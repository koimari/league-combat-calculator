"""Shyvana's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import shyvana
from tests import cc_review


class TestReviewedCrowdControl:
    """Shyvana's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Shyvana")
        assert shyvana.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "slow",
            "R": "fear",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slowing them by 30% for 2 seconds" in cc_review.slot_text(data, "E")
        # R also slows by 99%; the fear is the immobilizing half, which is
        # the answer a control-armed reader needs.
        assert "fears them for 0.75 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Shyvana") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Shyvana")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
