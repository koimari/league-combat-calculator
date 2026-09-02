"""Tests for the Riven champion module."""

import pytest

from src.calculator.champions import riven
from tests import cc_review, rider_probe, row_review


class TestReviewedCrowdControl:
    """Riven's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Riven")
        assert riven.MODULE_CC == {
            "Q": "none",
            "W": "stun",
            "R": "none",
            "P": "none",
            "E": "none",
        }
        # Q prices one slash of Broken Wings; only the third cast adds a
        # knock back, and this module does not price that specific one.
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing physical damage to enemies struck within an area" in q_text
        assert "knocking back enemies hit 75 units" in q_text
        assert riven.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            45.0,
            75.0,
            105.0,
            135.0,
            165.0,
        ]
        assert "stunning them for 0.75 seconds" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # E and P carry no control word at all.  R_buff is a result key
        # rather than a champion slot, so MODULE_CC has no entry for it.
        for slot in ("E", "P"):
            assert cc_review.any_control_hits(data, slot) == [], slot
        assert "R_buff" not in riven.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Riven") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Riven")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestRunicBladeCrits:
    """P declares the crit clause its own cached sentence states."""

    def test_the_on_hit_row_carries_the_sourced_effectiveness(self):
        text = cc_review.slot_text(cc_review.kit("Riven"), "P")
        assert "the bonus damage is affected by critical strike modifiers" in text
        on_hit = row_review.entry("Riven", "passive")["on_hit"]
        assert (
            on_hit["crit_effectiveness"] == riven._RUNIC_BLADE_CRIT_EFFECTIVENESS == 1.0
        )

    def test_the_rider_crits_in_a_real_fight(self):
        """Cloak of Agility: 15% crit chance, no other stat moved.

        Full effectiveness at the 200% base multiplier is
        1 - 0.15 + 0.15 x 2.0 == 1.15 on the rider's own row.
        """
        plain = rider_probe.fight("Riven", deterministic=True)
        crit = rider_probe.fight(
            "Riven", items=["Cloak of Agility"], deterministic=True
        )
        assert crit["champion_stats"]["critical_strike_chance"] == pytest.approx(15.0)
        assert crit["champion_stats"]["attack_damage"] == pytest.approx(
            plain["champion_stats"]["attack_damage"]
        )
        assert crit["breakdown"][rider_probe.RIDER_ROW][
            "total_damage"
        ] == pytest.approx(
            1.15 * plain["breakdown"][rider_probe.RIDER_ROW]["total_damage"], abs=0.1
        )
