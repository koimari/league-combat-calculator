"""Tests for the Evelynn champion module."""

from src.calculator.champions import evelynn
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Evelynn's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Evelynn")
        assert evelynn.MODULE_CC == {"Q": "none", "E": "none", "R": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # W is absent rather than "none": Allure's expunge slows and
        # charms, but W emits no damage row to carry the answer.
        assert "W" not in evelynn.MODULE_CC
        assert "charms them" in cc_review.slot_text(data, "W")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Evelynn") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Evelynn")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_evelynns_recasts_and_execute():
    """Three Q recasts author four legs; the execute prices above the base."""
    assert len(row_review.parts("Evelynn", "Q", q_recasts=3)) == 4
    assert row_review.priced("Evelynn", "R", r_execute_ready=True) > 500
