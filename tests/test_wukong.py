"""Reviewed crowd control for Wukong (MODULE_CC).

Cyclone knocks up; Crushing Blow's armor reduction is a shred, not
control.
"""

from src.calculator.champions import wukong
from tests import cc_review


class TestReviewedCrowdControl:
    """Wukong's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Wukong")
        assert wukong.MODULE_CC == {"Q": "none", "E": "none", "R": "knockup"}
        assert wukong.parse_abilities.cc_kinds == wukong.MODULE_CC
        assert "knock them up once for 0.6 seconds" in cc_review.slot_text(data, "R")
        # Q's only debuff is "armor reduction for 3 seconds" — a resistance
        # shred, which is not a kind in the control vocabulary.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == []
        assert "inflict armor reduction for 3 seconds" in q_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_the_unmodelled_slots_stay_absent(self):
        """W is the clone's pet timeline; P is the armor buff."""
        assert "W" not in wukong.MODULE_CC and "P" not in wukong.MODULE_CC
        assert wukong.MODULE_COVERAGE["W"] == "out_of_scope"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Wukong") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Wukong")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
