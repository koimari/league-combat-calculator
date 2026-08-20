"""Pantheon's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import pantheon
from tests import cc_review


class TestReviewedCrowdControl:
    """Shield Vault stuns, Grand Starfall slows, the rest control nothing."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert pantheon.MODULE_CC == {
            "W": "stun",
            "Q": "none",
            "E": "none",
            "R": "slow",
        }
        assert pantheon.parse_abilities.cc_kinds == pantheon.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Pantheon")
        assert "stuns them for 1 second" in cc_review.slot_text(data, "W")
        assert "slows them by 50% for 2 seconds" in cc_review.slot_text(data, "R")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_comet_spears_only_slow_is_on_pantheon_himself(self):
        text = cc_review.slot_text(cc_review.kit("Pantheon"), "Q")
        assert "pantheon charges while being slowed by 10%" in text
        assert pantheon.MODULE_CC["Q"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Pantheon") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Pantheon")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
