"""Reviewed crowd control for Warwick (MODULE_CC).

Infinite Duress suppresses for the whole channel it damages through;
Jaws of the Beast only bites.
"""

from src.calculator.champions import get_champion_module_contract, warwick
from tests import cc_review


class TestReviewedCrowdControl:
    """Warwick's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Warwick")
        assert warwick.MODULE_CC == {"Q": "none", "R": "suppression"}
        assert warwick.parse_abilities.cc_kinds == warwick.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        r_text = cc_review.slot_text(data, "R")
        assert "channels for up to 1.5 seconds to suppress" in r_text
        assert "he then knocks them down" in r_text

    def test_the_out_of_scope_slots_stay_absent(self):
        """E holds the fear and the 90% slow, but prices no damage."""
        data = cc_review.kit("Warwick")
        assert "W" not in warwick.MODULE_CC and "E" not in warwick.MODULE_CC
        assert get_champion_module_contract("Warwick").coverage["E"] == "out_of_scope"
        assert "fearing nearby enemies for 1 second" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Warwick") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Warwick")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
