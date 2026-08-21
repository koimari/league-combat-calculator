"""Tests for the Nocturne champion module."""

from src.calculator.champions import nocturne
from tests import cc_review


class TestReviewedCrowdControl:
    """Nocturne's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nocturne")
        assert nocturne.MODULE_CC == {"Q": "none", "E": "fear", "R": "none"}
        # Q's only control word is the dusk trail "slowly disappear[ing]",
        # which is the trail expiring rather than a slow applied to anyone.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == ["slow"]
        assert "dusk trails last 5 seconds and will slowly disappear" in q_text
        assert "the target is feared for a duration" in cc_review.slot_text(data, "E")
        # R nearsights, which is not an immobilize and has no kind in the
        # vocabulary; its damaging recast dash applies nothing.
        r_text = cc_review.slot_text(data, "R")
        assert "nearsighting them for 6 seconds" in r_text
        assert cc_review.control_words(r_text) == []
        # W (spell shield) deals no damage and P is an on-hit rider on the
        # auto stream, so neither could carry an answer of its own.
        assert "W" not in nocturne.MODULE_CC
        assert "P" not in nocturne.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nocturne") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nocturne")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
