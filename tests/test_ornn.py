"""Tests for the Ornn champion module."""

from src.calculator.champions import ornn, parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from tests import cc_review


class TestReviewedCrowdControl:
    """Ornn's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ornn")
        assert ornn.MODULE_CC == {"Q": "slow", "W": "none", "E": "none"}
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # E's priced row is the charge's pass-through damage; the knock-up
        # and stun belong to the terrain-collision shockwave, whose own
        # damage lands only on enemies the charge did not already hit.
        e_text = cc_review.slot_text(data, "E")
        assert "if ornn collides with terrain during the charge" in e_text
        assert "deals the same damage if they were not already hit" in e_text

    def test_r_answers_per_pass_because_the_two_passes_differ(self):
        data = cc_review.kit("Ornn")
        r_text = cc_review.slot_text(data, "R")
        assert "slows them for 2 seconds" in r_text
        assert "knocks them up and stuns them for 1 second" in r_text
        assert "R" not in ornn.MODULE_CC
        abilities = parse_champion_abilities(
            get_champion("Ornn"), 18, 0.0, ability_ranks={"R": 3}
        )
        assert [part.cc_kind for part in abilities["R"]["parts"]] == [
            "slow",
            "immobilize",
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Ornn") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Ornn")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
