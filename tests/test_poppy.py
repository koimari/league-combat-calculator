"""Tests for the Poppy champion module."""

from src.calculator.champions import poppy
from tests import cc_review


class TestReviewedCrowdControl:
    """Poppy's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Poppy")
        assert poppy.MODULE_CC == {
            "Q": "slow",
            "W": "knockup",
            "E": "immobilize",
            "R": "knockup",
            "P": "none",
        }
        assert "a field for 1 second that slows enemies within" in cc_review.slot_text(
            data, "Q"
        )
        assert "knocked up for 0.5 seconds" in cc_review.slot_text(data, "W")
        # E applies a forced displacement, and a stun on terrain: two
        # immobilize kinds from one cast, which the un-narrowed kind states.
        e_text = cc_review.slot_text(data, "E")
        assert "carries them along with her for up to 400 units" in e_text
        assert "deal the same physical damage again and stuns them" in e_text
        # R knocks up in both priced branches; the charged branch adds a
        # knock back, a second immobilize rather than a different answer.
        r_text = cc_review.slot_text(data, "R")
        assert "knocking them up for 1 second" in r_text
        assert "knocked back up-to 3400 units" in r_text
        # P is absent: Iron Ambassador is an on-hit rider on the autos.
        assert poppy.MODULE_CC["P"] == "none"
