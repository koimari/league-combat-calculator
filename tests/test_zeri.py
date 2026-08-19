"""Reviewed crowd control for Zeri (MODULE_CC) — and the slot that still
withholds.

Ultrashock Laser slows; nothing else in the kit controls.  Spark Surge's
seven-round bonus is one aggregated row with no timing, so this kit stays
coarse.
"""

from src.calculator.champions import parse_champion_abilities, zeri
from tests import cc_review


class TestReviewedCrowdControl:
    """Zeri's reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zeri")
        assert zeri.MODULE_CC == {"Q": "none", "W": "slow", "R": "none"}
        assert zeri.parse_abilities.cc_kinds == zeri.MODULE_CC
        assert "slows them for 2 seconds" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_spark_surge_withholds_on_its_aggregated_round_row(self):
        """E is control-free, but its seven rounds have no timing."""
        data = cc_review.kit("Zeri")
        assert "E" not in zeri.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["E"]["parts"]
        assert part.count == zeri._E_LIGHTNING_ROUNDS_ROUNDS
        assert part.time_offset is None and part.hit_interval is None

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Zeri") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Zeri")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
