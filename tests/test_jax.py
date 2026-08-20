"""Jax's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import jax
from tests import cc_review


class TestReviewedCrowdControl:
    """Counter Strike stuns; Leap Strike and the lantern swing do not."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert jax.MODULE_CC == {"Q": "none", "R": "none", "E": "stun"}
        assert jax.parse_abilities.cc_kinds == jax.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Jax")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        assert "and stuns them for 1 second" in cc_review.slot_text(data, "E")

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Empower controls nothing, but the row's damage is the engine's
        reattributed empowered swing with no damage part of its own, so a
        declaration would have nothing to stamp."""
        data = cc_review.kit("Jax")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "W" not in jax.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Jax") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Jax")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
