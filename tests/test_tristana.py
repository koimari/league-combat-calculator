"""Tristana's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import tristana
from tests import cc_review


class TestReviewedCrowdControl:
    """Tristana's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Tristana")
        assert tristana.MODULE_CC == {
            "W": "slow",
            "E": "none",
            "R": "immobilize",
            "P": "none",
            "Q": "none",
        }
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "W")
        # E's only control word is a reference to R's knock back, not to
        # anything the charge itself applies.
        assert "the charge then detonates" in cc_review.slot_text(data, "E")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == ["knock"]
        # R knocks back and stuns at once, so the reviewed kind is the
        # un-narrowed one.
        assert "knocked back and stunned for a duration" in (
            cc_review.slot_text(data, "R")
        )
