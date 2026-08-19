"""Twitch's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import twitch
from tests import cc_review


class TestReviewedCrowdControl:
    """Contaminate is the only cast that reaches the ability ledger."""

    def test_the_whole_cached_kit_puts_its_control_outside_the_damage(self):
        data = cc_review.kit("Twitch")
        assert twitch.MODULE_CC == {"E": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        # Venom Cask is where the kit's slow lives, and it deals no damage.
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == ["slow"]
        assert twitch.MODULE_COVERAGE["W"] == "out_of_scope"
        for slot in ("P", "Q", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Twitch") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Twitch")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
