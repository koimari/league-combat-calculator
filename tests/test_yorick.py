"""Reviewed crowd control for Yorick (MODULE_CC).

Mourning Mist slows; Dark Procession's displacement lives on a wall that
deals no damage.
"""

from src.calculator.champions import yorick
from tests import cc_review


class TestReviewedCrowdControl:
    """Yorick's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yorick")
        assert yorick.MODULE_CC == {"Q": "none", "E": "slow", "R": "none"}
        assert yorick.parse_abilities.cc_kinds == yorick.MODULE_CC
        assert "slowed by 30% for 1.5 seconds" in cc_review.slot_text(data, "E")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_dark_procession_is_absent_because_the_ring_deals_no_damage(self):
        data = cc_review.kit("Yorick")
        assert "W" not in yorick.MODULE_CC
        w_text = cc_review.slot_text(data, "W")
        assert "knocking aside enemies hit by the walls" in w_text
        assert "they are pulled inside" in w_text
        assert yorick.MODULE_COVERAGE["W"] == "out_of_scope"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yorick") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yorick")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
