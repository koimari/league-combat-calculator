"""Reviewed crowd control for Xayah (MODULE_CC) — and the slot that still
withholds.

Q, W and R only damage.  Bladecaller's root rides a feather count with no
sourced cadence, so its row never reaches the ledger and this kit stays
coarse.
"""

from src.calculator.champions import parse_champion_abilities, xayah
from tests import cc_review


class TestReviewedCrowdControl:
    """Xayah's reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Xayah")
        assert xayah.MODULE_CC == {"Q": "none", "W": "none", "R": "none"}
        assert xayah.parse_abilities.cc_kinds == xayah.MODULE_CC
        for slot in ("Q", "W", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_bladecaller_withholds_on_its_aggregated_feather_row(self):
        """E's root is real, and its row has no per-feather timing."""
        data = cc_review.kit("Xayah")
        assert "E" not in xayah.MODULE_CC
        assert "rooted for 1.25 seconds" in cc_review.slot_text(data, "E")
        parsed = parse_champion_abilities(
            data, 18, 0.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["E"]["parts"]
        assert part.count > 1
        assert part.time_offset is None and part.hit_interval is None

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Xayah") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Xayah")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
