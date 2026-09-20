"""Tests for the Neeko champion module."""

from src.calculator.champions import neeko
from tests import cc_review


class TestReviewedCrowdControl:
    """Neeko's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Neeko")
        assert neeko.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "root",
            "R": "stun",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "roots them for a duration" in cc_review.slot_text(data, "E")
        # R's leap knocks up and deals nothing; the landing burst is the
        # damaging part and it stuns, so the stun is the kind that rides it.
        r_text = cc_review.slot_text(data, "R")
        assert "knocking up nearby enemies for 0.6 seconds" in r_text
        assert "deals magic damage to nearby enemies and stuns them" in r_text
        # P is absent: Inherent Glamour is a disguise that damages nothing.
        assert neeko.MODULE_CC["P"] == "none"
