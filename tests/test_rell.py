"""Tests for the Rell champion module."""

from src.calculator.champions import rell
from tests import cc_review


class TestReviewedCrowdControl:
    """Rell's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rell")
        assert rell.MODULE_CC == {
            "Q": "stun",
            "W": "immobilize",
            "E": "none",
            "R": "pull",
            "P": "none",
        }
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing them magic damage and stunning them for 0.65 seconds" in q_text
        # Both W forms apply two immobilize kinds at once.
        w_text = cc_review.slot_text(data, "W")
        assert "stuns them for 0.8 seconds, and knocks them up" in w_text
        assert "stuns the target for 0.6 seconds, and flings them 150 units" in w_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "drags them towards her" in cc_review.slot_text(data, "R")
        # P is an on-hit rider on the auto stream.
        assert rell.MODULE_CC["P"] == "none"


def test_the_published_options_are_the_one_the_module_reads():
    """Rell's only choice is which W she casts."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Rell")["options"]}
    assert keys == {"w_variant"}
