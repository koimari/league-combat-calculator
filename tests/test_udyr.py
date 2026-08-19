"""Udyr's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import udyr
from tests import cc_review


class TestReviewedCrowdControl:
    """Wingborne Storm's blizzard is the kit's only cast-damage row."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Udyr")
        assert udyr.MODULE_CC == {"R": "slow"}
        assert "slows them while they remain within" in cc_review.slot_text(data, "R")
        # Blazing Stampede is where the kit's stun lives, and it deals no
        # damage of its own, so no part can carry that answer.
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["stun"]
        assert udyr.MODULE_COVERAGE["E"] == "out_of_scope"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Udyr") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Udyr")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
