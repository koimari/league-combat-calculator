"""Taric's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract
from tests import rider_probe
from src.calculator.champions import taric
from tests import cc_review


class TestReviewedCrowdControl:
    """Dazzle is the whole of Taric's reviewable control."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Taric")
        assert taric.MODULE_CC == {"E": "stun"}
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "E")
        # Q heals, W shields and R grants invulnerability: no other slot
        # damages, so no other slot has a control answer to carry.
        for slot in ("P", "Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Taric") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Taric")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestBravadoRider:
    """Taric P prices the attacks an ability cast empowers (slice 6)."""

    def test_two_empowered_attacks_reach_the_total(self):
        """Level 18, no items: 2 x 93.0 raw magic.

        Cached P "Per-Level Scaling" 25 : 101 (based on level) + 15% bonus
        armor; the probe target halves magic damage, so 93.0 lands.
        """
        result = rider_probe.fight("Taric")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Bravado (on-hit)"
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(93.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_no_empowered_attack_prices_nothing(self):
        result = rider_probe.fight("Taric", champion_options={"p_empowered_attacks": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_the_map_reports_what_each_slot_prices(self):
        """Only Cosmic Radiance's invulnerability has no engine axis."""
        assert get_champion_module_contract("Taric").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "out_of_scope",
        }
