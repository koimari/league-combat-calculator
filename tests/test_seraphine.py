"""Seraphine's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
``MODULE_CC`` is where this kit answers, read from the cached text, and the
probe below is the reason it exists.
"""

from src.calculator.champions import seraphine
from tests import cc_review


class TestReviewedCrowdControl:
    """Seraphine's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Seraphine")
        assert seraphine.MODULE_CC == {"Q": "none", "E": "slow", "R": "charm"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slows them by 99%" in cc_review.slot_text(data, "E")
        assert "charms them" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Seraphine") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Seraphine")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
