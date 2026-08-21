"""Tahm Kench's reviewed crowd control (``MODULE_CC`` plus Q's stack part).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import tahm_kench
from tests import cc_review
from src.calculator.champions.engine import CC_PER_PART


def _q_parts(stacks: int):
    """Tongue Lash's parts at a stack count, through the module."""
    data = cc_review.kit("Tahm Kench")
    results = tahm_kench.parse_abilities(
        data, 18, 0.0, champion_options={"q_passive_stacks": stacks}
    )
    return results["Q"]["parts"]


class TestReviewedCrowdControl:
    """Tahm Kench's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Tahm Kench")
        assert tahm_kench.MODULE_CC == {
            "Q": CC_PER_PART,
            "W": "immobilize",
            "R": "suppression",
        }
        # Abyssal Dive lands two immobilize kinds at once, so the reviewed
        # kind is the un-narrowed one.
        assert "knocking them up and stunning them for 1 second" in (
            cc_review.slot_text(data, "W")
        )
        # Devour "can only be cast on enemies with 3 stacks", whose bonus is
        # the suppression the Regurgitate damage is the end of.
        assert "suppressed during devour's cast time" in cc_review.slot_text(data, "R")

    def test_q_answers_by_stack_count_because_the_cached_text_does(self):
        text = cc_review.slot_text(cc_review.kit("Tahm Kench"), "Q")
        assert "slows them by 50% for 2 seconds" in text
        assert "the target is stunned for 1.5 seconds" in text
        assert tahm_kench.MODULE_CC["Q"] == CC_PER_PART
        assert _q_parts(0)[0].cc_kind == "slow"
        assert _q_parts(3)[0].cc_kind == "stun"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Tahm Kench") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Tahm Kench")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
