"""Kled's reviewed crowd control (``MODULE_CC``), and the slots that withhold.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import kled
from tests import cc_review


class TestReviewedCrowdControl:
    """Chaaaaaaaarge!!! knocks back; the two Total rows cannot answer."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert kled.MODULE_CC == {"W": "none", "R": "knockback"}
        assert kled.parse_abilities.cc_kinds == kled.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Kled")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "knock them back 150 units" in cc_review.slot_text(data, "R")

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        """Bear Trap's row is the trap hit plus the tether's pull hit, and
        only the second controls; Jousting's is the first dash plus the
        recast dash, with no sourced cadence between them."""
        data = cc_review.kit("Kled")
        q_text = cc_review.slot_text(data, "Q")
        assert "kled pulls the target 150 units toward him" in q_text
        assert "slows them for 2.5 seconds" in q_text
        assert cc_review.unreviewed_ability_slots("Kled") == ["E", "Q"]
        coverage = cc_review.fimbulwinter_coverage("Kled")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
