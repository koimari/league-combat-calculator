"""Urgot's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import urgot
from tests import cc_review


class TestReviewedCrowdControl:
    """Urgot's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Urgot")
        assert urgot.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "immobilize",
            "R": "slow",
            "P": "none",
        }
        assert "slow them for 1.25 seconds" in cc_review.slot_text(data, "Q")
        # W's only control word is Urgot's own slow resist, not a debuff.
        assert "gains 40% slow resist" in cc_review.slot_text(data, "W")
        # E knocks aside and stuns at once, so the reviewed kind is the
        # un-narrowed one.
        assert "knocking them aside and stunning them for 1 second" in (
            cc_review.slot_text(data, "E")
        )
        # R prices the chem-drill impale; the Mercy recast's suppression
        # and post-execution fear ride the execution branch it does not.
        assert "slowed by 0% : 75%" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Urgot") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Urgot")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
