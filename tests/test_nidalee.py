"""Tests for the Nidalee champion module."""

from src.calculator.champions import nidalee
from tests import cc_review


class TestReviewedCrowdControl:
    """Nidalee's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_the_whole_cached_kit_is_free_of_control_vocabulary(self):
        data = cc_review.kit("Nidalee")
        assert nidalee.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "none",
            "P": "none",
            "R": "none",
        }
        for slot in ("P", "Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # R (Aspect of the Cougar) and P (Prowl) are absent rather than
        # "none": the form swap and the brush movement damage nothing.
        assert nidalee.MODULE_CC["R"] == "none"
        assert nidalee.MODULE_CC["P"] == "none"
