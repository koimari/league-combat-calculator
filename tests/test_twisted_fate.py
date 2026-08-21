"""Twisted Fate's reviewed crowd control (``MODULE_CC`` plus W's card part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import twisted_fate
from tests import cc_review


def _w_parts(card: int):
    """Pick a Card's parts for one card selection, through the module."""
    data = cc_review.kit("Twisted Fate")
    results = twisted_fate.parse_abilities(
        data, 18, 0.0, champion_options={"w_card": card}
    )
    return results["W"]["parts"]


class TestReviewedCrowdControl:
    """Twisted Fate's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Twisted Fate")
        assert twisted_fate.MODULE_CC == {"Q": "none", "E": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_w_answers_by_card_because_each_card_bonus_does(self):
        text = cc_review.slot_text(cc_review.kit("Twisted Fate"), "W")
        assert "stuns the target for a duration" in text
        assert "all targets hit are slowed for 2.5 seconds" in text
        assert "W" not in twisted_fate.MODULE_CC
        # The module's card order is gold, red, blue.
        assert [_w_parts(card)[0].cc_kind for card in (0, 1, 2)] == [
            "stun",
            "slow",
            "none",
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Twisted Fate") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Twisted Fate")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
