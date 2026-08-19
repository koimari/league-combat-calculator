"""Reviewed crowd control for Zyra (MODULE_CC) — and the slot that still
withholds.

Grasping Roots roots and Stranglethorns knocks up.  Deadly Spines is
control-free and now lands on its sourced sprout delay; the plant row
still cannot say which plant it is, so this kit stays coarse.
"""

from src.calculator.champions import parse_champion_abilities, zyra
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
        assert zyra.MODULE_CC == {"Q": "none", "E": "root", "R": "knockup"}
        assert zyra.parse_abilities.cc_kinds == zyra.MODULE_CC
        assert "roots them for a duration" in cc_review.slot_text(data, "E")
        assert "knock up enemies within for 1 second" in cc_review.slot_text(data, "R")

    def test_deadly_spines_sprouts_on_its_sourced_delay(self):
        """Q is control-free, and its thorns appear 0.625 s after the cast."""
        data = cc_review.kit("Zyra")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "after a 0.625-seconds delay" in cc_review.slot_text(data, "Q")
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["Q"]["parts"]
        assert part.time_offset == 0.625
        assert part.cc_kind == "none"

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
        assert cc_review.unreviewed_ability_slots("Zyra") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Zyra")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
