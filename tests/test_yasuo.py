"""Reviewed crowd control for Yasuo (MODULE_CC).

Last Breath knocks up; Steel Tempest does so only on the Gathering Storm
cast, so its kind is authored per part rather than per slot.
"""

from src.calculator.champions import parse_champion_abilities, yasuo
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _q_kinds(**options):
    """The kinds Steel Tempest's parts carry for one option state."""
    parsed = parse_champion_abilities(
        cc_review.kit("Yasuo"), 18, 100.0, _RANKS, champion_options=options or None
    )
    return sorted({part.cc_kind for part in parsed["Q"]["parts"]})


class TestReviewedCrowdControl:
    """Yasuo's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yasuo")
        assert yasuo.MODULE_CC == {"E": "none", "R": "knockup"}
        assert yasuo.parse_abilities.cc_kinds == yasuo.MODULE_CC
        assert "knocks up all nearby airborne enemy champions" in cc_review.slot_text(
            data, "R"
        )
        # E's only control word is the knock-down Yasuo himself suffers.
        e_text = cc_review.slot_text(data, "E")
        assert cc_review.control_words(e_text) == ["immobiliz", "knock"]
        assert "yasuo will be knocked down by any immobilizing" in e_text

    def test_steel_tempest_carries_the_branch_it_is_cast_on(self):
        """The whirlwind knocks up; the ordinary thrust does not."""
        data = cc_review.kit("Yasuo")
        assert "Q" not in yasuo.MODULE_CC
        assert "additionally knocks up enemies hit for 0.9 seconds" in (
            cc_review.slot_text(data, "Q")
        )
        assert _q_kinds() == ["none"]
        assert _q_kinds(q_gathering_storm=2) == ["knockup"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yasuo") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yasuo")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
