"""Tests for the Nautilus champion module."""

from src.calculator.champions import nautilus
from tests import cc_review


class TestReviewedCrowdControl:
    """Nautilus' reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nautilus")
        assert nautilus.MODULE_CC == {
            "Q": "immobilize",
            "W": "none",
            "E": "slow",
            "R": "immobilize",
        }
        # Q and R each apply two immobilize kinds in one cast, which is
        # what the un-narrowed "immobilize" states.
        q_text = cc_review.slot_text(data, "Q")
        assert "stuns them for 1 second" in q_text
        assert "drags them toward nautilus" in q_text
        r_text = cc_review.slot_text(data, "R")
        assert "knocked up for 1 second, and stunned for a duration" in r_text
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slows them by an amount that decays" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nautilus") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nautilus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
