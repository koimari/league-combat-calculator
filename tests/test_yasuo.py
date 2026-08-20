"""Reviewed crowd control for Yasuo (MODULE_CC).

Last Breath knocks up; Steel Tempest does so only on the Gathering Storm
cast, so its kind is authored per part rather than per slot.
"""

from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    yasuo,
)
from tests import cc_review, coverage_truth

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


class TestCoverageMap:
    """R prices a row and W prices nothing; the map had both backwards.

    ``b03bbad9`` rewrote the set as ``{P, Q, E}`` while adding P, dropping
    Last Breath from it.  P and W are ``no_damage`` rather than
    ``out_of_scope``: Way of the Wanderer grants the Flow shield and the
    crit conversion the fight engine already applies, and Wind Wall only
    destroys projectiles — neither slot damages anybody.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Yasuo").coverage == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Yasuo") == {
            "P": coverage_truth.ZERO,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ZERO,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_two_no_damage_slots_have_no_cached_damage_row(self):
        kit = cc_review.kit("Yasuo")["abilities"]
        for slot in ("P", "W"):
            attributes = {
                level["attribute"]
                for ability in kit[slot]
                for effect in ability["effects"]
                for level in effect["leveling"] or []
            }
            assert not any("Damage" in name for name in attributes - {"Bonus Damage"})
        # P's one "Bonus Damage" row is the Flow shield, not enemy damage.
        assert "grant himself a shield" in cc_review.slot_text(
            cc_review.kit("Yasuo"), "P"
        )
