"""Fiora's reviewed crowd control (``MODULE_CC``), whole kit.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import fiora, parse_champion_abilities
from tests import cc_review


class TestReviewedCrowdControl:
    """Lunge controls nothing, Riposte's shock slows, Bladework withholds."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert fiora.MODULE_CC == {"Q": "none", "W": "slow", "E": "slow"}
        assert fiora.parse_abilities.cc_kinds == fiora.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Fiora")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert (
            "the enemy champion struck is also slowed and crippled by 25% "
            "for 2 seconds" in cc_review.slot_text(data, "W")
        )

    def test_bladework_slows_through_the_swings_it_forces(self):
        """The row's damage is the engine's reattributed empowered swings,
        so the engine builds the zero-damage carrier the slow rides."""
        data = cc_review.kit("Fiora")
        assert "the first attack slows the target by 30% for 1 second" in (
            cc_review.slot_text(data, "E")
        )
        entry = parse_champion_abilities(data, 18, 100.0)["E"]
        assert entry["empowers_next_auto"] == {"hits": 2}
        (marker,) = entry["parts"]
        assert (marker.amount, marker.cc_kind) == (0.0, "slow")

    def test_the_whole_kit_is_reviewed_and_the_fight_certifies(self):
        assert cc_review.unreviewed_ability_slots("Fiora") == []
        coverage = cc_review.fimbulwinter_coverage("Fiora")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
