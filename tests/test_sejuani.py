"""Tests for the Sejuani champion module."""

from src.calculator.champions import parse_champion_abilities, sejuani
from src.calculator.data_fetcher import get_champion
from tests import cc_review


class TestReviewedCrowdControl:
    """Sejuani's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sejuani")
        assert sejuani.MODULE_CC == {"Q": "knockup", "E": "immobilize", "R": "stun"}
        assert "knocking them up for 0.5 seconds" in cc_review.slot_text(data, "Q")
        # E applies two immobilize kinds in one cast.
        assert "displaces slightly, and stuns them for 1 second" in cc_review.slot_text(
            data, "E"
        )
        # R's frost storm slows the enemies around the detonation, but the
        # cached text says the bola's own target is exempt.
        r_text = cc_review.slot_text(data, "R")
        assert "dealing magic damage and stunning them for 1 second" in r_text
        assert "the enemy hit by the bola is unaffected by the storm" in r_text
        # P is absent: Icebreaker's bonus rides Sejuani's next attack or
        # ability rather than emitting an ability event of its own.
        assert "P" not in sejuani.MODULE_CC

    def test_w_answers_per_swing_because_the_two_swings_differ(self):
        w_text = cc_review.slot_text(cc_review.kit("Sejuani"), "W")
        assert "knocks back minions and monsters hit" in w_text
        assert "slowing them by 75% for 0.25 seconds" in w_text
        assert "W" not in sejuani.MODULE_CC
        abilities = parse_champion_abilities(
            get_champion("Sejuani"), 18, 0.0, ability_ranks={"W": 5}
        )
        assert [part.cc_kind for part in abilities["W"]["parts"]] == ["none", "slow"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sejuani") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sejuani")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
