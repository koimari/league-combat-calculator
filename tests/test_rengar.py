"""Tests for the Rengar champion module."""

from src.calculator.champions import parse_champion_abilities, rengar
from src.calculator.data_fetcher import get_champion
from tests import cc_review


def _e_part(ferocity):
    """The E part set the fight prices at this Ferocity.

    Bola Strike carries BOTH answers on one entry — ``parts`` is the base
    bola that slows, ``ferocity_parts`` the empowered one that roots — and
    ``damage.py`` prices the second set once the cast consumes the 4-stack
    cap.  Reading whichever set that cast spends is what makes the control
    answer per-branch rather than per-slot.
    """
    abilities = parse_champion_abilities(
        get_champion("Rengar"),
        18,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"p_ferocity": ferocity},
    )
    key = "ferocity_parts" if ferocity >= 4 else "parts"
    (part,) = abilities["E"][key]
    return part


class TestReviewedCrowdControl:
    """Rengar's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rengar")
        assert rengar.MODULE_CC == {"Q": "none", "W": "none"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # R's damage row is the empowered attack's armour-reduction rider
        # and P is the Ferocity state row, so neither carries an event.
        assert "R" not in rengar.MODULE_CC
        assert "P" not in rengar.MODULE_CC

    def test_e_answers_per_ferocity_branch_because_the_bonus_changes_it(self):
        e_text = cc_review.slot_text(cc_review.kit("Rengar"), "E")
        assert "slows them for 1.75 seconds" in e_text
        assert "the target is rooted instead of slowed" in e_text
        assert "E" not in rengar.MODULE_CC
        assert _e_part(0).cc_kind == "slow"
        assert _e_part(4).cc_kind == "root"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Rengar") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Rengar")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
