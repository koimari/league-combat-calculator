"""Tests for the Renekton champion module."""

from src.calculator.champions import renekton
from tests import cc_review


class TestReviewedCrowdControl:
    """Renekton's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Renekton")
        assert renekton.MODULE_CC == {
            "Q": "none",
            "W": "stun",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        assert "stunning them for 0.75 seconds" in cc_review.slot_text(data, "W")
        # P is Fury bookkeeping with no damage row.
        assert renekton.MODULE_CC["P"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Renekton") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Renekton")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
