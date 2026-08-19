"""Sylas's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import sylas
from tests import cc_review


class TestReviewedCrowdControl:
    """W and E reviewed; Q's summed packet keeps Sylas coarse."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sylas")
        assert sylas.MODULE_CC == {"W": "none", "E": "immobilize"}
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # Abduct stuns on the chain hit and knocks up on arrival — two
        # immobilize kinds, so the reviewed kind is the un-narrowed one.
        assert "stun them for 0.5 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 0.5 seconds" in cc_review.slot_text(data, "E")

    def test_q_is_undeclared_because_its_packet_sums_two_hits(self):
        """Chain Lash does slow, but the packet prices the cached "Total
        Magic Damage" row — the lash and the 0.6s-delayed explosion in one
        cast-boundary lump — so no part of it is a hit the ledger can time."""
        data = cc_review.kit("Sylas")
        assert "slowing them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        assert "Q" not in sylas.MODULE_CC
        assert sylas.PACKET_SPEC["slots"]["Q"]["base"] == [
            100.0,
            175.0,
            250.0,
            325.0,
            400.0,
        ]

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Sylas") == ["Q"]
        coverage = cc_review.fimbulwinter_coverage("Sylas")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
