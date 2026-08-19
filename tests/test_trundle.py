"""Trundle's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import trundle
from tests import cc_review


class TestReviewedCrowdControl:
    """Trundle's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Trundle")
        assert trundle.MODULE_CC == {"Q": "slow", "R": "none"}
        assert "slow the target by 75% for 0.1 seconds" in cc_review.slot_text(
            data, "Q"
        )
        # Subjugate drains resistances, health and size — real debuffs, but
        # none of them crowd control.
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Trundle") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Trundle")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
