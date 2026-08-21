"""Teemo's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.ability_spec import (
    CC_KIND_VOCABULARY,
    IMMOBILIZING_CC_KINDS,
)
from src.calculator.champions import teemo
from tests import cc_review


class TestReviewedCrowdControl:
    """Teemo's whole kit is reviewed once ``blind`` exists as a kind."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Teemo")
        assert teemo.MODULE_CC == {"Q": "blind", "E": "none", "R": "slow"}
        assert "blinds them for a duration" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "slowing them for 4 seconds" in cc_review.slot_text(data, "R")

    def test_a_blind_is_crowd_control_the_vocabulary_now_names(self):
        """Blinding Dart applies real control that is neither an immobilize
        nor a movement slow, so "none" would be false and "slow" wrong."""
        assert "blind" in CC_KIND_VOCABULARY
        assert "blind" not in IMMOBILIZING_CC_KINDS

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Teemo") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Teemo")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
