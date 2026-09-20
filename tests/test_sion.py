"""Sion's reviewed crowd control (``MODULE_CC`` plus Q's charge-dependent part).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import sion
from src.calculator.champions.slot_cc import CC_PER_PART
from tests import cc_review


def _q_parts(charge: float):
    """Decimating Smash's parts at a charge fraction, through the module."""
    data = cc_review.kit("Sion")
    results = sion.parse_abilities(
        data, 18, 0.0, champion_options={"q_charge_fraction": charge}
    )
    return results["Q"]["parts"]


class TestReviewedCrowdControl:
    """Sion's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sion")
        assert sion.MODULE_CC == {
            "Q": CC_PER_PART,
            "W": "none",
            "E": "slow",
            "R": "slow",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # E's stun and knock-back reach only "a minion or non-epic monster";
        # R's pull and stun reach only "enemies in a smaller radius".  The
        # slow is what every damaged target takes.
        assert "slows them for 2.5 seconds" in cc_review.slot_text(data, "E")
        assert "are slowed for 3 seconds" in cc_review.slot_text(data, "R")
        assert "in a smaller radius" in cc_review.slot_text(data, "R")

    def test_q_answers_by_charge_because_the_cached_text_does(self):
        """Uncharged Decimating Smash slows; charged for at least a second it
        knocks up and stuns instead, so Q authors its kind on its part."""
        text = cc_review.slot_text(cc_review.kit("Sion"), "Q")
        assert "slowing them by 50%" in text
        assert "charged for at least 1 second" in text
        assert "knocking them up" in text
        assert sion.MODULE_CC["Q"] == CC_PER_PART
        assert _q_parts(0.0)[0].cc_kind == "slow"
        assert _q_parts(1.0)[0].cc_kind == "immobilize"
