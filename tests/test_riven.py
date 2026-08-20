"""Tests for the Riven champion module."""

from src.calculator.champions import riven
from tests import cc_review


class TestReviewedCrowdControl:
    """Riven's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Riven")
        assert riven.MODULE_CC == {"Q": "none", "W": "stun", "R": "none"}
        # Q prices one slash of Broken Wings; only the third cast adds a
        # knock back, and this module does not price that specific one.
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing physical damage to enemies struck within an area" in q_text
        assert "knocking back enemies hit 75 units" in q_text
        assert riven.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            45.0,
            75.0,
            105.0,
            135.0,
            165.0,
        ]
        assert "stunning them for 0.75 seconds" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # E deals no damage, P rides the auto stream on-hit, and R_buff is
        # the AD steroid's zero-damage row.
        for slot in ("E", "P", "R_buff"):
            assert slot not in riven.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Riven") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Riven")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
