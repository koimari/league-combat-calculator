"""Tests for the Nunu & Willump champion module."""

from src.calculator.champions import nunu_willump
from tests import cc_review


class TestReviewedCrowdControl:
    """Nunu & Willump's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nunu & Willump")
        assert nunu_willump.MODULE_CC == {
            "Q": "none",
            "W": "immobilize",
            "E": "slow",
            "R": "slow",
        }
        # Q's devour stun-and-pull is gated on killing a minion or a
        # small/medium monster; against the fight's champion target it
        # "deals magic damage and the heal is reduced to 60%".
        q_text = cc_review.slot_text(data, "Q")
        assert "if consume would kill the target minion" in q_text
        assert "against champions, he deals magic damage" in q_text
        # W applies two immobilize kinds in one cast, which is what the
        # un-narrowed "immobilize" states.
        assert "knocking them up for 0.5 : 0.75" in cc_review.slot_text(data, "W")
        assert "subsequently stunning them" in cc_review.slot_text(data, "W")
        assert "enemies hit 3 times are slowed for 1 second" in cc_review.slot_text(
            data, "E"
        )
        assert "will remain slowed" in cc_review.slot_text(data, "R")
        # P is absent: Call of the Freljord is an attack-speed buff with no
        # damage row of its own.
        assert "P" not in nunu_willump.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Nunu & Willump") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Nunu & Willump")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
