"""Tests for the Rumble champion module."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import get_champion_module_contract, rumble
from src.calculator.champions.slotlib import extract_named
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
        assert rumble.MODULE_CC == {"E": "slow", "Q": "none", "R": "slow"}
        assert rumble.parse_abilities.cc_kinds == rumble.MODULE_CC
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")
        assert "being slowed by 35%" in cc_review.slot_text(data, "R")
        # Flamespitter only scorches: no control word in the whole entry.
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # W (a shield) and P (the heat system) carry no damage row.
        assert "W" not in rumble.MODULE_CC
        assert "P" not in rumble.MODULE_CC

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


class TestOverheatedOnHit:
    """P (Junkyard Titan): the Overheated rider, and what it deliberately omits.

    At 150 Heat the cached entry says Rumble "empowers his basic attacks
    to deal 5 : 44.12 (based on level) (+ 25% AP) (+ 4% of the target's
    maximum health) bonus magic damage on-hit" — a complete sourced row.
    It rides the ``p_overheated`` option, off by default, so a default
    request is the number it always was.
    """

    def test_the_default_request_prices_no_rider(self):
        entry = row_review.entry("Rumble", "passive")
        assert entry["total_raw"] == 0.0
        assert "on_hit" not in entry
        assert coverage_truth.emitted("Rumble")["P"] == coverage_truth.ZERO

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
        entry = row_review.entry("Rumble", "passive", p_overheated=True)
        assert entry["on_hit"] == {
            "name": "Junkyard Titan (Overheated)",
            "damage_per_hit": pytest.approx(expected),
            "damage_type": "magic",
        }
        assert entry["total_raw"] == 0.0

    def test_the_rider_reaches_the_fight_on_the_basic_attack_stream(self):
        probe = {
            "champion": "Rumble",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
        off = calculate_payload({**probe, "champion_options": {}})
        on = calculate_payload({**probe, "champion_options": {"p_overheated": True}})

        assert "on_hit_ability_passive" not in off["breakdown"]
        row = on["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Junkyard Titan (Overheated)"
        assert row["count"] == off["breakdown"]["auto_attacks"]["count"]
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], rel=1e-2
        )
        # Only the auto stream moves: no ability row is repriced.
        assert on["ability_damage"] == pytest.approx(off["ability_damage"])
        assert on["auto_attack_damage"] > off["auto_attack_damage"]

    def test_the_attack_speed_half_of_overheating_is_left_out(self):
        """Granting it without the ability lockout would be a free upgrade."""
        assert "bonus attack speed" in cc_review.slot_text(cc_review.kit("Rumble"), "P")
        entry = row_review.entry("Rumble", "passive", p_overheated=True)
        assert "stat_buff" not in entry
        assert "ability lockout are both unmodeled" in entry["detail"]


class TestCoverageMap:
    """P now prices a row; W never will.

    Scrap Shield is a shield and a movement-speed burst — ``no_damage``,
    not ``out_of_scope`` — and the Overheated rider closes P.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Rumble").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Rumble", p_overheated=True) == {
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
