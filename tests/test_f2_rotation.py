"""F2 optimal event-order engine — rotation resolver and cooldown cadence.

Covers the combo layer (src/calculator/rotation_resolver.py) end to end:

1. Per-combo-champion parse-level assertions: ``run_fight`` derives the
   documented cast order for each champion in the batch, and the
   ``/api/calculate``-shaped ``rotation`` receipt carries the order plus
   a rationale that names the setup/consume relationship.
2. The DPS-scoring helper ranks the parsed abilities against their
   per-rank cooldowns (the data-driven signal behind the table).
3. Time-based fights prove the derived order respects cooldowns:
   Cassiopeia recasts Q at its cooldown intervals with Twin Fang spam
   between reapplications (and strictly more E casts than the fixed
   default order in a short window); Varus' Blight detonation rides the
   Q cast that follows the auto-applied stacks.
"""

import pytest

from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import ONE_ROTATION_DURATION, FightParams, run_fight
from src.calculator.rotation_resolver import (
    COMBO_TABLE,
    build_rotation_receipt,
    rank_ability_dps,
    resolve_cast_order,
)

_COMBO_CHAMPIONS = [
    "Cassiopeia",
    "Varus",
    "Brand",
    "Vladimir",
    "Aatrox",
    "Jhin",
    "Annie",
    "Lux",
    "Zed",
    "Aphelios",
]

_EXPECTED_ORDERS = {
    "Cassiopeia": ["Q", "E", "W", "R"],
    "Varus": ["Q", "E", "R", "W"],
    "Brand": ["Q", "R", "E", "W"],
    "Vladimir": ["R", "Q", "E", "W"],
    "Aatrox": ["R", "Q", "W"],
    "Jhin": ["Q", "W", "E", "R"],
    "Annie": ["E", "R", "Q", "W"],
    "Lux": ["E", "Q", "R", "W"],
    "Zed": ["W", "E", "Q", "R"],
    "Aphelios": ["Q", "W", "R"],
}

_RATIONALE_FRAGMENTS = {
    "Cassiopeia": ("poison", "E-spam"),
    "Varus": ("Blight", "detonat"),
    "Brand": ("Blaze", "spread"),
    "Vladimir": ("amplif", "mark"),
    "Aatrox": ("bonus AD", "buff"),
    "Jhin": ("4th shot", "crit"),
    "Annie": ("stun", "Tibbers", "shield"),
    "Lux": ("slow", "root"),
    "Zed": ("shadow", "Death Mark"),
    "Aphelios": ("weapon", "swap"),
}


@pytest.fixture(scope="module")
def champion_by_name():
    champions = fetch_champion_data()
    return {data.get("name"): data for data in champions.values()}


def _params(one_rotation=True, duration=None, uptime=0.0, cast_order=None):
    return FightParams(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=(
            duration if duration is not None else ONE_ROTATION_DURATION
        ),
        auto_attack_uptime=uptime,
        one_rotation=one_rotation,
        include_actives=True,
        cast_order=cast_order,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options=None,
        deterministic=True,
    )


def _run(champion_data, level=11, one_rotation=True, duration=None, uptime=0.0):
    return run_fight(
        champion_data,
        level,
        [],
        _params(one_rotation=one_rotation, duration=duration, uptime=uptime),
    )


# ---------------------------------------------------------------------------
# Combo table shape
# ---------------------------------------------------------------------------


class TestComboTable:
    def test_batch_has_ten_combo_champions(self) -> None:
        assert set(COMBO_TABLE) == set(_COMBO_CHAMPIONS)

    def test_every_rule_has_order_rationale_and_sources(self) -> None:
        for name, rule in COMBO_TABLE.items():
            assert rule.champion == name
            assert rule.order, f"{name} combo has an empty order"
            assert rule.rationale, f"{name} combo has no rationale"
            assert rule.sources, f"{name} combo has no sourced atoms"
            assert len(set(rule.order)) == len(
                rule.order
            ), f"{name} combo order repeats a slot"
            for slot in rule.order:
                assert slot in {
                    "Q",
                    "W",
                    "E",
                    "R",
                    "P",
                }, f"{name} combo references unknown slot {slot}"

    def test_resolve_cast_order_uses_table_then_default(self) -> None:
        order, rule = resolve_cast_order("Cassiopeia", {})
        assert order == ["Q", "E", "W", "R"]
        assert rule is not None and rule.champion == "Cassiopeia"
        # A champion with no combo signal keeps the engine default (with Q2).
        order, rule = resolve_cast_order("NoSuchChampion", {})
        assert rule is None
        assert order == list(DEFAULT_CAST_ORDER)


# ---------------------------------------------------------------------------
# Parse-level rotation assertions per combo champion
# ---------------------------------------------------------------------------


class TestParseLevelRotations:
    @pytest.mark.parametrize("champion", _COMBO_CHAMPIONS)
    def test_derived_cast_order_matches_the_combo_table(
        self, champion, champion_by_name
    ) -> None:
        result = _run(champion_by_name[champion])
        rotation = result["rotation"]
        assert rotation["cast_order"] == _EXPECTED_ORDERS[champion]
        assert rotation["order"] == _EXPECTED_ORDERS[champion]

    @pytest.mark.parametrize("champion", _COMBO_CHAMPIONS)
    def test_rationale_names_the_driving_mechanic(
        self, champion, champion_by_name
    ) -> None:
        result = _run(champion_by_name[champion])
        rationale = result["rotation"]["rationale"].lower()
        for fragment in _RATIONALE_FRAGMENTS[champion]:
            assert fragment.lower() in rationale, (
                f"{champion} rationale should mention {fragment!r}: "
                f"{result['rotation']['rationale']}"
            )

    def test_cassiopeia_opens_with_poison_and_consumes_with_e(
        self, champion_by_name
    ) -> None:
        result = _run(champion_by_name["Cassiopeia"])
        rotation = result["rotation"]
        assert rotation["setup"] == ["Q", "W"]
        assert rotation["consume"] == ["E"]
        assert rotation["sources"]

    def test_varus_marks_blight_as_setup_and_q_as_detonator(
        self, champion_by_name
    ) -> None:
        result = _run(champion_by_name["Varus"])
        rotation = result["rotation"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["Q", "E", "R"]
        # The atom that drives the rule: W's on-hit applies Blight and Q's
        # post_hit_proc prices the detonation.
        abilities = _parse_abilities(champion_by_name["Varus"])
        assert abilities["W"]["on_hit"]
        assert abilities["Q"]["post_hit_proc"]["name"] == "Blight Detonation"

    def test_vladimir_opens_with_r_hemoplague(self, champion_by_name) -> None:
        result = _run(champion_by_name["Vladimir"])
        rotation = result["rotation"]
        assert rotation["cast_order"][0] == "R"
        assert rotation["setup"] == ["R"]
        assert "10%" in rotation["rationale"]

    def test_aatrox_buffs_with_r_before_damage(self, champion_by_name) -> None:
        result = _run(champion_by_name["Aatrox"])
        rotation = result["rotation"]
        assert rotation["cast_order"][0] == "R"
        assert rotation["setup"] == ["R"]
        assert "bonus AD" in rotation["rationale"]

    def test_lux_slows_roots_then_ults(self, champion_by_name) -> None:
        result = _run(champion_by_name["Lux"])
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["E", "Q", "R", "W"]
        assert rotation["setup"] == ["E", "Q"]
        assert rotation["consume"] == ["R"]

    def test_zed_places_shadow_before_burst(self, champion_by_name) -> None:
        result = _run(champion_by_name["Zed"])
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["W", "E", "Q", "R"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["R"]

    def test_aphelios_weapon_q_opens_then_swap_then_r(self, champion_by_name) -> None:
        result = _run(champion_by_name["Aphelios"])
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["Q", "W", "R"]
        assert rotation["setup"] == ["Q", "W"]
        assert "weapon" in rotation["rationale"].lower()

    @pytest.mark.parametrize(
        ("champion", "aoe_slots"),
        [
            ("Cassiopeia", {"W": 5, "R": 5}),
            ("Varus", {"E": 5}),
            ("Brand", {"W": 5, "E": 5}),
            ("Vladimir", {"W": 5, "E": 5, "R": 5}),
            ("Aatrox", {"Q": 5, "W": 2}),
            ("Jhin", {"Q": 4, "E": 5}),
            ("Annie", {"W": 5, "R": 5}),
            ("Lux", {"E": 5, "R": 5, "Q": 2}),
            ("Zed", {"E": 5}),
            ("Aphelios", {"R": 5, "Q": 5}),
        ],
    )
    def test_receipt_carries_aoe_target_caps(
        self, champion, aoe_slots, champion_by_name
    ) -> None:
        """AoE modeling: the receipt tells the UI which slots hit more than
        one champion and how many."""
        result = _run(champion_by_name[champion])
        assert result["rotation"]["aoe"] == aoe_slots

    def test_annie_opens_with_molten_shield(self, champion_by_name) -> None:
        """Buffs-first: Annie's shield row is in the derived cast order so
        the E8 shield ledger still casts it."""
        result = _run(champion_by_name["Annie"])
        rotation = result["rotation"]
        assert rotation["cast_order"][0] == "E"
        assert "shield" in rotation["rationale"].lower()
        assert "E" in result["breakdown"]


def _parse_abilities(champion_data):
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.stats import calculate_total_stats

    stats = calculate_total_stats(champion_data, 11, [])
    return parse_champion_abilities(
        champion_data,
        11,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=None,
    )


# ---------------------------------------------------------------------------
# DPS ranking signal (data-driven scoring behind the table)
# ---------------------------------------------------------------------------


class TestDpsRanking:
    def test_ranks_by_raw_over_effective_cooldown(self) -> None:
        abilities = {
            "Q": {"total_raw": 100.0, "cooldown": 10.0},
            "W": {"total_raw": 100.0, "cooldown": 5.0},
            "E": {"total_raw": 0.0, "cooldown": 2.0},
            "P": {"total_raw": 50.0, "cooldown": 0.0},  # passive: not a cast
        }
        ranked = rank_ability_dps(abilities)
        assert [slot for slot, *_ in ranked] == ["W", "Q"]

    def test_ability_haste_lowers_effective_cooldown(self) -> None:
        abilities = {"Q": {"total_raw": 100.0, "cooldown": 10.0}}
        base = rank_ability_dps(abilities)[0][1]
        hasted = rank_ability_dps(abilities, ability_haste=100.0)[0][1]
        assert hasted == pytest.approx(base * 2.0)

    def test_cassiopeia_e_outranks_q_as_the_spam_tool(self) -> None:
        """Signal (b): at the parsed per-rank numbers E's 0.75s cooldown
        makes it the highest-DPS cast even though Q's poison total is
        higher per cast."""
        abilities = _parse_abilities(
            next(
                c
                for c in fetch_champion_data().values()
                if c.get("name") == "Cassiopeia"
            )
        )
        ranked = rank_ability_dps(abilities)
        slots = [slot for slot, *_ in ranked]
        assert slots[0] == "E"
        assert "Q" in slots

    def test_aoe_slot_weights_by_roster_target_count(self) -> None:
        """AoE: at five enemies, an ability that hits all five outranks a
        single-target nuke of the same raw damage per cast."""
        abilities = {
            "Q": {"total_raw": 400.0, "cooldown": 10.0},  # single target
            "W": {"total_raw": 100.0, "cooldown": 10.0},  # AoE, hits 5
        }
        aoe = {"W": 5}
        solo = rank_ability_dps(abilities, aoe=aoe, target_count=1)
        assert [slot for slot, *_ in solo] == ["Q", "W"]
        five = rank_ability_dps(abilities, aoe=aoe, target_count=5)
        assert [slot for slot, *_ in five] == ["W", "Q"]
        # The multiplier is min(target_count, cap), never more than the cap.
        w_dps = dict((s, d) for s, d, *_ in five)["W"]
        capped = rank_ability_dps(abilities, aoe=aoe, target_count=9)
        assert dict((s, d) for s, d, *_ in capped)["W"] == w_dps


# ---------------------------------------------------------------------------
# Time-based fights: cooldown-aware cadence
# ---------------------------------------------------------------------------


class TestTimedCadence:
    def test_cassiopeia_q_recasts_at_cd_intervals_with_e_spam_between(
        self, champion_by_name
    ) -> None:
        """Q at t=0, then again at 0.25s cast + 3.5s cooldown = 3.75s; E
        fills the gap on its own 0.875s cycle.  The receipt order shows
        the Q, E, E, E, Q cadence."""
        result = _run(
            champion_by_name["Cassiopeia"],
            one_rotation=False,
            duration=8.0,
            uptime=0.0,
        )
        timeline = [
            (round(float(event["time"]), 2), event["slot"])
            for event in result["cast_timeline"]
        ]
        q_times = [time for time, slot in timeline if slot == "Q"]
        assert q_times[0] == 0.0
        assert q_times[1] == pytest.approx(3.75, abs=0.01)
        assert q_times[2] == pytest.approx(7.5, abs=0.01)
        # E casts sit between the Q reapplications.
        e_times = [time for time, slot in timeline if slot == "E"]
        assert any(0.25 < time < 3.75 for time in e_times)
        assert any(3.75 < time < 7.5 for time in e_times)
        # The receipt order reads Q, E, E, E, Q, ... (not E before Q).
        order = result["rotation"]["order"]
        assert order[0] == "Q"
        assert order[1] == "E"
        assert "Q" in order[2:]
        # W's zone cast happens after E on the shared timeline.
        w_time = next(time for time, slot in timeline if slot == "W")
        assert w_time > e_times[0]

    def test_cassiopeia_combo_order_lands_more_es_than_fixed_order(
        self, champion_by_name
    ) -> None:
        """The whole point: E before W on the shared timeline starts the
        spam cadence earlier — strictly more Twin Fangs in a 3s window."""
        data = champion_by_name["Cassiopeia"]
        combo = _run(data, one_rotation=False, duration=3.0)
        default = run_fight(
            data,
            11,
            [],
            _params(
                one_rotation=False,
                duration=3.0,
                cast_order=list(DEFAULT_CAST_ORDER),
            ),
        )
        assert combo["breakdown"]["E"]["casts"] > default["breakdown"]["E"]["casts"]
        assert combo["total_damage"] > default["total_damage"]

    def test_varus_autos_apply_blight_before_q_detonates(
        self, champion_by_name
    ) -> None:
        """Timed fight with an auto stream: the Blight detonation rides the
        Q cast (post_hit_proc) after the auto-applied stacks exist, and the
        receipt marks W (the on-hit applier) as setup."""
        result = _run(
            champion_by_name["Varus"],
            one_rotation=False,
            duration=5.0,
            uptime=1.0,
        )
        rotation = result["rotation"]
        assert rotation["setup"] == ["W"]
        assert rotation["consume"] == ["Q", "E", "R"]
        assert rotation["order"][0] == "Q"
        # The auto stream exists and the detonation is priced on Q.
        assert result["breakdown"]["auto_attacks"]["count"] > 0
        detonation = result["breakdown"]["blight_detonation"]
        assert detonation["total_damage"] > 0
        q_casts = result["breakdown"]["Q"]["casts"]
        # One sourced detonation per Q cast (conservative single-detonator
        # model, documented in the Varus module).
        assert detonation["count"] == q_casts

    def test_zed_w_first_lets_e_recast_inside_the_window(
        self, champion_by_name
    ) -> None:
        """The W-shadow opener costs zero cast time, so E fires at t=0 and
        again at t=5.0 — two casts instead of the fixed order's one."""
        data = champion_by_name["Zed"]
        combo = _run(data, one_rotation=False, duration=5.0, uptime=1.0)
        default = run_fight(
            data,
            11,
            [],
            _params(
                one_rotation=False,
                duration=5.0,
                uptime=1.0,
                cast_order=list(DEFAULT_CAST_ORDER),
            ),
        )
        assert combo["breakdown"]["E"]["casts"] > default["breakdown"]["E"]["casts"]
        assert combo["rotation"]["order"][0] == "W"

    def test_receipt_fallback_documents_the_default_order(self) -> None:
        receipt = build_rotation_receipt(
            "NoSuchChampion",
            cast_order=list(DEFAULT_CAST_ORDER),
            cast_timeline=[],
            rule=None,
        )
        assert receipt["order"] == list(DEFAULT_CAST_ORDER)
        assert "default" in receipt["rationale"].lower()
        assert receipt["setup"] == []
        assert receipt["consume"] == []

    def test_receipt_defers_to_explicit_user_order(self, champion_by_name) -> None:
        """An explicit caller-supplied order wins and is labelled as such —
        the combo layer never overrides it."""
        from src.calculator.pipeline import FightParams, run_fight

        data = champion_by_name["Cassiopeia"]
        params = FightParams(
            target_health=2000.0,
            target_bonus_health=0.0,
            target_armor=50.0,
            target_magic_resistance=40.0,
            fight_duration_seconds=ONE_ROTATION_DURATION,
            auto_attack_uptime=0.0,
            one_rotation=True,
            include_actives=True,
            cast_order=["R", "E", "Q", "W"],
            auto_attacks_only=False,
            ability_ranks=None,
            champion_options=None,
            deterministic=True,
        )
        result = run_fight(data, 11, [], params)
        rotation = result["rotation"]
        assert rotation["cast_order"] == ["R", "E", "Q", "W"]
        assert rotation["order"] == ["R", "E", "Q", "W"]
        assert "Custom order" in rotation["rationale"]
