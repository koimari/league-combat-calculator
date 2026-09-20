"""Tryndamere's crowd-control review: one damaging slot, and it is cc-free.

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import get_champion_module_contract, tryndamere
from tests import cc_review


class TestReviewedCrowdControl:
    """Spinning Slash is the only slot that damages, and it controls nothing."""

    def test_the_whole_cached_kit_puts_its_control_outside_the_damage(self):
        data = cc_review.kit("Tryndamere")
        assert tryndamere.MODULE_CC == {
            "E": "none",
            "P": "none",
            "Q": "none",
            "W": "per_part",
            "R": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # Mocking Shout is where the kit's slow lives, and it deals no
        # damage, so no part can carry that answer.
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == ["slow"]
        assert get_champion_module_contract("Tryndamere").coverage["W"] == "no_damage"
        for slot in ("P", "Q", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
