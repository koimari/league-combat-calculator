"""Tests for the Draven champion module."""

from src.calculator.champions import draven
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Draven's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Draven")
        assert draven.MODULE_CC == {
            "Q": "none",
            "E": "airborne",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        assert "knocking them aside" in " ".join(cc_review.slot_text(data, "E").split())
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == ["slow"]
        # The only "slow" in R's text is the axes "slowly coming to a
        # stop" — an adverb, not a debuff.
        assert "slowly coming to a stop" in cc_review.slot_text(data, "R")


def test_the_packet_states_dravens_axe_and_pass_counts():
    """Q empowers the next auto; R's two passes are the option's own count."""
    assert row_review.entry("Draven", "Q")["empowers_next_auto"]
    assert row_review.parts("Draven", "R", r_passes=2)[0].count == 2
