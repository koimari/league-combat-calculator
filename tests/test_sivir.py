"""Sivir's crowd-control review: two control-free slots neither can carry.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.  Sivir's
two damaging slots apply no control at all, but neither row is a hit the
ledger can time, and a reviewed "none" that never reaches an event proves
nothing about the fight it was supposed to certify — so the module
declares nothing and this kit stays coarse.
"""

from src.calculator.champions import sivir
from tests import cc_review


class TestReviewedCrowdControl:
    """Why Sivir withholds: timing, not an unread control."""

    def test_the_damaging_slots_are_control_free_in_the_cached_text(self):
        data = cc_review.kit("Sivir")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert sivir.MODULE_CC == {"P": "none", "E": "none", "R": "none"}
        assert sivir.parse_abilities.cc_kinds == sivir.MODULE_CC

    def test_neither_row_is_a_hit_the_ledger_can_time(self):
        """Boomerang Blade is two passes the module prices at the cast
        boundary ("the exact return cadence is not cached"), and Ricochet's
        packet is one stand-in bounce for a four-second empowered attack
        stream — so neither is one authored hit."""
        data = cc_review.kit("Sivir")
        # The return is timed to an event, not to an instant: the cache
        # says when the blade turns around, never when either pass lands.
        assert (
            "upon reaching maximum range, the crossblade returns to her, "
            "resetting the damage modifier and dealing the same damage to "
            "enemies on its way back" in cc_review.slot_text(data, "Q")
        )
        # Ricochet's bounces ride basic attacks over a 4-second buff.
        assert (
            "sivir empowers her crossblade for the next 4 seconds, gaining "
            "bonus attack speed and causing her basic attacks to bounce to "
            "additional surrounding enemies" in cc_review.slot_text(data, "W")
        )

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Sivir") == ["Q", "W"]
        coverage = cc_review.fimbulwinter_coverage("Sivir")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
