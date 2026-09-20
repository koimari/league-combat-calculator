"""Tests for the Olaf champion module."""

from src.calculator.champions import olaf
from tests import cc_review


class TestReviewedCrowdControl:
    """Olaf's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Olaf")
        assert olaf.MODULE_CC == {
            "Q": "slow",
            "E": "none",
            "P": "none",
            "W": "none",
            "R": "none",
        }
        assert "slows them for 1 : 3" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # The shield, the self-cleanse and the innate attack speed review
        # as "none" against the wider screen: no control word at all.
        for slot in ("W", "R", "P"):
            assert cc_review.any_control_hits(data, slot) == [], slot
