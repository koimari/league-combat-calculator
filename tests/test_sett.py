"""Sett's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import sett
from tests import cc_review


class TestReviewedCrowdControl:
    """Three reviewed slots, and the aggregated Q row that keeps Sett coarse."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sett")
        assert sett.MODULE_CC == {"W": "none", "E": "pull", "R": "suppression"}
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "pulls in enemies at his front and back" in cc_review.slot_text(
            data, "E"
        )
        assert "suppresses and reveals the target enemy champion" in (
            cc_review.slot_text(data, "R")
        )

    def test_q_is_undeclared_because_its_row_is_two_attacks_summed(self):
        """Knuckle Down "empowers his next two basic attacks", and the module
        prices both from one cached total, so no part of it is a hit the
        ledger can time — a declaration there would review nothing."""
        q_text = cc_review.slot_text(cc_review.kit("Sett"), "Q")
        assert (
            "sett empowers his next two basic attacks within 5 seconds to "
            "gain 50 bonus range and deal bonus physical damage" in q_text
        )
        # A 5-second window and an attack-timer reset are the only timing
        # the entry gives: neither attack has a stated instant.
        assert "knuckle down resets sett's basic attack timer" in q_text
        assert "Q" not in sett.MODULE_CC

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Sett") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Sett")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
