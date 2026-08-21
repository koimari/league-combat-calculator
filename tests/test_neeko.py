"""Tests for the Neeko champion module."""

from src.calculator.champions import neeko
from tests import cc_review


class TestReviewedCrowdControl:
    """Neeko's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Neeko")
        assert neeko.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "root",
            "R": "stun",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "roots them for a duration" in cc_review.slot_text(data, "E")
        # R's leap knocks up and deals nothing; the landing burst is the
        # damaging part and it stuns, so the stun is the kind that rides it.
        r_text = cc_review.slot_text(data, "R")
        assert "knocking up nearby enemies for 0.6 seconds" in r_text
        assert "deals magic damage to nearby enemies and stuns them" in r_text
        # P is absent: Inherent Glamour is a disguise that damages nothing.
        assert "P" not in neeko.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Neeko") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Neeko")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
