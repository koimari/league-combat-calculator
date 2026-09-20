"""Sett's reviewed crowd control (``MODULE_CC``), total over his five slots.

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from src.calculator.champions import sett
from tests import cc_review


class TestReviewedCrowdControl:
    """Two controls, three reviewed absences, and the fight they certify."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sett")
        assert sett.MODULE_CC == {
            "W": "none",
            "E": "pull",
            "R": "suppression",
            "P": "none",
            "Q": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "pulls in enemies at his front and back" in cc_review.slot_text(
            data, "E"
        )
        assert "suppresses and reveals the target enemy champion" in (
            cc_review.slot_text(data, "R")
        )

    def test_q_declares_none_on_a_row_of_two_attacks_summed(self):
        """Knuckle Down "empowers his next two basic attacks", and the module
        prices both from one cached total, so no part of it is a hit the
        ledger can time — the reviewed "none" lands on a part nothing reads."""
        q_text = cc_review.slot_text(cc_review.kit("Sett"), "Q")
        assert (
            "sett empowers his next two basic attacks within 5 seconds to "
            "gain 50 bonus range and deal bonus physical damage" in q_text
        )
        # A 5-second window and an attack-timer reset are the only timing
        # the entry gives: neither attack has a stated instant.
        assert "knuckle down resets sett's basic attack timer" in q_text
        assert sett.MODULE_CC["Q"] == "none"
