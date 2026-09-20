"""Tests for the Renata Glasc champion module."""

from src.calculator.champions import renata_glasc
from tests import cc_review


class TestReviewedCrowdControl:
    """Renata Glasc's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Renata Glasc")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert renata_glasc.MODULE_CC == {
            "Q": "root",
            "E": "slow",
            "R": "berserk",
            "P": "none",
            "W": "none",
        }
        q_text = cc_review.slot_text(data, "Q")
        assert "deals magic damage to the first enemy hit and roots them" in q_text
        # The recast's stun lands on the enemies the thrown target passes
        # through, not on the hooked target this row prices.
        assert "all secondary targets hit are stunned for 0.5 seconds" in q_text
        assert "dealt magic damage and slowed by 30%" in cc_review.slot_text(data, "E")
        # W and R deal no damage; R's berserk is real control, published
        # as a sourced ControlEvent off the cached Berserk Duration row.
        # P is an on-hit mark on the autos.
        assert renata_glasc.MODULE_CC["W"] == "none"
        assert renata_glasc.MODULE_CC["P"] == "none"
        assert "become berserk for a duration" in cc_review.slot_text(data, "R")
