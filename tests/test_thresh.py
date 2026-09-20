"""Thresh's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import thresh
from tests import cc_review


class TestReviewedCrowdControl:
    """Thresh's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Thresh")
        assert thresh.MODULE_CC == {
            "Q": "immobilize",
            "E": "knockback",
            "R": "slow",
            "P": "none",
            "W": "none",
        }
        # Death Sentence stuns and renders airborne at once, so the
        # reviewed kind is the un-narrowed one.
        assert "stun and reveal them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        assert "render them airborne for 0.4 seconds" in cc_review.slot_text(data, "Q")
        # Flay knocks and then slows; the knock-back is the immobilize.
        assert "knocked 200 units in the target direction" in (
            cc_review.slot_text(data, "E")
        )
        assert "slowing them by 99% for 2 seconds" in cc_review.slot_text(data, "R")
