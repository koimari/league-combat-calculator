"""Tests for the Evelynn champion module."""

from src.calculator.champions import evelynn
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Evelynn's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Evelynn")
        assert evelynn.MODULE_CC == {
            "Q": "none",
            "E": "none",
            "R": "none",
            "P": "none",
            "W": "per_part",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # W is absent rather than "none": Allure's expunge slows and
        # charms, but W emits no damage row to carry the answer.
        assert evelynn.MODULE_CC["W"] == "per_part"
        assert "charms them" in cc_review.slot_text(data, "W")


def test_the_packet_states_evelynns_recasts_and_execute():
    """Three Q recasts author four legs; the execute prices above the base."""
    assert len(row_review.parts("Evelynn", "Q", q_recasts=3)) == 4
    assert row_review.priced("Evelynn", "R", r_execute_ready=True) > 500
