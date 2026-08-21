"""Tests for the Pyke champion module."""

from src.calculator.champions import pyke
from tests import cc_review


class TestReviewedCrowdControl:
    """Pyke's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Pyke")
        assert pyke.MODULE_CC == {"Q": "pull", "E": "stun", "R": "none"}
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing physical damage to the first enemy hit and pulling" in q_text
        assert "then slowing them by 90% for 1 second" in q_text
        assert "the phantom homes back to pyke to stun enemies" in cc_review.slot_text(
            data, "E"
        )
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # W (camouflage) and P (grey health) damage nothing, so no event of
        # theirs could carry an answer.
        assert "W" not in pyke.MODULE_CC
        assert "P" not in pyke.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Pyke") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Pyke")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
