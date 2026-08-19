"""Reviewed crowd control for Xerath (MODULE_CC).

Eye of Destruction slows, Shocking Orb stuns; Arcanopulse's only slow is
Xerath's own charge penalty.
"""

from src.calculator.champions import xerath
from tests import cc_review


class TestReviewedCrowdControl:
    """Xerath's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Xerath")
        assert xerath.MODULE_CC == {"Q": "none", "W": "slow", "E": "stun", "R": "none"}
        assert xerath.parse_abilities.cc_kinds == xerath.MODULE_CC
        assert "slowing them by 25% for 2.5 seconds" in cc_review.slot_text(data, "W")
        assert "stuns them for" in cc_review.slot_text(data, "E")
        # Q's only "slow" is Xerath's own charge penalty, not a debuff.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == ["slow"]
        assert "xerath charges while being slowed by" in q_text
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_the_sourced_blast_delay_is_the_one_the_rows_author(self):
        data = cc_review.kit("Xerath")
        assert xerath._BLAST_DELAY_SECONDS == 0.528
        assert "unable to act for 0.528 seconds" in cc_review.slot_text(data, "Q")
        assert "after 0.528 seconds" in cc_review.slot_text(data, "W")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Xerath") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Xerath")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
