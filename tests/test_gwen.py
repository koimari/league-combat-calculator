"""Gwen's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import gwen
from tests import cc_review


class TestReviewedCrowdControl:
    """Skip 'n Slash controls nothing, Needlework slows, Snip Snip! withholds."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert gwen.MODULE_CC == {"E": "none", "R": "slow"}
        assert gwen.parse_abilities.cc_kinds == gwen.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Gwen")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "slows them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Snip Snip! is an aggregate of "at least twice" snips over the
        cast time with no sourced per-snip cadence, so nothing it declares
        would reach the ledger."""
        data = cc_review.kit("Gwen")
        assert "gwen snips at least twice with her scissors" in (
            cc_review.slot_text(data, "Q")
        )
        assert "Q" not in gwen.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Gwen") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Gwen")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
