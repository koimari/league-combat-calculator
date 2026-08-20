"""Sona's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract
from tests import rider_probe
from src.calculator.champions import sona
from tests import cc_review


class TestReviewedCrowdControl:
    """Sona's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sona")
        assert sona.MODULE_CC == {"Q": "none", "R": "stun"}
        # Power Chord's Tempo slow rides the passive's empowered attack,
        # not Q, so Q's own text carries no control at all.
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sona") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sona")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPowerChordRider:
    """Sona P prices the chord three basic abilities empower (slice 6)."""

    def test_one_chord_reaches_the_total(self):
        """Level 18, no items: 240.0 raw magic on one empowered attack.

        Cached P "Per-Level Scaling" 20 : 270 (based on level) + 20% AP —
        the unmodified chord; the probe target halves magic damage.
        """
        result = rider_probe.fight("Sona")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Power Chord (on-hit)"
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(120.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_no_chord_prices_nothing(self):
        result = rider_probe.fight("Sona", champion_options={"p_power_chords": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_the_map_reports_what_each_slot_prices(self):
        assert get_champion_module_contract("Sona").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "out_of_scope",
            "R": "modeled",
        }
