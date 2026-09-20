"""Reviewed crowd control for Viktor (MODULE_CC).

Every modelled slot is control-free; the slow and stun live in Gravity
Field, which this module does not price.
"""

from functools import partial

import pytest

from src.calculator.champions import get_champion_module_contract, viktor
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Viktor's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Viktor")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert viktor.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_coverage_labels_match_what_the_slots_emit(self):
        # W emits its sourced control event, so it is no_damage, not
        # out_of_scope; P alone stays outside the model.
        contract = get_champion_module_contract("Viktor")
        assert contract.coverage["W"] == "no_damage"
        assert contract.coverage["P"] == "out_of_scope"

    def test_gravity_field_publishes_the_slow_it_can_source(self):
        """W prices no damage, so its slow is a sourced control event.

        The 1-second refreshing slow window and the ranked Slow row both
        have atoms; the fifth-stack 1.5s stun has none, so it stays
        unpriced rather than being declared against a prose literal.
        """
        data = cc_review.kit("Viktor")
        w_text = cc_review.slot_text(data, "W")
        assert "slow enemies within for 1 second" in w_text
        assert "knock down and stun the target for 1.5 seconds" in w_text

    def test_arcane_storms_disrupt_is_not_a_kind_in_the_vocabulary(self):
        """R interrupts channels; no control-armed passive keys on that."""
        data = cc_review.kit("Viktor")
        r_text = cc_review.slot_text(data, "R")
        assert "disrupting their channeled abilities" in r_text
        assert cc_review.control_words(r_text) == []
