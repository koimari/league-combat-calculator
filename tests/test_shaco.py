"""Shaco's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import shaco
from tests import cc_review


class TestReviewedCrowdControl:
    """Q/W/E reviewed; R's optional clone attacks keep Shaco coarse."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Shaco")
        assert shaco.MODULE_CC == {"Q": "none", "W": "immobilize", "E": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Two immobilize kinds land together, so the reviewed kind is the
        # un-narrowed one rather than a choice between them.
        assert "fearing nearby enemies" in cc_review.slot_text(data, "W")
        assert "rooting them" in cc_review.slot_text(data, "W")
        assert "slows them for 3 seconds" in cc_review.slot_text(data, "E")

    def test_r_is_undeclared_because_its_entry_can_carry_a_second_part(self):
        """Hallucinate's boxes do control what the explosion damages, but with
        ``r_clone_attacks`` set the entry carries a second, separately timed
        part, so the explosion is not a hit the ledger can time in every
        configuration."""
        r_text = cc_review.slot_text(cc_review.kit("Shaco"), "R")
        assert "deploy three mini-boxes that activate instantly" in r_text
        # The explosion has no instant either: the cache times it to the
        # clone's death, and gives only the 18-second cap on its life.
        assert (
            "remaining within control range of him as a controllable clone "
            "for up to 18 seconds" in r_text
        )
        assert (
            "the clone will explode upon dying or expiring to deal magic "
            "damage to nearby enemies" in r_text
        )
        assert "R" not in shaco.MODULE_CC

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Shaco") == ["R"]
        coverage = cc_review.fimbulwinter_coverage("Shaco")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
