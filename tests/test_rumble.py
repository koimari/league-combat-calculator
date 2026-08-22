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
    Overheat is a 4-second heat-state window the fight engine does not
    simulate, so ``overheat_autos`` is the explicit count of empowered
    swings, 0 by default — a default request is the number it always was.
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
        entry = row_review.entry(
            "Rumble", "passive", overheat_autos=3, overheat_windows=1
        )
        assert entry["on_hit"] == {
            "name": "Junkyard Titan (on-hit)",
            "damage_per_hit": pytest.approx(expected),
            "damage_type": "magic",
            "max_procs": 3,
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
        # The window is held constant across both arms so the comparison
        # isolates the rider: moving it too would move the lockout as well.
        off = calculate_payload({**probe, "champion_options": {"overheat_windows": 1}})
        on = calculate_payload(
            {
                **probe,
                "champion_options": {"overheat_autos": 3, "overheat_windows": 1},
            }
        )

        assert "on_hit_ability_passive" not in off["breakdown"]
        row = on["breakdown"]["on_hit_ability_passive"]
        assert row["name"] == "Junkyard Titan (on-hit)"
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], rel=1e-2
        )
        # Only the auto stream moves: no ability row is repriced.
        assert on["ability_damage"] == pytest.approx(off["ability_damage"])
        assert on["auto_attack_damage"] > off["auto_attack_damage"]

    def test_the_empowered_swing_count_is_bounded_by_the_option(self):
        """Overheat is a 4-second window, so the count cannot be inferred.

        Batch K's fail-closed reading (``overheat_autos``, 0 by default)
        is carried on the on-hit channel rather than as a ``parts``-priced
        passive row: ``passive`` is not an orderable cast
        (``pipeline.validate_cast_order_for_kit`` refuses it), so a
        parts-priced passive row never reaches the fight at all.
        ``max_procs`` is what stops the rider from charging every swing of
        a long fight as Overheated.
        """
        probe = {
            "champion": "Rumble",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
        one = calculate_payload(
            {**probe, "champion_options": {"overheat_autos": 1, "overheat_windows": 1}}
        )
        three = calculate_payload(
            {**probe, "champion_options": {"overheat_autos": 3, "overheat_windows": 1}}
        )
        autos = one["breakdown"]["auto_attacks"]["count"]
        assert autos > 3, "the probe must outlast the empowered swings"
        assert one["breakdown"]["on_hit_ability_passive"]["count"] == 1
        assert three["breakdown"]["on_hit_ability_passive"]["count"] == 3

    def test_the_attack_speed_half_needs_a_declared_heat_window(self):
        """Granting it without the ability lockout would be a free upgrade.

        The heat axis is what makes the pair declarable at all, so the
        default request — which declares no window — still emits neither.
        """
        assert "bonus attack speed" in cc_review.slot_text(cc_review.kit("Rumble"), "P")
        entry = row_review.entry("Rumble", "passive")
        assert "stat_buff" not in entry
        assert "self_cast_lockout_seconds" not in entry
        assert "no Overheat window is declared" in entry["detail"]

    def test_a_declared_heat_window_buys_the_attack_speed_and_its_cost(self):
        """The two halves are one purchase: the fight pays for the steroid.

        A timed probe through the real pipeline — the AS goes up, and the
        casts the lockout costs come off the same fight.
        """
        probe = {
            "champion": "Rumble",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "fight_duration": 10.0,
            "include_auto_attacks": True,
        }
        cold = calculate_payload({**probe, "champion_options": {}})
        hot = calculate_payload(
            {**probe, "champion_options": {"overheat_windows": 1}},
        )
        cold_as = cold["champion_stats"]["bonus_attack_speed"]
        hot_as = hot["champion_stats"]["bonus_attack_speed"]
        # 130% at level 18, over the 4s of a 10s fight the window covers.
        assert hot_as - cold_as == pytest.approx(130.0 * 0.4)
        assert (
            hot["champion_stats"]["attack_speed"]
            > cold["champion_stats"]["attack_speed"]
        )
        assert hot["auto_attack_damage"] > cold["auto_attack_damage"]
        # ...and the cost: four seconds off the shared cast schedule.
        assert len(hot["cast_timeline"]) < len(cold["cast_timeline"])
        assert hot["ability_damage"] < cold["ability_damage"]

    def test_an_autos_only_fight_never_overheats(self):
        """No cast, no Heat — the axis cannot conjure a window."""
        entry = row_review.entry(
            "Rumble", "passive", overheat_windows=2, auto_attacks_only=True
        )
        assert "stat_buff" not in entry
        assert "self_cast_lockout_seconds" not in entry


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
        assert coverage_truth.emitted(
            "Rumble", overheat_autos=1, overheat_windows=1
        ) == {
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
