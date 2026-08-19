"""Singed's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import singed
from tests import cc_review


class TestReviewedCrowdControl:
    """Singed's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Singed")
        assert singed.MODULE_CC == {"Q": "none", "E": "airborne"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Fling throws the target; the cached text names the throw only as
        # a displacement, so the reviewed kind is the un-narrowed airborne
        # one.  Its root is conditional on landing in W's field.
        assert "flings the target enemy 550 units over himself" in (
            cc_review.slot_text(data, "E")
        )
        assert "after the displacement" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Singed") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Singed")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
