"""Reviewed crowd control for Zilean (MODULE_CC).

A lone Time Bomb only explodes; the kit's stun needs a second bomb inside
the first one's fuse.
"""

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    zilean,
)
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.stats import calculate_total_stats
from tests import cc_review


class TestReviewedCrowdControl:
    """Zilean's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Zilean")
        # Q's kind depends on the second-bomb state, so it is authored PER
        # PART by ``_time_bomb`` rather than declared per slot; the module
        # therefore declares no slot kind of its own.
        assert zilean.MODULE_CC == {}
        assert zilean.parse_abilities.cc_kinds == zilean.MODULE_CC
        lone = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        assert [part.cc_kind for part in lone["Q"]["parts"]] == ["none"]
        detonated = parse_champion_abilities(
            data,
            18,
            100.0,
            {"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_options={"q_second_bomb": True},
        )
        assert [part.cc_kind for part in detonated["Q"]["parts"]] == ["stun"]
        q_text = cc_review.slot_text(data, "Q")
        assert "the bomb explodes to deal magic damage to nearby enemies" in q_text
        # The only control word is the double-bomb detonation, which needs
        # a second bomb on the same unit inside the first one's fuse.
        assert cc_review.control_words(q_text) == ["stun"]
        assert "if another bomb attaches itself to the same unit, stunning" in q_text

    def test_time_bomb_damage_rides_its_sourced_fuse(self):
        data = cc_review.kit("Zilean")
        assert zilean._Q_FUSE_SECONDS == 3.0
        assert "after 3 seconds" in cc_review.slot_text(data, "Q")
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["Q"]["parts"]
        assert part.time_offset == 3.0

    def test_the_damageless_slots_stay_absent_from_the_review(self):
        """E holds the enemy slow, but Time Warp deals no damage.

        MERGE: a slot that emits a declared zero-damage row is
        ``no_damage``, not ``out_of_scope`` -- "we looked and it prices
        nothing" is a different answer from "nothing looked".  Either way
        it authors no damage event, so it carries no reviewable control.
        """
        data = cc_review.kit("Zilean")
        coverage = get_champion_module_contract("Zilean").coverage
        for slot in ("W", "E"):
            assert slot not in zilean.MODULE_CC, slot
            assert coverage[slot] == "no_damage", slot
        assert "if the target is an enemy, they are slowed" in (
            cc_review.slot_text(data, "E")
        )

    def test_r_is_modeled_as_the_1100_chronoshift_revive(self):
        """R prices no damage row, so its coverage rests on the revive.

        Rank 3 with no ability power is the cached Heal row's 1100.0, which
        ``resolve_starting_defenses`` hands the engine as Chronoshift — the
        receipt behind R's ``modeled`` label.
        """
        contract = get_champion_module_contract("Zilean")
        assert contract.coverage["R"] == "modeled"
        assert contract.coverage_channels["R"] == ("starting_revive_defense",)
        assert "R" not in zilean.MODULE_CC

        stats = calculate_total_stats(cc_review.kit("Zilean"), 18, [])
        defenses = resolve_starting_defenses("Zilean", 18, stats, [])
        assert defenses.revive_source == "Chronoshift"
        assert defenses.revive_health_amount == pytest.approx(1100.0)

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Zilean") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Zilean")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
