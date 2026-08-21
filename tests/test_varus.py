"""Varus's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import varus
from tests import cc_review


class TestReviewedCrowdControl:
    """Varus's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Varus")
        assert varus.MODULE_CC == {"Q": "none", "E": "slow", "R": "root"}
        # Q's only "slow" is the one Varus takes himself while charging.
        assert "charges while being slowed by 20%" in cc_review.slot_text(data, "Q")
        assert "slowing enemies within" in cc_review.slot_text(data, "E")
        assert "rooting them for 2 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Varus") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Varus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
