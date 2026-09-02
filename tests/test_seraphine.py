"""Seraphine's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
``MODULE_CC`` is where this kit answers, read from the cached text, and the
probe below is the reason it exists.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, seraphine
from tests import cc_review, rider_probe


class TestReviewedCrowdControl:
    """Seraphine's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Seraphine")
        assert seraphine.MODULE_CC == {"Q": "none", "E": "slow", "R": "charm"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slows them by 99%" in cc_review.slot_text(data, "E")
        assert "charms them" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Seraphine") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Seraphine")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestStagePresenceRider:
    """Seraphine P fires her Notes on the empowered attack (census slice 6)."""

    def test_four_notes_reach_the_total(self):
        """Level 18, no items, the 4-Note cap: 4 x 25.0 raw magic.

        Cached P "Bonus Magic Damage" 4 : 27.47 (based on level) + 4% AP per
        Note; the probe target halves magic damage, so 50.0 lands.
        """
        result = rider_probe.fight("Seraphine")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Stage Presence (on-hit)"
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(50.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_one_note_prices_a_quarter_of_the_cap(self):
        row = rider_probe.rider_row("Seraphine", champion_options={"p_notes": 1})
        assert row["total_damage"] == pytest.approx(12.5, abs=0.05)

    def test_no_notes_prices_nothing(self):
        result = rider_probe.fight("Seraphine", champion_options={"p_notes": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Seraphine").coverage == dict.fromkeys(
            "PQWER", "modeled"
        )
