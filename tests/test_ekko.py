"""Tests for the Ekko champion module."""

from src.calculator.champions import ekko
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Ekko's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
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


def test_the_packet_states_ekkos_delayed_return_and_stack_procs():
    """Q's second leg is the 2s return; the passive prices the armed proc."""
    assert row_review.parts("Ekko", "Q")[1].time_offset == 2.0
    assert row_review.entry("Ekko", "passive", p_procs=1)["proc_count"] == 1
