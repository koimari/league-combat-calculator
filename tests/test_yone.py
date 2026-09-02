"""Reviewed crowd control for Yone (MODULE_CC) — and the slot that still
withholds.

Fate Sealed pulls; Mortal Steel knocks up only on the Gathering Storm
cast.  Soul Unbound's true-damage recast is built by the fight engine
rather than by a part, so this kit stays coarse.
"""

from src.calculator.champions import parse_champion_abilities, yone
from src.calculator.champions.engine import CC_PER_PART
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _q_parts(**options):
    """Mortal Steel's parts for one option state."""
    parsed = parse_champion_abilities(
        cc_review.kit("Yone"), 18, 100.0, _RANKS, champion_options=options or None
    )
    return parsed["Q"]["parts"]


class TestReviewedCrowdControl:
    """Yone's reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yone")
        assert yone.MODULE_CC == {"Q": CC_PER_PART, "W": "none", "R": "pull"}
        assert yone.parse_abilities.cc_kinds == yone.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        r_text = cc_review.slot_text(data, "R")
        assert "pulls them towards the location yone blinked to" in r_text
        assert "the stun ends prematurely upon the pull" in r_text

    def test_fate_sealed_damage_rides_the_gust_not_the_mark(self):
        assert yone._R_GUST_DELAY_SECONDS == 0.3
        assert "after 0.3 seconds, a gust rushes" in cc_review.slot_text(
            cc_review.kit("Yone"), "R"
        )

    def test_mortal_steel_carries_the_branch_it_is_cast_on(self):
        """The whirlwind knocks up; the ordinary thrust does not.

        Yasuo's shape exactly (see ``tests/test_yasuo.py``): one thrust is
        one landing, so the branch's kind rides the flat part that carries
        the cast instant, and the crit-eligible AD part books no event and
        states no kind.  ``"none"`` is ``MODULE_CC``'s reviewed absence.
        """
        data = cc_review.kit("Yone")
        assert yone.MODULE_CC["Q"] == CC_PER_PART
        assert "knocking up enemies hit in their path" in cc_review.slot_text(data, "Q")
        thrust = _q_parts()
        assert [part.cc_kind for part in thrust] == ["none", None]
        assert thrust[0].cc_duration == 0.0
        whirlwind = _q_parts(q_gathering_storm=2)
        assert [part.cc_kind for part in whirlwind] == ["knockup", None]
        assert whirlwind[0].cc_duration == 0.75
        assert [part.amount for part in thrust] == [part.amount for part in whirlwind]

    def test_soul_unbound_withholds_on_its_engine_authored_event(self):
        """E emits a true-damage event with no module part to mark."""
        parsed = parse_champion_abilities(cc_review.kit("Yone"), 18, 100.0, _RANKS)
        assert "E" not in yone.MODULE_CC
        assert parsed["E"]["parts"] == ()
        assert parsed["E"]["stored_damage"]["duration"] == yone._E_SPIRIT_FORM_SECONDS

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Yone") == ["E"]
        coverage = cc_review.fimbulwinter_coverage("Yone")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
