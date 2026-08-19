"""Tests for the Rek'Sai champion module."""

from src.calculator.champions import reksai
from tests import cc_review


class TestReviewedCrowdControl:
    """Rek'Sai's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rek'Sai")
        assert reksai.MODULE_CC == {
            "Q": "none",
            "W": "knockup",
            "E": "none",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "knock them up for 1 second" in cc_review.slot_text(data, "W")
        # E's only control word is about Rek'Sai being unable to enter a
        # tunnel while immobilized, not about control she applies.
        e_text = cc_review.slot_text(data, "E")
        assert "bites the target enemy, dealing physical damage" in e_text
        assert "cannot enter a tunnel while immobilized" in e_text
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # P is Fury generation and healing, with no damage row.
        assert "P" not in reksai.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rek'Sai") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rek'Sai")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
