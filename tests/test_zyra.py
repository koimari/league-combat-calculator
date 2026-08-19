"""Reviewed crowd control for Zyra (MODULE_CC) — and the two slots that
still withhold.

Grasping Roots roots and Stranglethorns knocks up.  Deadly Spines has an
unauthored sprout delay and the plant row cannot say which plant it is, so
this kit stays coarse.
"""

from src.calculator.champions import zyra
from tests import cc_review


class TestReviewedCrowdControl:
    """Zyra's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zyra")
        assert zyra.MODULE_CC == {"E": "root", "R": "knockup"}
        assert zyra.parse_abilities.cc_kinds == zyra.MODULE_CC
        assert "roots them for a duration" in cc_review.slot_text(data, "E")
        assert "knock up enemies within for 1 second" in cc_review.slot_text(data, "R")

    def test_deadly_spines_withholds_on_its_unauthored_sprout_delay(self):
        """Q is control-free, but its thorns do not appear at the cast."""
        data = cc_review.kit("Zyra")
        assert "Q" not in zyra.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "after a 0.625-seconds delay" in cc_review.slot_text(data, "Q")

    def test_the_plant_row_cannot_say_which_plant_it_is(self):
        """W prices plant basic attacks; Vine Lashers slow, Spitters do not."""
        assert "W" not in zyra.MODULE_CC
        assert any(
            "the Vine Lasher slow" in assumption for assumption in zyra.ASSUMPTIONS
        )
        assert {option["key"] for option in zyra.OPTIONS} == {
            "plant_count",
            "plant_attacks",
        }

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Zyra") == ["Q", "W"]
        coverage = cc_review.fimbulwinter_coverage("Zyra")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
