"""Tests for the Ekko champion module."""

from src.calculator.champions import ekko
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Ekko's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ekko")
        assert ekko.MODULE_CC == {
            "Q": "slow",
            "E": "none",
            "R": "none",
            "P": "none",
            "W": "per_part",
        }
        assert "field that slows nearby enemies" in " ".join(
            cc_review.slot_text(data, "Q").split()
        )
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == ["stasis"]
        # The "stasis" in R's text is Ekko's own, not something he
        # applies to the enemies his arrival explosion damages.
        assert "ekko enters stasis" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Ekko") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Ekko")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_packet_states_ekkos_delayed_return_and_stack_procs():
    """Q's second leg is the 2s return; the passive prices the armed proc."""
    assert row_review.parts("Ekko", "Q")[1].time_offset == 2.0
    assert row_review.entry("Ekko", "passive", p_procs=1)["proc_count"] == 1
