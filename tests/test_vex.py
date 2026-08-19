"""Reviewed crowd control for Vex — and the slots that still withhold.

Doom empowers "her next basic ability", so Q, W and E have no slot-wide
answer and this kit stays coarse.
"""

from src.calculator.champions import vex
from tests import cc_review


class TestReviewedCrowdControl:
    """Vex's crowd-control review, and the slots that still withhold.

    Doom's fear is stack state, not slot state: it empowers "her next basic
    ability", and against Looming Darkness it replaces E's own slow with a
    flee, so neither a slot-wide immobilize nor a slot-wide "none" is true
    of Mistral Bolt, Personal Space or Looming Darkness.
    """

    def test_the_kit_declares_nothing_because_doom_is_state(self):
        data = cc_review.kit("Vex")
        assert not hasattr(vex, "MODULE_CC")
        passive = cc_review.slot_text(data, "P")
        assert "empowers her next basic ability to knock down and fear" in passive
        assert "flee from the epicenter instead" in passive

    def test_looming_darkness_slow_is_the_one_the_flee_overrides(self):
        data = cc_review.kit("Vex")
        assert "slowing them for 2 seconds" in cc_review.slot_text(data, "E")

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Vex") == ["E", "Q", "R", "W"]
        coverage = cc_review.fimbulwinter_coverage("Vex")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
