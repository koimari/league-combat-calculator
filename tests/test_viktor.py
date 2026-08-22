"""Reviewed crowd control for Viktor (MODULE_CC).

Every modelled slot is control-free; the slow and stun live in Gravity
Field, which this module does not price.
"""

from src.calculator.champions import get_champion_module_contract, viktor
from tests import cc_review


class TestReviewedCrowdControl:
    """Viktor's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
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
        }
        assert viktor.parse_abilities.cc_kinds == viktor.MODULE_CC
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

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

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Viktor") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Viktor")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
