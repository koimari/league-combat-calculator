"""Teemo's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.ability_spec import CC_KIND_VOCABULARY
from src.calculator.champions import teemo
from tests import cc_review


class TestReviewedCrowdControl:
    """E and R reviewed; Blinding Dart has no kind the vocabulary can name."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Teemo")
        assert teemo.MODULE_CC == {"E": "none", "R": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "slowing them for 4 seconds" in cc_review.slot_text(data, "R")

    def test_q_is_undeclared_because_a_blind_has_no_reviewed_kind(self):
        """Blinding Dart applies real crowd control, and the vocabulary has
        no term for it — its non-immobilizing kinds are slow, cripple and
        silence — so "none" would be false and nothing true can be said."""
        data = cc_review.kit("Teemo")
        assert "blinds them for a duration" in cc_review.slot_text(data, "Q")
        assert "blind" not in CC_KIND_VOCABULARY
        assert "Q" not in teemo.MODULE_CC

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Teemo") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Teemo")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
