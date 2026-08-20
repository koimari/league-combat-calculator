"""Reviewed crowd control for Warwick (MODULE_CC), and his two riders.

Infinite Duress suppresses for the whole channel it damages through;
Jaws of the Beast only bites.

Eternal Hunger and Blood Hunt priced nothing before the coverage-frontier
campaign: five autos were 270.0 physical and 0.0 magic.  The rider tests
below hold both to the cached rows they read.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, warwick
from tests import cc_review, rider_probe, row_review


def _cached_leveling(slot, attribute):
    """One cached leveling row's first modifier values, straight from JSON."""
    for ability in cc_review.kit("Warwick")["abilities"][slot]:
        for effect in ability.get("effects") or []:
            for leveling in effect.get("leveling") or []:
                if leveling.get("attribute") == attribute:
                    return leveling["modifiers"][0]["values"]
    raise AssertionError(f"Warwick {slot} has no {attribute!r} row")


class TestReviewedCrowdControl:
    """Warwick's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Warwick")
        assert warwick.MODULE_CC == {"Q": "none", "R": "suppression"}
        assert warwick.parse_abilities.cc_kinds == warwick.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        r_text = cc_review.slot_text(data, "R")
        assert "channels for up to 1.5 seconds to suppress" in r_text
        assert "he then knocks them down" in r_text

    def test_the_out_of_scope_slots_stay_absent(self):
        """E holds the fear and the 90% slow, but prices no damage."""
        data = cc_review.kit("Warwick")
        assert "W" not in warwick.MODULE_CC and "E" not in warwick.MODULE_CC
        assert get_champion_module_contract("Warwick").coverage["E"] == "out_of_scope"
        assert "fearing nearby enemies for 1 second" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Warwick") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Warwick")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestEternalHunger:
    """P: the on-hit rider, and the heal its low-health tiers pay."""

    def test_the_per_hit_damage_is_the_cached_per_level_row(self):
        """55 at level 18, + 15% of 100 bonus AD + 10% of 200 AP = 90.0."""
        assert _cached_leveling("P", "Per-Level Scaling")[17] == 55
        on_hit = row_review.entry("Warwick", "passive")["on_hit"]
        assert on_hit["damage_type"] == "magic"
        assert on_hit["damage_per_hit"] == pytest.approx(55 + 15 + 20)

    def test_the_rider_reaches_the_fight_total(self):
        """9 autos carry 27.5 post-mitigation magic each — 247.5."""
        result = rider_probe.fight("Warwick")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Eternal Hunger (on-hit)"
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"] == 9
        assert row["total_damage"] == pytest.approx(247.5, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_a_healthy_warwick_heals_nothing_from_it(self):
        """The heal needs him below 50% maximum health; the default is 100."""
        result = rider_probe.fight("Warwick")
        assert row_review.entry("Warwick", "passive")["self_heal_share_of_damage"] == 0
        assert rider_probe.healing_from(result, "Eternal Hunger") == 0.0

    def test_below_half_health_it_heals_its_whole_post_mitigation_damage(self):
        result = rider_probe.fight(
            "Warwick", champion_options={"p_self_health_percent": 40}
        )
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert rider_probe.healing_from(result, "Eternal Hunger") == pytest.approx(
            row["total_damage"], abs=0.05
        )

    def test_below_a_quarter_health_the_heal_is_two_and_a_half_times_it(self):
        result = rider_probe.fight(
            "Warwick", champion_options={"p_self_health_percent": 20}
        )
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert rider_probe.healing_from(result, "Eternal Hunger") == pytest.approx(
            2.5 * row["total_damage"], abs=0.5
        )


class TestBloodHunt:
    """W: the attack-speed steroid, base and doubled."""

    def test_the_base_tier_is_the_cached_bonus_attack_speed_row(self):
        assert _cached_leveling("W", "Bonus Attack Speed") == [70, 80, 90, 100, 110]
        entry = row_review.entry("Warwick", "W")
        assert entry["stat_buff"] == {"bonus_attack_speed": 110.0}
        assert entry["total_raw"] == 0.0

    def test_a_target_below_a_quarter_health_doubles_it(self):
        """More than 75% missing is below 25% maximum health."""
        assert _cached_leveling("W", "Increased Attack Speed") == [
            140,
            160,
            180,
            200,
            220,
        ]
        entry = row_review.entry("Warwick", "W", target_missing_hp_pct=80)
        assert entry["stat_buff"] == {"bonus_attack_speed": 220.0}

    def test_the_steroid_buys_autos_in_the_fight(self):
        """9 autos at the base tier, 14 at the doubled one."""
        base = rider_probe.fight("Warwick")
        doubled = rider_probe.fight(
            "Warwick", champion_options={"target_missing_hp_pct": 80}
        )
        assert base["breakdown"]["auto_attacks"]["count"] == 9
        assert doubled["breakdown"]["auto_attacks"]["count"] == 14
        assert doubled["total_damage"] > base["total_damage"]


class TestTheSlotThatStaysOutOfScope:
    """E (Primal Howl) reduces damage TAKEN — an axis the engine lacks."""

    def test_the_module_names_the_missing_axis(self):
        assert get_champion_module_contract("Warwick").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "out_of_scope",
            "R": "modeled",
        }
        assert "damage *taken*" in warwick.__doc__
        assert "Damage Reduction" in warwick.__doc__
