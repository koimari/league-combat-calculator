"""Reviewed crowd control for Veigar (MODULE_CC) — and the two slots that
still withhold.

Q and R are control-free; the cage deals no damage and Dark Matter's
sourced impact delay is not authored, so this kit stays coarse.
"""

from src.calculator.champions import veigar
from tests import cc_review


class TestReviewedCrowdControl:
    """Veigar's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Veigar")
        assert veigar.MODULE_CC == {"Q": "none", "R": "none"}
        assert veigar.parse_abilities.cc_kinds == veigar.MODULE_CC
        for slot in ("Q", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_cage_carries_the_kits_stun_and_no_damage(self):
        data = cc_review.kit("Veigar")
        assert "E" not in veigar.MODULE_CC
        assert "stunned for a duration" in cc_review.slot_text(data, "E")
        assert veigar.MODULE_COVERAGE["E"] == "no_damage"

    def test_dark_matter_withholds_on_its_unauthored_impact_delay(self):
        """W is control-free, but its hit does not land at the cast."""
        data = cc_review.kit("Veigar")
        assert "W" not in veigar.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "after a 1.221 seconds delay" in cc_review.slot_text(data, "W")

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Veigar") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Veigar")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
