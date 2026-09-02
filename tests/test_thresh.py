"""Thresh's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import thresh
from tests import cc_review


class TestReviewedCrowdControl:
    """Thresh's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Thresh")
        assert thresh.MODULE_CC == {
            "Q": "immobilize",
            "E": "knockback",
            "R": "slow",
            "P": "none",
            "W": "none",
        }
        # Death Sentence stuns and renders airborne at once, so the
        # reviewed kind is the un-narrowed one.
        assert "stun and reveal them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        assert "render them airborne for 0.4 seconds" in cc_review.slot_text(data, "Q")
        # Flay knocks and then slows; the knock-back is the immobilize.
        assert "knocked 200 units in the target direction" in (
            cc_review.slot_text(data, "E")
        )
        assert "slowing them by 99% for 2 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Thresh") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Thresh")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
