"""Tests for the Samira champion module."""

from src.calculator.champions import samira
from tests import cc_review


class TestReviewedCrowdControl:
    """Samira's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_every_damaging_cast_is_free_of_control_vocabulary(self):
        data = cc_review.kit("Samira")
        assert samira.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "none",
            "R": "none",
        }
        for slot in ("Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # P is absent: it is a state row with no damage, and its knock-up
        # rider fires only on the empowered basic attack against a target
        # already immobilized and either a monster or airborne.
        assert "P" not in samira.MODULE_CC
        p_text = cc_review.slot_text(data, "P")
        assert "basic attack against an immobilized target" in p_text
        assert "if the target is a monster or is airborne" in p_text

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Samira") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Samira")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
