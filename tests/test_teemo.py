"""Teemo's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import teemo
from src.calculator.control_spec import CC_KIND_VOCABULARY, IMMOBILIZING_CC_KINDS
from tests import cc_review


class TestReviewedCrowdControl:
    """Teemo's whole kit is reviewed once ``blind`` exists as a kind."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Teemo")
        assert teemo.MODULE_CC == {
            "Q": "blind",
            "E": "none",
            "R": "slow",
            "P": "none",
            "W": "none",
        }
        assert "blinds them for a duration" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "slowing them for 4 seconds" in cc_review.slot_text(data, "R")

    def test_a_blind_is_crowd_control_the_vocabulary_now_names(self):
        """Blinding Dart applies real control that is neither an immobilize
        nor a movement slow, so "none" would be false and "slow" wrong."""
        assert "blind" in CC_KIND_VOCABULARY
        assert "blind" not in IMMOBILIZING_CC_KINDS
