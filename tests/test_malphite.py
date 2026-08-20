"""Malphite's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.ability_spec import IMMOBILIZING_CC_KINDS, NON_IMMOBILIZING_CC_KINDS
from src.calculator.champions import malphite
from tests import cc_review


class TestReviewedCrowdControl:
    """Ground Slam's cripple is the kind the vocabulary added for it."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert malphite.MODULE_CC == {"Q": "slow", "E": "cripple", "R": "knockup"}
        assert malphite.parse_abilities.cc_kinds == malphite.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Malphite")
        assert "slows them for 3 seconds upon impact" in cc_review.slot_text(data, "Q")
        assert "crippling them for 3 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_a_cripple_is_neither_an_immobilize_nor_a_movement_slow(self):
        assert "cripple" in NON_IMMOBILIZING_CC_KINDS
        assert "cripple" not in IMMOBILIZING_CC_KINDS

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Thunderclap controls nothing, but its row is two parts - the
        empowered attack's on-hit bonus and the cone every attack triggers
        "for the next 5 seconds" - and those are different hits."""
        data = cc_review.kit("Malphite")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "W" not in malphite.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Malphite") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Malphite")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
