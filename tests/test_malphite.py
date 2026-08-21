"""Malphite's reviewed crowd control (``MODULE_CC``).

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
        assert malphite.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "cripple",
            "R": "knockup",
        }
        assert malphite.parse_abilities.cc_kinds == malphite.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Malphite")
        assert "slows them for 3 seconds upon impact" in cc_review.slot_text(data, "Q")
        assert "crippling them for 3 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_a_cripple_is_neither_an_immobilize_nor_a_movement_slow(self):
        assert "cripple" in NON_IMMOBILIZING_CC_KINDS
        assert "cripple" not in IMMOBILIZING_CC_KINDS

    def test_thunderclaps_two_halves_are_one_landing_and_say_so(self):
        """W is one empowered swing priced as its on-hit bonus plus its
        cone, so the shared-instant certification carries its review."""
        data = cc_review.kit("Malphite")
        text = cc_review.slot_text(data, "W")
        assert (
            "empowers his next basic attack within 6 seconds to have an "
            "uncancellable windup, gain 50 bonus range, and deal additional "
            "physical damage on-hit" in text
        )
        assert (
            "basic attacks on-hit for the next 5 seconds are empowered to "
            "trigger a cone in the direction of the target that deals "
            "physical damage to enemies hit" in text
        )
        assert cc_review.control_words(text) == []

    def test_the_whole_kit_is_reviewed_and_the_fight_certifies(self):
        assert cc_review.unreviewed_ability_slots("Malphite") == []
        coverage = cc_review.fimbulwinter_coverage("Malphite")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
