"""Tests for the Nilah champion module."""

from src.calculator.champions import nilah
from tests import cc_review


class TestReviewedCrowdControl:
    """Nilah's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nilah")
        assert nilah.MODULE_CC == {"Q": "none", "E": "none", "R": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # The module prices R's whirl ticks, and "each hit also slows
        # targets by 10%"; the pull rides the unpriced final burst.
        r_text = cc_review.slot_text(data, "R")
        assert "each hit also slows targets by 10%" in r_text
        assert "pulls them 250 units towards her" in r_text
        # P and W are absent: the heal/shield innate and the mist damage
        # nothing, so no event of theirs could carry an answer.
        assert "P" not in nilah.MODULE_CC
        assert "W" not in nilah.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nilah") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nilah")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
