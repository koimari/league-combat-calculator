"""Smolder's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import smolder
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Smolder's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Smolder")
        assert smolder.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slows them by 35% for 1.5 seconds" in cc_review.slot_text(data, "W")
        # E's only control word is about Smolder himself, not the target.
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["immobiliz"]
        assert "becomes immobilized" in cc_review.slot_text(data, "E")

    def test_r_reads_none_because_the_module_prices_the_outer_row(self):
        """MMOOOMMMM!'s slow is gated on the centre, and the packet prices
        the cached outer "Physical Damage" row rather than the "Increased
        Physical Damage" centre one."""
        data = cc_review.kit("Smolder")
        assert "with those in the center taking 50% increased damage" in (
            cc_review.slot_text(data, "R")
        )
        assert smolder.SLOTS.packet_spec["slots"]["R"]["base"] == [150.0, 250.0, 350.0]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Smolder") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Smolder")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPricedRows:
    """W and E price the whole cast, not one of its hits.

    The generated packets read "Glob Physical Damage" for W (no
    explosion) and "Physical Damage per Hit" for E (one bolt of five).
    Both cached entries carry the cast's total, and that is what the
    module reads.
    """

    def test_achooo_prices_the_glob_and_the_champion_hit_explosion(self):
        total = row_review.cached_row(
            "Smolder", "W", "Total Physical Damage On Champion Hit"
        )
        glob = row_review.cached_row("Smolder", "W", "Glob Physical Damage")
        explosion = row_review.cached_row("Smolder", "W", "Explosion Physical Damage")
        assert total == pytest.approx(glob + explosion)
        assert row_review.priced("Smolder", "W") == pytest.approx(total)
        assert row_review.packet_row("Smolder", "W", smolder)[4] == 100.0

    def test_flap_flap_flap_prices_the_five_bolt_floor(self):
        total = row_review.cached_row("Smolder", "E", "Minimum Total Physical Damage")
        per_bolt = row_review.cached_row("Smolder", "E", "Physical Damage per Hit")
        assert total == pytest.approx(5 * per_bolt)
        assert row_review.priced("Smolder", "E") == pytest.approx(total)
        assert row_review.packet_row("Smolder", "E", smolder)[4] == 30.0
