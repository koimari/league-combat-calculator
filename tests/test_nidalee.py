"""Tests for the Nidalee champion module."""

from src.calculator.champions import nidalee
from tests import cc_review


class TestReviewedCrowdControl:
    """Nidalee's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_the_whole_cached_kit_is_free_of_control_vocabulary(self):
        data = cc_review.kit("Nidalee")
        assert nidalee.MODULE_CC == {"Q": "none", "W": "none", "E": "none"}
        for slot in ("P", "Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # R (Aspect of the Cougar) and P (Prowl) are absent rather than
        # "none": the form swap and the brush movement damage nothing.
        assert "R" not in nidalee.MODULE_CC
        assert "P" not in nidalee.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nidalee") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nidalee")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
