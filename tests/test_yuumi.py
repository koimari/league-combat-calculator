"""Reviewed crowd control for Yuumi (MODULE_CC).

Both damaging slots slow: Prowling Projectile by 20%, Final Chapter's
waves by a stacking 10%.
"""

from src.calculator.champions import get_champion_module_contract, yuumi
from tests import cc_review


class TestReviewedCrowdControl:
    """Yuumi's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yuumi")
        assert yuumi.MODULE_CC == {"Q": "slow", "R": "slow"}
        assert yuumi.parse_abilities.cc_kinds == yuumi.MODULE_CC
        assert "slowed by 20% for 1 second" in cc_review.slot_text(data, "Q")
        assert "slowed by 10% for 1.25 seconds" in cc_review.slot_text(data, "R")

    def test_the_ally_slots_stay_absent(self):
        """W attaches and E shields; neither damages an enemy.

        Coverage is about the row a slot publishes, not about damage: E is
        ``modeled`` on its 165.0 shield to the anchor (test_e8_support.py),
        while W's attachment has no axis at all.
        """
        assert "W" not in yuumi.MODULE_CC and "E" not in yuumi.MODULE_CC
        assert get_champion_module_contract("Yuumi").coverage["W"] == "out_of_scope"
        assert get_champion_module_contract("Yuumi").coverage["E"] == "modeled"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yuumi") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yuumi")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
