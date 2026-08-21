"""Tristana's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import tristana
from tests import cc_review


class TestReviewedCrowdControl:
    """Tristana's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Tristana")
        assert tristana.MODULE_CC == {
            "W": "slow",
            "E": "none",
            "R": "immobilize",
        }
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "W")
        # E's only control word is a reference to R's knock back, not to
        # anything the charge itself applies.
        assert "the charge then detonates" in cc_review.slot_text(data, "E")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["knock"]
        # R knocks back and stuns at once, so the reviewed kind is the
        # un-narrowed one.
        assert "knocked back and stunned for a duration" in (
            cc_review.slot_text(data, "R")
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Tristana") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Tristana")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
