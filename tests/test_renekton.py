"""Tests for the Renekton champion module."""

from src.calculator.champions import renekton
from tests import cc_review


class TestReviewedCrowdControl:
    """Renekton's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Renekton")
        assert renekton.MODULE_CC == {
            "Q": "none",
            "W": "stun",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        assert "stunning them for 0.75 seconds" in cc_review.slot_text(data, "W")
        # P is Fury bookkeeping with no damage row.
        assert renekton.MODULE_CC["P"] == "none"
