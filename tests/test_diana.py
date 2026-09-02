"""Tests for the Diana slot map (src.calculator.champions.diana).

Hand-validated against the wiki at level 20, ranks Q5/W5/E5/R3, 100 AP
(the spec's sanity numbers), plus the structural invariants the module
exists for: the passive's tripled-AS stat buff feeding the auto count,
the cleave riding the auto stream (floor(autos/3), auto-attack bucket,
auto-stream pen), E's two-dash activation, and R's per-champion beam
bonus.
"""

import pytest

from src.calculator.champions import diana, parse_champion_abilities
from src.calculator.champions.slotlib import (
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from src.calculator.damage import (
    FightConfig,
    calculate_fight_damage,
    split_auto_vs_ability,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from tests import cc_review

# Round stats so wiki arithmetic is checkable by eye. attack_speed_ratio
# is 0 by default so the passive's AS buff doesn't move the auto-count
# math; the buff-feeds-the-count test overrides it.
_STATS = {
    "armor_penetration_bonus_percent": 0.0,
    "lethality": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "resource_regen_per_second": 0.0,
    "ultimate_haste": 0.0,
    "attack_damage": 100.0,
    "base_attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
    "ability_power": 100.0,
    "attack_speed": 1.0,
    "attack_speed_ratio": 0.0,
    "bonus_attack_speed": 0.0,
    "critical_strike_chance": 0.0,
    "ability_haste": 0.0,
    "basic_ability_haste": 0.0,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "flat_armor_penetration": 0.0,
    "armor_penetration_percent": 0.0,
    "max_mana": 500.0,
    "bonus_mana": 0.0,
    "health": 2000.0,
    "bonus_health": 0.0,
    "is_melee": True,
    "level": 20,
}
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(diana_data, *, level=20, ranks=None, options=None, stats=None):
    """Parse Diana at explicit ranks with the round test stats."""
    return diana.parse_abilities(
        diana_data,
        level,
        (stats or _STATS)["ability_power"],
        ranks or _RANKS,
        champion_options=options,
        champion_stats=dict(stats or _STATS),
        target_stats={"target_max_health": 2000.0},
    )


def _timed_options(duration=9.0, uptime=1.0, **extra):
    """Reserved-key options as the pipeline injects them for timed fights."""
    options = {"fight_duration_seconds": duration, "auto_attack_uptime": uptime}
    options.update(extra)
    return options


class TestAbilityValues:
    """The spec's sanity numbers: level 20, Q5/W5/E5/R3, 100 AP."""

    def test_q_rank_5(self, diana_data) -> None:
        """210 base + 70% AP = 280 magic."""
        abilities = _parse(diana_data)
        assert abilities["Q"]["damage_type"] == "magic"
        assert abilities["Q"]["total_raw"] == pytest.approx(280.0)

    def test_w_rank_5_is_all_three_orbs(self, diana_data) -> None:
        """204 base + 54% AP = 258 magic — the Total attribute, not per-orb."""
        abilities = _parse(diana_data)
        assert abilities["W"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == pytest.approx(258.0)

    def test_e_rank_5_is_two_dashes_of_190(self, diana_data) -> None:
        """130 + 60% AP = 190 per dash, x2 with the Moonlight reset."""
        entry = _parse(diana_data)["E"]
        assert entry["damage_type"] == "magic"
        assert entry["total_raw"] == pytest.approx(380.0)
        # Per-dash damage on the amount, never pre-multiplied (Amumu trap).
        (part,) = entry["parts"]
        assert part.amount == pytest.approx(190.0)
        assert part.count == 2
        assert entry["cast_instances"] == 2

    def test_r_rank_3_one_champion_pulled(self, diana_data) -> None:
        """400 base + 60% AP = 460 magic; the pull itself deals nothing."""
        abilities = _parse(diana_data)
        assert abilities["R"]["damage_type"] == "magic"
        assert abilities["R"]["total_raw"] == pytest.approx(460.0)

    def test_cleave_is_320_per_proc(self, diana_data) -> None:
        """270 base + 50% AP = 320 magic per cleave at level 20."""
        abilities = _parse(diana_data, options=_timed_options())
        entry = abilities["auto_attacks_moonsilver_cleave"]
        assert entry["damage_type"] == "magic"
        (part,) = entry["parts"]
        assert part.amount == pytest.approx(320.0)


class TestCooldownsAndCastTimes:
    """Cooldowns at the tested ranks; cast times land on Q and R only."""

    def test_cooldowns(self, diana_data) -> None:
        abilities = _parse(diana_data)
        assert abilities["Q"]["cooldown"] == pytest.approx(6.0)  # rank 5
        assert abilities["W"]["cooldown"] == pytest.approx(9.0)  # rank 5
        assert abilities["E"]["cooldown"] == pytest.approx(14.0)  # rank 5
        assert abilities["R"]["cooldown"] == pytest.approx(80.0)  # rank 3

    def test_cast_times(self, diana_data) -> None:
        """Q/R castTime is '0.25'; W/E are the string 'none' (instant)."""
        abilities = _parse(diana_data)
        assert abilities["Q"]["cast_time"] == pytest.approx(0.25)
        assert abilities["R"]["cast_time"] == pytest.approx(0.25)
        assert "cast_time" not in abilities["W"]
        assert "cast_time" not in abilities["E"]


class TestPassiveStatBuff:
    """Moonsilver Blade's TRIPLED attack speed, assumed always active."""

    def test_tripled_values_at_levels_1_and_20(self, diana_data) -> None:
        """45% at level 1, 112.06% at level 20 (the tripled array)."""
        at_1 = _parse(diana_data, level=1)["passive"]
        at_20 = _parse(diana_data)["passive"]
        assert at_1["stat_buff"] == {"bonus_attack_speed": pytest.approx(45.0)}
        assert at_20["stat_buff"] == {"bonus_attack_speed": pytest.approx(112.06)}

    def test_buff_entry_deals_no_damage_but_never_vanishes(self, diana_data) -> None:
        entry = _parse(diana_data)["passive"]
        assert entry["total_raw"] == 0.0
        assert entry["name"] == "Moonsilver Blade"

    def test_fight_champion_stats_show_the_buffed_attack_speed(
        self, diana_data
    ) -> None:
        """run_fight reports fight-effective stats (the Gnar panel rule)."""
        level = 18
        before = calculate_total_stats(diana_data, level, [])
        tripled = sum_modifiers(
            find_named_leveling(
                diana_data["abilities"]["P"][0], "Per-Level Scaling", occurrence=1
            ),
            level,
        )
        result = run_fight(diana_data, level, [], _fight_params())
        stats = result["champion_stats"]
        assert stats["bonus_attack_speed"] == pytest.approx(
            before["bonus_attack_speed"] + tripled
        )
        assert stats["attack_speed"] == pytest.approx(
            before["attack_speed"] + before["attack_speed_ratio"] * tripled / 100.0
        )


class TestCleaveCadence:
    """floor(autos / 3) procs, riding the auto stream only."""

    def test_three_cleaves_from_nine_autos(self, diana_data) -> None:
        """AS 1.0 (ratio 0), 9s at full uptime: 9 autos -> 3 cleaves."""
        entry = _parse(diana_data, options=_timed_options(duration=9.0))[
            "auto_attacks_moonsilver_cleave"
        ]
        assert entry["proc_count"] == 3
        assert entry["total_raw"] == pytest.approx(960.0)
        assert entry["unit"] == "cleaves"

    def test_count_floors_partial_cycles(self, diana_data) -> None:
        """8 autos -> 2 cleaves (the third cycle never completes)."""
        entry = _parse(diana_data, options=_timed_options(duration=8.0))[
            "auto_attacks_moonsilver_cleave"
        ]
        assert entry["proc_count"] == 2

    def test_passive_as_buff_feeds_the_auto_count(self, diana_data) -> None:
        """With a real AS ratio the tripled buff raises the cleave count:
        AS 1.0 + 0.625 x 1.1206 = 1.700 -> 13 autos in 8s -> 4 cleaves."""
        stats = dict(_STATS, attack_speed_ratio=0.625)
        entry = _parse(diana_data, options=_timed_options(duration=8.0), stats=stats)[
            "auto_attacks_moonsilver_cleave"
        ]
        assert entry["proc_count"] == 4

    def test_no_fight_window_means_no_cleave_slot(self, diana_data) -> None:
        """Per-cast mode (one-rotation / direct parse): no auto stream."""
        abilities = _parse(diana_data)
        assert "auto_attacks_moonsilver_cleave" not in abilities
        assert set(abilities) == {"passive", "Q", "W", "E", "R"}

    def test_zero_uptime_means_no_cleave_slot(self, diana_data) -> None:
        abilities = _parse(diana_data, options=_timed_options(uptime=0.0))
        assert "auto_attacks_moonsilver_cleave" not in abilities

    def test_cleave_is_not_an_on_hit_effect(self, diana_data) -> None:
        """Spell AoE riding the autos: no on-hit payload, no item on-hit
        application — it must never scale with on-hit effectiveness."""
        entry = _parse(diana_data, options=_timed_options())[
            "auto_attacks_moonsilver_cleave"
        ]
        assert "on_hit" not in entry
        assert "applies_item_on_hits" not in entry


def _fight_params(**overrides):
    """Timed-fight FightParams with explicit overrides."""
    defaults = {
        "target_health": 5000.0,
        "target_bonus_health": 0.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 8.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": False,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "deterministic": True,
    }
    defaults.update(overrides)
    return FightParams(**defaults)


class TestCleaveInFights:
    """The cleave row through the full pipeline: count agreement with the
    engine's auto count, the auto-attack bucket, and auto-stream pen."""

    def test_count_matches_the_fight_engines_buffed_auto_count(
        self, diana_data
    ) -> None:
        """Parse-time and fight-time auto counts must agree — both include
        the passive's tripled AS."""
        result = run_fight(diana_data, 18, [], _fight_params())
        breakdown = result["breakdown"]
        row = breakdown["auto_attacks_moonsilver_cleave"]
        assert row["unit"] == "cleaves"
        assert row["count"] == breakdown["auto_attacks"]["count"] // 3

    def test_cleave_buckets_as_auto_attack_damage(self, diana_data) -> None:
        """The Corki split rule: assert the bucket, not just the total."""
        breakdown = run_fight(diana_data, 18, [], _fight_params())["breakdown"]
        row = breakdown["auto_attacks_moonsilver_cleave"]
        assert row["total_damage"] > 0

        auto_dmg, ability_dmg = split_auto_vs_ability(breakdown)
        without = {
            k: v for k, v in breakdown.items() if k != "auto_attacks_moonsilver_cleave"
        }
        auto_without, ability_without = split_auto_vs_ability(without)
        assert auto_dmg - auto_without == pytest.approx(row["total_damage"])
        assert ability_dmg == pytest.approx(ability_without)

    def test_one_rotation_fight_has_no_cleave_row(self, diana_data) -> None:
        result = run_fight(
            diana_data,
            18,
            [],
            _fight_params(
                fight_duration_seconds=5.0, auto_attack_uptime=0.0, one_rotation=True
            ),
        )
        assert "auto_attacks_moonsilver_cleave" not in result["breakdown"]

    def test_zero_uptime_timed_fight_has_no_cleave_row(self, diana_data) -> None:
        result = run_fight(diana_data, 18, [], _fight_params(auto_attack_uptime=0.0))
        assert "auto_attacks_moonsilver_cleave" not in result["breakdown"]

    def test_cleave_takes_the_auto_stream_magic_pen(self, diana_data) -> None:
        """The Terminus split rule: the cleave is priced after the rotation
        switches to auto-attack pen, so its per-hit damage mitigates at the
        reported (auto-variant) effective MR — which Terminus stacks have
        reduced — while abilities never see that pen."""
        raw_per_cleave = extract_named(
            diana_data["abilities"]["P"][0], "Bonus Magic Damage", 18
        )  # 220 at level 18, no AP on this build

        plain = run_fight(diana_data, 18, [], _fight_params())
        terminus = run_fight(
            diana_data, 18, [get_item_by_name("Terminus")], _fight_params()
        )
        assert terminus["effective_mr"] < plain["effective_mr"]
        for result in (plain, terminus):
            row = result["breakdown"]["auto_attacks_moonsilver_cleave"]
            assert row["damage_per_hit"] == pytest.approx(
                raw_per_cleave * 100.0 / (100.0 + result["effective_mr"])
            )


class TestOptions:
    """Every declared option changes the parse; invalid values clamp."""

    def test_moonlight_reset_off_halves_e(self, diana_data) -> None:
        entry = _parse(diana_data, options={"moonlight_reset": False})["E"]
        assert entry["total_raw"] == pytest.approx(190.0)
        (part,) = entry["parts"]
        assert part.count == 1
        assert entry["cast_instances"] == 1

    def test_champions_pulled_5_reproduces_the_wiki_max(self, diana_data) -> None:
        """340/540/740 (+120% AP) — at 100 AP: 460/660/860."""
        expected = {1: 460.0, 2: 660.0, 3: 860.0}
        for rank, total in expected.items():
            entry = _parse(
                diana_data,
                ranks=dict(_RANKS, R=rank),
                options={"champions_pulled": 5},
            )["R"]
            assert entry["total_raw"] == pytest.approx(total)

    def test_champions_pulled_scales_linearly(self, diana_data) -> None:
        """Each champion beyond the first adds 85 + 15% AP = 100 at R3."""
        for pulled in range(1, 6):
            entry = _parse(diana_data, options={"champions_pulled": pulled})["R"]
            assert entry["total_raw"] == pytest.approx(460.0 + (pulled - 1) * 100.0)

    def test_champions_pulled_clamps_to_1_and_5(self, diana_data) -> None:
        low = _parse(diana_data, options={"champions_pulled": 0})["R"]
        high = _parse(diana_data, options={"champions_pulled": 9})["R"]
        assert low["total_raw"] == pytest.approx(460.0)
        assert high["total_raw"] == pytest.approx(860.0)


class TestFightIntegration:
    """Slot-map entries through calculate_fight_damage."""

    def test_both_e_dashes_land_in_one_rotation(self, diana_data) -> None:
        """380 raw vs 100 MR -> 190 mitigated."""
        abilities = _parse(diana_data)
        result = calculate_fight_damage(
            dict(_STATS),
            {"E": abilities["E"]},
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["E"]["total_damage"] == pytest.approx(190.0)


class TestJsonCrossChecks:
    """The JSON quirks the module depends on stay true."""

    def test_both_as_arrays_run_40_entries_past_the_level_cap(self, diana_data) -> None:
        passive = diana_data["abilities"]["P"][0]
        for occurrence in (0, 1):
            leveling = find_named_leveling(
                passive, "Per-Level Scaling", occurrence=occurrence
            )
            assert len(leveling["modifiers"][0]["values"]) == 40

    def test_tripled_array_is_three_times_the_base(self, diana_data) -> None:
        """Base (unused, documented) vs tripled, within JSON rounding."""
        passive = diana_data["abilities"]["P"][0]
        base = find_named_leveling(passive, "Per-Level Scaling", occurrence=0)
        tripled = find_named_leveling(passive, "Per-Level Scaling", occurrence=1)
        for level in (1, 6, 11, 18, 20):
            assert sum_modifiers(tripled, level) == pytest.approx(
                3.0 * sum_modifiers(base, level), abs=0.03
            )
        # The level-20 pins from the spec: 37.35% base, 112.06% tripled.
        assert sum_modifiers(base, 20) == pytest.approx(37.35)
        assert sum_modifiers(tripled, 20) == pytest.approx(112.06)

    def test_cleave_array_reaches_270_at_level_20(self, diana_data) -> None:
        passive = diana_data["abilities"]["P"][0]
        assert extract_named(passive, "Bonus Magic Damage", 20) == pytest.approx(270.0)

    def test_w_total_is_exactly_three_orbs(self, diana_data) -> None:
        ability = diana_data["abilities"]["W"][0]
        for rank in range(1, 6):
            per_orb = extract_named(
                ability, "Magic Damage per Orb", rank, {"ability_power": 100.0}
            )
            total = extract_named(
                ability, "Total Magic Damage", rank, {"ability_power": 100.0}
            )
            assert total == pytest.approx(3.0 * per_orb)

    def test_r_display_total_is_base_plus_four_bonuses(self, diana_data) -> None:
        """'Total Damage Vs. 5 Champions' is derived — the module must
        reproduce it from base + 4 x bonus."""
        ability = diana_data["abilities"]["R"][0]
        stats = {"ability_power": 100.0}
        for rank in range(1, 4):
            derived = extract_named(
                ability, "Magic Damage", rank, stats
            ) + 4.0 * extract_named(ability, "Bonus Damage Per Champion", rank, stats)
            display = extract_named(
                ability, "Total Damage Vs. 5 Champions", rank, stats
            )
            assert derived == pytest.approx(display)


class TestReviewedCrowdControl:
    """Diana's crowd-control review, and the slots that still withhold.

    R's beam strikes "after 1 second" — the sourced delay the row now
    authors, and the instant its pull and slow have already landed on.
    W's row is the cached 'Total Magic Damage' of all three spheres and
    E's is the dash count in one part, neither with a cadence to place.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Diana")
        assert diana.MODULE_CC == {"Q": "none", "R": "pull"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "pulls all nearby enemies towards her" in cc_review.slot_text(data, "R")

    def test_moonfalls_beam_lands_on_its_sourced_delay(self):
        data = cc_review.kit("Diana")
        assert "strike upon the area around her after 1 second" in (
            cc_review.slot_text(data, "R")
        )
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["R"]["parts"]
        assert part.time_offset == 1.0
        assert part.cc_kind == "pull"

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Diana") == ["E", "W"]
        coverage = cc_review.fimbulwinter_coverage("Diana")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
