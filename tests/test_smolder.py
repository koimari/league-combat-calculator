"""Smolder's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import smolder
from tests import cc_review


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
        assert smolder.PACKET_SPEC["slots"]["R"]["base"] == [150.0, 250.0, 350.0]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Smolder") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Smolder")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
