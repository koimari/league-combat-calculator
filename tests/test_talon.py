"""Talon's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import talon
from tests import cc_review


class TestReviewedCrowdControl:
    """Talon's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Talon")
        assert talon.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "R": "none",
            "P": "none",
            "E": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # Rake's outward fan applies nothing; the return pass slows.
        assert "slowing them for 1 second" in cc_review.slot_text(data, "W")
