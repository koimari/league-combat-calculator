"""Naafiri's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import naafiri
from tests import cc_review


class TestReviewedCrowdControl:
    """Only Hounds' Pursuit controls, and it slows."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert naafiri.MODULE_CC == {"Q": "none", "E": "none", "R": "slow"}
        assert naafiri.parse_abilities.cc_kinds == naafiri.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Naafiri")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "slows the target by 99% for 0.25 seconds" in (
            cc_review.slot_text(data, "R")
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Naafiri") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Naafiri")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
