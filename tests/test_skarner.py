"""Skarner's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import skarner
from tests import cc_review


class TestReviewedCrowdControl:
    """Skarner's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Skarner")
        assert skarner.MODULE_CC == {
            "P": "none",
            "Q": "slow",
            "W": "slow",
            "E": "stun",
            "R": "suppression",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []
        assert "slowing afflicted enemies by 40%" in cc_review.slot_text(data, "Q")
        assert "slow them by 20% for 1 second" in cc_review.slot_text(data, "W")
        # E's suppression is the grab that precedes the damage; the stun is
        # what lands with it, on terrain collision.
        assert "stunning them for 1.1 seconds" in cc_review.slot_text(data, "E")
        assert "suppress them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Skarner") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Skarner")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
