"""Tests for the Quinn champion module."""

from src.calculator.champions import quinn
from tests import cc_review


class TestReviewedCrowdControl:
    """Quinn's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Quinn")
        assert quinn.MODULE_CC == {
            "Q": "none",
            "E": "knockback",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        # Q's nearsight is not an immobilize and has no kind in the
        # vocabulary; the disarm branch never reaches a champion.
        q_text = cc_review.slot_text(data, "Q")
        assert "the primary target is nearsighted for 1.75 seconds" in q_text
        assert cc_review.control_words(q_text) == []
        assert "knocking them back a very short distance" in cc_review.slot_text(
            data, "E"
        )
        # R's own "immobilized" wording is about Quinn losing the ability.
        r_text = cc_review.slot_text(data, "R")
        assert "becoming immobilized, grounded, or silenced ends" in r_text
        assert "dealing physical damage to nearby enemies and marking" in r_text
        # W (vision) deals no damage, P rides the auto stream on-hit.
        assert quinn.MODULE_CC["W"] == "none"
        assert quinn.MODULE_CC["P"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Quinn") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Quinn")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
