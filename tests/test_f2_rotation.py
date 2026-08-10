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

from src.calculator.cast_dependency import CustomOrderViolatesDependencyError
from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import ONE_ROTATION_DURATION, FightParams, run_fight
from src.calculator.rotation_resolver import (
    CAST_ORDER_OVERRIDES,
    ORDER_OVERRIDE_REASONS,
    ComboRule,
    _validate_override_reasons,
    build_rotation_receipt,
    derive_champion_rule,
    rank_ability_dps,
    resolve_cast_order,
)

_OVERRIDE_CHAMPIONS = [
    "Cassiopeia",
    "Varus",
    "Brand",
    "Vladimir",
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
    "Jhin": ("4th shot", "crit"),
    "Annie": ("stun", "Tibbers", "shield"),
    "Lux": ("slow", "root"),
    "Zed": ("shadow", "Death Mark"),
    "Aphelios": ("weapon", "swap"),
}


# The engine's ``DEFAULT_CAST_ORDER`` still names ``Q2`` positionally, which
# is the resolver's own fallback and not something a caller may request: a
# requested order may name only slots the champion's parse offers, and
# neither Cassiopeia nor Zed has a recast row (D-11).  The Q2 element was
# always inert for them, so dropping it is what "the fixed order" meant here.
FIXED_ORDER = [slot for slot in DEFAULT_CAST_ORDER if slot != "Q2"]


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


def _parse_for(champion_data, *, level=18, splinters=None):
    """One champion's parse, optionally at a splinter count, for receipts."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.stats import calculate_total_stats

    stats = calculate_total_stats(dict(champion_data), level, [])
    return parse_champion_abilities(
        dict(champion_data),
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options=None if splinters is None else {"splinters": splinters},
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


class TestCastOrderOverrides:
    def test_the_table_holds_exactly_the_hand_seeds(self) -> None:
        assert set(CAST_ORDER_OVERRIDES) == set(_OVERRIDE_CHAMPIONS)

    def test_every_override_says_why_it_is_still_hand_held(self) -> None:
        """P5-f: the retirement frontier is counted, not claimed.

        A seed that cannot name its reason from the closed set is either a
        mechanic its module should declare or a preference nobody wrote
        down — and it would sit in the table forever either way.
        """
        for name, rule in CAST_ORDER_OVERRIDES.items():
            assert (
                rule.override_reason in ORDER_OVERRIDE_REASONS
            ), f"{name} declares override_reason {rule.override_reason!r}"

    def test_a_derived_rule_carries_no_override_reason(self) -> None:
        assert (
            ComboRule(champion="X", order=("Q",), rationale="").override_reason is None
        )

    def test_an_unreasoned_override_fails_at_import(self) -> None:
        """The check is reachable: it fires on a table with a bad entry."""
        original = dict(CAST_ORDER_OVERRIDES)
        CAST_ORDER_OVERRIDES["Synthetic"] = ComboRule(
            champion="Synthetic", order=("Q",), rationale="", override_reason="vibes"
        )
        try:
            with pytest.raises(ValueError, match="override_reason"):
                _validate_override_reasons()
        finally:
            CAST_ORDER_OVERRIDES.clear()
            CAST_ORDER_OVERRIDES.update(original)

    def test_every_rule_has_order_rationale_and_sources(self) -> None:
        for name, rule in CAST_ORDER_OVERRIDES.items():
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
                    "Q2",  # a recast slot rides its parent's schedule
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


class TestDerivedPathRotations:
    """Champions whose order the derivation computes, not a hand seed.

    Every row here used to live in ``_OVERRIDE_CHAMPIONS``.  A retirement
    moves its assertions rather than deleting them: the same order, the
    same mechanic, now asserted on the path that computes it.  Syndra's
    row additionally demands the declared kind and the wiki revision in
    the rationale, which a hand seed's prose never carried; the others
    were seeds the derivation already reproduced, held only until a
    deletion commit proved it on both baselines (``pending_primitive``).
    """

    @pytest.mark.parametrize(
        ("champion", "order", "aoe", "fragments"),
        [
            (
                "Syndra",
                ["Q", "Q2", "E", "W", "R"],
                {"Q": 5, "Q2": 5, "W": 5, "E": 5, "R": 1, "passive": 1},
                ("sphere", "stun", "cc_enabler", "@4024662"),
            ),
            (
                "Aatrox",
                ["R", "Q", "W"],
                {"Q": 5, "W": 1, "R": 1, "passive": 1},
                ("stat_buff(bonus_attack_damage)", "amplifies ability damage"),
            ),
        ],
    )
    def test_the_derivation_reproduces_the_order_the_seed_pinned(
        self, champion, order, aoe, fragments, champion_by_name
    ) -> None:
        rotation = _run(champion_by_name[champion])["rotation"]
        assert rotation["cast_order"] == order
        assert rotation["order"][: len(order)] == order
        assert rotation["aoe"] == aoe
        rationale = rotation["rationale"].lower()
        for fragment in fragments:
            assert (
                fragment.lower() in rationale
            ), f"{champion} rationale should mention {fragment!r}: {rationale}"

    @pytest.mark.parametrize("champion", ["Syndra", "Aatrox"])
    def test_the_rule_is_derived_and_carries_no_override_reason(
        self, champion, champion_by_name
    ) -> None:
        _, rule = resolve_cast_order(
            champion,
            _parse_for(champion_by_name[champion]),
            champion_data=champion_by_name[champion],
        )
        assert rule is not None and rule.derived is True
        assert rule.override_reason is None
        assert champion not in CAST_ORDER_OVERRIDES


class TestParseLevelRotations:
    @pytest.mark.parametrize("champion", _OVERRIDE_CHAMPIONS)
    def test_derived_cast_order_matches_the_combo_table(
        self, champion, champion_by_name
    ) -> None:
        result = _run(champion_by_name[champion])
        rotation = result["rotation"]
        assert rotation["cast_order"] == _EXPECTED_ORDERS[champion]
        assert rotation["order"] == _EXPECTED_ORDERS[champion]

    @pytest.mark.parametrize("champion", _OVERRIDE_CHAMPIONS)
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
                cast_order=FIXED_ORDER,
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
        again at t=5.0 — two casts instead of the later E's one.

        The control was the engine's fixed default order until Zed's module
        declared that Q and E each require the Shadow placement: an order
        opening on Q now inverts that declaration and is refused outright
        (D-86, asserted in the next test).  So the control moved to the
        nearest legal order — W still first, E one slot later — which is
        what isolates E's cadence rather than the opener.
        """
        data = champion_by_name["Zed"]
        combo = _run(data, one_rotation=False, duration=5.0, uptime=1.0)
        late_e = run_fight(
            data,
            11,
            [],
            _params(
                one_rotation=False,
                duration=5.0,
                uptime=1.0,
                cast_order=["W", "Q", "E", "R"],
            ),
        )
        assert combo["breakdown"]["E"]["casts"] > late_e["breakdown"]["E"]["casts"]
        assert combo["rotation"]["order"][0] == "W"

    def test_zeds_declaration_refuses_an_order_that_skips_the_shadow(
        self, champion_by_name
    ) -> None:
        """The fixed default order is no longer a legal request for Zed.

        D-86 at a champion the phase's criteria never name: a declared
        prerequisite states impossibility, so ``Q, W, E, R`` — the control
        the test above used to run — comes back as a refusal quoting the
        Shadow-placement mechanic rather than as a fight priced against a
        kit Zed cannot cast.
        """
        with pytest.raises(CustomOrderViolatesDependencyError) as caught:
            run_fight(
                champion_by_name["Zed"],
                11,
                [],
                _params(
                    one_rotation=False,
                    duration=5.0,
                    uptime=1.0,
                    cast_order=FIXED_ORDER,
                ),
            )
        assert (caught.value.dependency.slot, caught.value.dependency.requires) == (
            "Q",
            "W",
        )
        assert caught.value.dependency.source in str(caught.value)

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


class TestTheReceiptPublishesTheMerge:
    """``rotation.dependencies`` — what the merge did, on every response."""

    _LEDGERS = (
        "active",
        "inactive",
        "suppressed",
        "latent",
        "confirmed_by_inference",
        "conflicts",
        "unconsulted",
    )

    def test_a_non_declaring_champion_publishes_empty_ledgers(
        self, champion_by_name
    ) -> None:
        """Empty and absent must not read alike."""
        receipt = _run(champion_by_name["Ahri"])["rotation"]
        assert set(receipt["dependencies"]) == set(self._LEDGERS)
        assert all(rows == [] for rows in receipt["dependencies"].values())

    def test_the_fallback_receipt_still_carries_the_shape(self) -> None:
        receipt = build_rotation_receipt(
            "NoSuchChampion",
            cast_order=list(DEFAULT_CAST_ORDER),
            cast_timeline=[],
            rule=None,
        )
        assert set(receipt["dependencies"]) == set(self._LEDGERS)

    def test_a_declaring_champion_publishes_its_mechanic_and_source(
        self, champion_by_name
    ) -> None:
        """The rows name the mechanic, not the rule that produced them."""
        rule = derive_champion_rule(
            "Syndra",
            _parse_for(champion_by_name["Syndra"], splinters=120),
            champion_by_name["Syndra"],
            None,
            champion_options={"splinters": 120},
        )
        receipt = build_rotation_receipt(
            "Syndra", cast_order=list(rule.order), cast_timeline=[], rule=rule
        )
        rows = receipt["dependencies"]
        assert len(rows["active"]) == 2
        assert "cc_enabler" in rows["active"][0]
        assert "wiki.leagueoflegends.com" in rows["active"][0]
        assert rows["suppressed"] and rows["latent"]
        assert rows["conflicts"] and "covered" in rows["conflicts"][0]

    def test_an_inactive_declaration_is_published_as_inactive(
        self, champion_by_name
    ) -> None:
        rule = derive_champion_rule(
            "Syndra",
            _parse_for(champion_by_name["Syndra"], splinters=39),
            champion_by_name["Syndra"],
            None,
            champion_options={"splinters": 39},
        )
        receipt = build_rotation_receipt(
            "Syndra", cast_order=list(rule.order), cast_timeline=[], rule=rule
        )
        assert "Q2 not in this parse" in receipt["dependencies"]["inactive"][0]

    def test_a_seeded_declarer_names_the_declarations_nobody_consulted(
        self, champion_by_name
    ) -> None:
        """Zed declares and is still seeded: his ledgers must say so.

        Six empty ledgers would read "this module declares nothing",
        which is a different fact — and this row is how the frontier
        counts a declarer whose hand seed still wins.  Syndra held this
        row until her seed retired against her declaration (D-89); Zed
        and Brand are the head-only declarers whose tails are DPS
        preferences no declaration can honestly express, so their seeds
        stay and the disclosure has to stay with them.
        """
        order, rule = resolve_cast_order(
            "Zed",
            _parse_for(champion_by_name["Zed"]),
            champion_data=champion_by_name["Zed"],
        )
        assert order == list(CAST_ORDER_OVERRIDES["Zed"].order)
        receipt = build_rotation_receipt(
            "Zed", cast_order=order, cast_timeline=[], rule=rule
        )
        rows = receipt["dependencies"]["unconsulted"]
        assert len(rows) == 2
        assert "hand seed" in rows[0] and "dps_tiebreak" in rows[0]
        assert rows == receipt["dependencies"]["unconsulted"]
        assert receipt["dependencies"]["active"] == []

    def test_a_seeded_champion_that_declares_nothing_has_empty_ledgers(
        self, champion_by_name
    ) -> None:
        order, rule = resolve_cast_order(
            "Cassiopeia",
            _parse_for(champion_by_name["Cassiopeia"]),
            champion_data=champion_by_name["Cassiopeia"],
        )
        receipt = build_rotation_receipt(
            "Cassiopeia", cast_order=order, cast_timeline=[], rule=rule
        )
        assert all(rows == [] for rows in receipt["dependencies"].values())
