"""Tests for the Ryze champion module."""

from src.calculator.champions import ryze
from tests import cc_review


class TestReviewedCrowdControl:
    """Ryze's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ryze")
        assert ryze.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # W's Flux bonus roots instead of slowing, but that empowerment has
        # no option or damage row here, so the priced cast is the base
        # seize and the slow is what it applies.
        w_text = cc_review.slot_text(data, "W")
        assert "dealing magic damage and slowing them by 50%" in w_text
        assert "the target is rooted instead of slowed" in w_text
        # R's root, disarm and silence land on Ryze and his own allies.
        r_text = cc_review.slot_text(data, "R")
        assert "ryze and all allied units within the portal will blink" in r_text
        assert "become rooted, disarmed, silenced and untargetable" in r_text
        # P only raises Ryze's maximum mana.
        assert ryze.MODULE_CC["P"] == "none"
