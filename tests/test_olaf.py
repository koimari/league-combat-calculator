"""Tests for the Olaf champion module."""

from src.calculator.champions import olaf
from tests import cc_review


class TestReviewedCrowdControl:
    """Olaf's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Olaf")
        assert olaf.MODULE_CC == {"Q": "slow", "E": "none"}
        assert "slows them for 1 : 3" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # W, R and P are absent rather than "none": the shield, the
        # self-cleanse and the innate attack speed damage nothing.
        for slot in ("W", "R", "P"):
            assert slot not in olaf.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Olaf") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Olaf")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
