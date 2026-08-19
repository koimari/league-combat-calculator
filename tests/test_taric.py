"""Taric's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import taric
from tests import cc_review


class TestReviewedCrowdControl:
    """Dazzle is the whole of Taric's reviewable control."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Taric")
        assert taric.MODULE_CC == {"E": "stun"}
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "E")
        # Q heals, W shields and R grants invulnerability: no other slot
        # damages, so no other slot has a control answer to carry.
        for slot in ("P", "Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Taric") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Taric")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
