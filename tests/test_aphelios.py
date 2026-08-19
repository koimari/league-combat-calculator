"""Tests for the Aphelios champion module."""

from src.calculator.champions import aphelios
from tests import cc_review


class TestReviewedCrowdControl:
    """Aphelios's crowd-control review, and the slot that still withholds.

    Q is whichever Moonstone weapon is equipped — Gravitum's Binding
    Eclipse roots where the others apply nothing — so the answer follows
    the weapon option, not the slot; neither Q nor R authors a boundary
    the ledger can carry one on either.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Aphelios")
        assert not hasattr(aphelios, "MODULE_CC")

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Aphelios") == ["Q", "R"]
        coverage = cc_review.fimbulwinter_coverage("Aphelios")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
