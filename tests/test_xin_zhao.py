"""Reviewed crowd control for Xin Zhao (MODULE_CC) — and the slot that
still withholds.

Wind Becomes Lightning and Audacious Charge slow; Crescent Guard displaces
only unChallenged targets, which the duel target never is.  Q prices one
of three empowered attacks, so it carries no slot-wide answer and this kit
stays coarse.
"""

from src.calculator.champions import xin_zhao
from tests import cc_review


class TestReviewedCrowdControl:
    """Xin Zhao's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Xin Zhao")
        assert xin_zhao.MODULE_CC == {"W": "slow", "E": "slow", "R": "none"}
        assert xin_zhao.parse_abilities.cc_kinds == xin_zhao.MODULE_CC
        assert "slowing all targets hit by 30%" in cc_review.slot_text(data, "E")
        # W's slow is the thrust's; the packet prices the per-slash row,
        # but the cast still slows the target it damages.
        assert "slowing them by 50%" in cc_review.slot_text(data, "W")
        assert xin_zhao.PACKET_SPEC["slots"]["W"]["base"] == [
            7.5,
            10.0,
            12.5,
            15.0,
            17.5,
        ]

    def test_crescent_guard_never_displaces_a_challenged_duel_target(self):
        data = cc_review.kit("Xin Zhao")
        r_text = cc_review.slot_text(data, "R")
        assert "knocking back all targets hit that are not challenged" in r_text
        assert "basic attacks and audacious charge apply the challenged mark" in r_text

    def test_three_talon_strike_has_no_slot_wide_answer(self):
        """Only the third of Q's three empowered attacks knocks up."""
        data = cc_review.kit("Xin Zhao")
        assert "Q" not in xin_zhao.MODULE_CC
        assert "the third attack knocks up the target" in cc_review.slot_text(data, "Q")
        # The priced row is one empowered attack, not the three-attack total.
        assert xin_zhao.PACKET_SPEC["slots"]["Q"]["base"] == [
            15.0,
            30.0,
            45.0,
            60.0,
            75.0,
        ]

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Xin Zhao") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Xin Zhao")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
