"""Tests for the Rumble champion module."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import get_champion_module_contract, rumble
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review, coverage_truth, row_review


class TestReviewedCrowdControl:
    """Rumble's reviewed crowd control, and the one slot that blocks it.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rumble")
        assert rumble.MODULE_CC == {
            "E": "slow",
            "Q": "none",
            "R": "slow",
            "P": "none",
            "W": "none",
        }
        assert rumble.parse_abilities.cc_kinds == rumble.MODULE_CC
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")
        assert "being slowed by 35%" in cc_review.slot_text(data, "R")
        # Flamespitter only scorches: no control word in the whole entry.
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # W (a shield) and P (the heat system) carry no damage row.
        assert rumble.MODULE_CC["W"] == "none"
        assert rumble.MODULE_CC["P"] == "none"

    def test_flamespitter_ticks_on_the_cadence_the_cache_states(self):
        """Fifteen ticks on a 0.25-second beat, both halves sourced."""
        data = cc_review.kit("Rumble")
        q_text = cc_review.slot_text(data, "Q")
        assert (
            "activate his flamethrower for 3 seconds, spewing forth flames "
            "in a frontal cone every 0.25 seconds" in q_text
        )
        assert (
            "scorched for 0.6 seconds, taking magic damage every 0.25 "
            "seconds" in q_text
        )
        (part,) = row_review.parts("Rumble", "Q")
        assert (part.time_offset, part.hit_interval, part.count) == (0.0, 0.25, 15)
        assert part.cc_kind == "none"

    def test_the_timed_fimbulwinter_fight_is_now_exact(self):
        assert cc_review.unreviewed_ability_slots("Rumble") == []
        coverage = cc_review.fimbulwinter_coverage("Rumble")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """Flamespitter prices its own damage, not the monster cap.

    The generated packet read the Danger Zone effect's "Bonus Damage"
    row — the per-LEVEL cap the cache states as "capped at 65 : 336.84
    (based on level) against monsters" — and indexed its 20 level values
    by rank, so rank 5 priced the level-5 cap.  Flamespitter's own rows
    are Minimum / per-Second / per-Tick / Maximum Magic Damage.
    """

    def test_the_packet_still_carries_the_level_indexed_monster_cap(self):
        base = row_review.packet_row("Rumble", "Q", rumble)
        assert len(base) == 20
        assert (base[0], base[4], base[-1]) == (65.0, 107.71, 336.84)
        assert rumble.SLOTS.packet_spec["slots"]["Q"]["ranks"] == "rank"
        assert "against monsters" in cc_review.slot_text(cc_review.kit("Rumble"), "Q")

    def test_flamespitter_prices_the_full_channel(self):
        maximum = row_review.cached_row("Rumble", "Q", "Maximum Magic Damage")
        per_tick = row_review.cached_row("Rumble", "Q", "Magic Damage per Tick")
        assert maximum == pytest.approx(15 * per_tick, rel=1e-3)
        assert row_review.priced("Rumble", "Q") == pytest.approx(maximum)


#: Rumble's own bonus attack speed at level 18 with no items and no
#: Overheat window: the growth the stat sheet already carries, which every
#: derived grant below is measured against.
_UNHEATED_BONUS_ATTACK_SPEED = 31.45


class TestOverheatedOnHit:
    """P (Junkyard Titan): the Overheated rider, derived from the cast plan.

    At 150 Heat the cached entry says Rumble "empowers his basic attacks
    to deal 5 : 44.12 (based on level) (+ 25% AP) (+ 4% of the target's
    maximum health) bonus magic damage on-hit".  How often the mech
    reaches 150 is the fight's own question, and
    ``fight/rotation/cast_resource_lockout.py`` answers it by walking the
    casts the plan actually made.
    """

    def test_the_slot_states_the_cached_heat_rule_and_declares_no_number(self):
        entry = row_review.entry("Rumble", "passive")
        assert entry["cast_resource_lockout"] == {
            "slots": ("Q", "W", "E"),
            "per_cast": 20.0,
            "ceiling": 150.0,
            "seconds": 4.0,
            "decay_per_second": 10.0,
            "decay_delay_seconds": 4.0,
            "ultimate_slot": "R",
            "ultimate_delay_seconds": 2.0,
        }
        # No scenario option speaks for the heat state any more.
        assert not [
            option
            for option in get_champion_module_contract("Rumble").options
            if "overheat" in str(option.get("name", ""))
        ]

    def test_the_rider_is_the_cached_bonus_magic_damage_row(self):
        ability = cc_review.kit("Rumble")["abilities"]["P"][0]
        expected = extract_named(
            ability,
            "Bonus Magic Damage",
            18,
            dict(row_review.STATS),
            dict(row_review.TARGET),
        )
        # 40 (level 18) + 25% of 200 AP + 4% of a 2500 HP target.
        assert expected == pytest.approx(40.0 + 50.0 + 100.0)
        entry = row_review.entry("Rumble", "passive")
        assert entry["on_hit"] == {
            "name": "Junkyard Titan (on-hit)",
            "damage_per_hit": pytest.approx(expected),
            "damage_type": "magic",
        }
        assert entry["total_raw"] == 0.0

    def test_a_fight_that_never_fills_the_bar_prices_neither_half(self):
        """Ten seconds of Rumble is about 120 Heat, so nothing Overheats."""
        payload = calculate_payload(
            {
                "champion": "Rumble",
                "level": 18,
                "items": [],
                "fight_mode": "timed",
                "fight_duration": 10.0,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            }
        )
        assert "on_hit_ability_passive" not in payload["breakdown"]
        assert payload["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            _UNHEATED_BONUS_ATTACK_SPEED
        )

    def test_a_fight_that_fills_the_bar_buys_the_swings_and_the_attack_speed(self):
        """The two halves are one purchase, and the plan decides its size."""
        payload = calculate_payload(
            {
                "champion": "Rumble",
                "level": 18,
                "items": [],
                "fight_mode": "timed",
                "fight_duration": 30.0,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            }
        )
        row = payload["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Junkyard Titan (on-hit)"
        assert row["count"] == 4
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], rel=1e-2
        )
        # One 4-second window in a 30-second fight: 130% at level 18 over
        # the share of the fight it covers.
        assert payload["champion_stats"][
            "bonus_attack_speed"
        ] - _UNHEATED_BONUS_ATTACK_SPEED == pytest.approx(130.0 * 4.0 / 30.0)

    def test_the_lockout_silences_the_casts_it_eats(self):
        """The window sits where it happens, not off the end of the fight."""
        payload = calculate_payload(
            {
                "champion": "Rumble",
                "level": 18,
                "items": ["Malignance", "Cosmic Drive", "Horizon Focus"],
                "fight_mode": "timed",
                "fight_duration": 30.0,
                "include_auto_attacks": True,
            }
        )
        times = sorted(event["time"] for event in payload["cast_timeline"])
        # The bar fills at 7.77 and again at 22.68; each buys four seconds
        # in which nothing casts at all.
        for start in (7.772727, 22.681818):
            assert not [
                time for time in times if start + 1e-3 < time < start + 4.0
            ], f"a cast landed inside the {start:.2f}s lockout"

    def test_an_autos_only_fight_never_overheats(self):
        """No cast, no Heat, and nothing to derive a window from."""
        payload = calculate_payload(
            {
                "champion": "Rumble",
                "level": 18,
                "items": [],
                "fight_mode": "auto_only",
                "fight_duration": 30.0,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            }
        )
        assert "on_hit_ability_passive" not in payload["breakdown"]
        assert payload["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            _UNHEATED_BONUS_ATTACK_SPEED
        )


class TestCoverageMap:
    """Every slot is priced; W is priced outside the damage ledger.

    Scrap Shield books no damage row, but it is not unpriced: the
    ally-support scanner derives the sourced self-shield (25/55/85/115/145
    + 30% AP + 4% maximum health) at target scope "self", so the slot is
    ``modeled`` rather than ``no_damage`` — a priced slot is never labelled
    for the ledger it does not ride.  The Overheated row closes P.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Rumble").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
        # W's shield is not damage, so the damage ledger still reads zero.
        assert coverage_truth.emitted("Rumble") == {
            "P": coverage_truth.PRICED,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ZERO,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_scrap_shield_has_no_cached_damage_row(self):
        rows = {
            level["attribute"]
            for ability in cc_review.kit("Rumble")["abilities"]["W"]
            for effect in ability["effects"]
            for level in effect["leveling"] or []
        }
        assert not any("Damage" in name for name in rows)
        assert "grant himself a shield" in cc_review.slot_text(
            cc_review.kit("Rumble"), "W"
        )
