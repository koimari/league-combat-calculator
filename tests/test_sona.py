"""Sona's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import sona
from tests import cc_review


class TestReviewedCrowdControl:
    """Sona's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sona")
        assert sona.MODULE_CC == {"Q": "none", "R": "stun"}
        # Power Chord's Tempo slow rides the passive's empowered attack,
        # not Q, so Q's own text carries no control at all.
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sona") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sona")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
