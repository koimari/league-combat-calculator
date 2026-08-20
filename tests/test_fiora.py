"""Fiora's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import fiora
from tests import cc_review


class TestReviewedCrowdControl:
    """Lunge controls nothing, Riposte's shock slows, Bladework withholds."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert fiora.MODULE_CC == {"Q": "none", "W": "slow"}
        assert fiora.parse_abilities.cc_kinds == fiora.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Fiora")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert (
            "the enemy champion struck is also slowed and crippled by 25% "
            "for 2 seconds" in cc_review.slot_text(data, "W")
        )

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        """Bladework's first attack does slow, but the row's damage is the
        engine's reattributed empowered swings with no damage part of its
        own, so the declaration would have nothing to stamp."""
        data = cc_review.kit("Fiora")
        assert "the first attack slows the target by 30% for 1 second" in (
            cc_review.slot_text(data, "E")
        )
        assert "E" not in fiora.MODULE_CC
        assert cc_review.unreviewed_ability_slots("Fiora") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Fiora")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
