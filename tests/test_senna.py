"""Tests for the Senna champion module."""

from src.calculator.champions import senna
from tests import cc_review


class TestReviewedCrowdControl:
    """Senna's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Senna")
        assert senna.MODULE_CC == {
            "Q": "slow",
            "W": "root",
            "R": "none",
            "P": "none",
            "E": "none",
        }
        assert "deals physical damage to enemies hit and slows them" in (
            cc_review.slot_text(data, "Q")
        )
        assert "rooting them and surrounding enemies" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # E (camouflage) deals no damage and P's mark consume rides the
        # auto stream, so neither carries an ability event of its own.
        assert senna.MODULE_CC["E"] == "none"
        assert senna.MODULE_CC["P"] == "none"
