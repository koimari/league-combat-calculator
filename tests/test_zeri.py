"""Reviewed crowd control for Zeri (MODULE_CC), and Spark Surge's rounds.

Ultrashock Laser slows; nothing else in the kit controls.  Spark Surge's
seven-round bonus rides Burst Fire, so it takes Burst Fire's authored
placement instead of staying an untimed aggregate.
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
        assert zeri.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
        }
        assert zeri.parse_abilities.cc_kinds == zeri.MODULE_CC
        assert "slows them for 2 seconds" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_spark_surges_rounds_take_burst_fires_authored_placement(self):
        """E is control-free, and its rounds ARE Q's rounds."""
        data = cc_review.kit("Zeri")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "empowering Burst Fire to deal bonus magic damage" in " ".join(
            effect["description"] for effect in data["abilities"]["E"][0]["effects"]
        )
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (rider,) = parsed["E"]["parts"]
        (burst,) = parsed["Q"]["parts"]
        assert rider.count == zeri._E_LIGHTNING_ROUNDS_ROUNDS == burst.count
        assert (rider.time_offset, rider.hit_interval) == (
            burst.time_offset,
            burst.hit_interval,
        )
        assert rider.cc_kind == "none"

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Zeri") == []
        coverage = cc_review.fimbulwinter_coverage("Zeri")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
