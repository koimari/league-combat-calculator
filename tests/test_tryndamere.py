"""Tryndamere's crowd-control review: one damaging slot, and it is cc-free.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import get_champion_module_contract, tryndamere
from tests import cc_review


class TestReviewedCrowdControl:
    """Spinning Slash is the only slot that damages, and it controls nothing."""

    def test_the_whole_cached_kit_puts_its_control_outside_the_damage(self):
        data = cc_review.kit("Tryndamere")
        assert tryndamere.MODULE_CC == {"E": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # Mocking Shout is where the kit's slow lives, and it deals no
        # damage, so no part can carry that answer.
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == ["slow"]
        assert get_champion_module_contract("Tryndamere").coverage["W"] == "no_damage"
        for slot in ("P", "Q", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Tryndamere") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Tryndamere")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
