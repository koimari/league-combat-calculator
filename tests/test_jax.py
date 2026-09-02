"""Jax's reviewed crowd control (``MODULE_CC``), whole kit.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import jax, parse_champion_abilities
from tests import cc_review


class TestReviewedCrowdControl:
    """Counter Strike stuns; Leap Strike and the lantern swing do not."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert jax.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "R": "none",
            "E": "stun",
            "P": "none",
        }
        assert jax.parse_abilities.cc_kinds == jax.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Jax")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        assert "and stuns them for 1 second" in cc_review.slot_text(data, "E")

    def test_empower_is_a_reviewed_absence_on_the_swing_it_forces(self):
        """Empower controls nothing, and the row's damage is the engine's
        reattributed swing — the engine builds the zero-damage carrier the
        declaration rides."""
        data = cc_review.kit("Jax")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        entry = parse_champion_abilities(data, 18, 100.0)["W"]
        assert entry["empowers_next_auto"] is True
        (marker,) = entry["parts"]
        assert (marker.amount, marker.cc_kind) == (0.0, "none")

    def test_the_whole_kit_is_reviewed_and_the_fight_certifies(self):
        assert cc_review.unreviewed_ability_slots("Jax") == []
        coverage = cc_review.fimbulwinter_coverage("Jax")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
