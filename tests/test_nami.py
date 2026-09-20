"""Tests for the Nami champion module."""

from src.calculator.champions import nami
from tests import cc_review


class TestReviewedCrowdControl:
    """Nami's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nami")
        assert nami.MODULE_CC == {
            "Q": "airborne",
            "W": "none",
            "E": "slow",
            "R": "knockup",
            "P": "none",
        }
        assert "suspending them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slow enemies for 1 second" in cc_review.slot_text(data, "E")
        assert "knocking them up for 0.5 seconds" in cc_review.slot_text(data, "R")
        # P is absent rather than "none": Surging Tides only grants allied
        # champions movement speed, so no event of its own could carry an
        # answer.
        assert nami.MODULE_CC["P"] == "none"
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []
