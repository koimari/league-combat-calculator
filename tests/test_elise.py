"""Tests for the Elise champion module."""

from src.calculator.champions import elise
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Elise's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Elise")
        assert elise.MODULE_CC == {"Q": "none", "W": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # E is absent rather than "none": Cocoon does stun, but it deals
        # no damage, so no event of its own could carry an answer.
        assert "E" not in elise.MODULE_CC
        assert "stunning the first enemy hit" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Elise") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Elise")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_elises_spider_form_reads():
    """Spider form is an on-hit passive and a missing-health Q."""
    spider = {"spider_form": True, "q_form": 1}
    assert "on_hit" in row_review.entry("Elise", "passive", **spider)
    assert "missing health" in row_review.entry("Elise", "Q", **spider)["detail"]
