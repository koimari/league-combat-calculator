"""Tests for the Senna champion module."""

from src.calculator.champions import senna
from tests import cc_review


class TestReviewedCrowdControl:
    """Senna's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Senna")
        assert senna.MODULE_CC == {"Q": "slow", "W": "root", "R": "none"}
        assert "deals physical damage to enemies hit and slows them" in (
            cc_review.slot_text(data, "Q")
        )
        assert "rooting them and surrounding enemies" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # E (camouflage) deals no damage and P's mark consume rides the
        # auto stream, so neither carries an ability event of its own.
        assert "E" not in senna.MODULE_CC
        assert "P" not in senna.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Senna") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Senna")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
