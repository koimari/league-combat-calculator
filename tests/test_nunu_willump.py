"""Tests for the Nunu & Willump champion module."""

from src.calculator.champions import nunu_willump
from tests import cc_review


class TestReviewedCrowdControl:
    """Nunu & Willump's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nunu & Willump")
        assert nunu_willump.MODULE_CC == {
            "Q": "none",
            "W": "immobilize",
            "E": "slow",
            "R": "slow",
            "P": "none",
        }
        # Q's devour stun-and-pull is gated on killing a minion or a
        # small/medium monster; against the fight's champion target it
        # "deals magic damage and the heal is reduced to 60%".
        q_text = cc_review.slot_text(data, "Q")
        assert "if consume would kill the target minion" in q_text
        assert "against champions, he deals magic damage" in q_text
        # W applies two immobilize kinds in one cast, which is what the
        # un-narrowed "immobilize" states.
        assert "knocking them up for 0.5 : 0.75" in cc_review.slot_text(data, "W")
        assert "subsequently stunning them" in cc_review.slot_text(data, "W")
        assert "enemies hit 3 times are slowed for 1 second" in cc_review.slot_text(
            data, "E"
        )
        assert "will remain slowed" in cc_review.slot_text(data, "R")
        # P is absent: Call of the Freljord is an attack-speed buff with no
        # damage row of its own.
        assert nunu_willump.MODULE_CC["P"] == "none"
