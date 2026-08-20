"""Tests for the Draven champion module."""

from src.calculator.champions import draven
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Draven's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Draven")
        assert draven.MODULE_CC == {"Q": "none", "E": "airborne", "R": "none"}
        assert "knocking them aside" in " ".join(cc_review.slot_text(data, "E").split())
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == ["slow"]
        # The only "slow" in R's text is the axes "slowly coming to a
        # stop" — an adverb, not a debuff.
        assert "slowly coming to a stop" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Draven") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Draven")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_dravens_axe_and_pass_counts():
    """Q empowers the next auto; R's two passes are the option's own count."""
    assert row_review.entry("Draven", "Q")["empowers_next_auto"]
    assert row_review.parts("Draven", "R", r_passes=2)[0].count == 2
