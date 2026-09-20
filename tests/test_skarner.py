"""Skarner's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import skarner
from tests import cc_review


class TestReviewedCrowdControl:
    """Skarner's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Skarner")
        assert skarner.MODULE_CC == {
            "P": "none",
            "Q": "slow",
            "W": "slow",
            "E": "stun",
            "R": "suppression",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []
        assert "slowing afflicted enemies by 40%" in cc_review.slot_text(data, "Q")
        assert "slow them by 20% for 1 second" in cc_review.slot_text(data, "W")
        # E's suppression is the grab that precedes the damage; the stun is
        # what lands with it, on terrain collision.
        assert "stunning them for 1.1 seconds" in cc_review.slot_text(data, "E")
        assert "suppress them for 1.5 seconds" in cc_review.slot_text(data, "R")


def test_the_published_options_are_the_one_the_module_reads():
    """Skarner's only choice is which Q he casts."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Skarner")["options"]}
    assert keys == {"q_variant"}
