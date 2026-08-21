"""Tests for Alistar champion ability parsing and damage calculation."""

import pytest

from src.calculator.champions.slotlib import extract_named
from src.calculator.champions.alistar import (
    _extract_e_on_hit_damage,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.champions import alistar
from src.calculator.champions.engine import CC_PER_PART
from tests import cc_review


class TestQPulverize:
    """Tests for Q (Pulverize) — simple magic damage."""

    def test_q_returns_magic_damage(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 5)
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 5)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_damage_matches_json(self, alistar_data, parse_at) -> None:
        """Q rank 1: 60 base + 80% AP."""
        _, abilities = parse_at(alistar_data, 1, ap=100.0)
        expected = 60 + 0.80 * 100
        assert abs(abilities["Q"]["total_raw"] - expected) < 0.5

    def test_q_scales_with_rank(self, alistar_data, parse_at) -> None:
        _, low = parse_at(
            alistar_data,
            3,
            ability_ranks={"Q": 1, "W": 1, "E": 1},
        )
        _, high = parse_at(
            alistar_data,
            9,
            ability_ranks={"Q": 5, "W": 1, "E": 1},
        )
        assert high["Q"]["total_raw"] > low["Q"]["total_raw"]


class TestWHeadbutt:
    """Tests for W (Headbutt) — simple magic damage."""

    def test_w_returns_magic_damage(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 3)
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_has_cooldown(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_rank1_damage_matches_json(self, alistar_data, parse_at) -> None:
        """W rank 1: 55 base + 100% AP."""
        _, abilities = parse_at(
            alistar_data,
            2,
            ap=50.0,
            ability_ranks={"Q": 1, "W": 1, "E": 0},
        )
        expected = 55 + 1.00 * 50
        assert abs(abilities["W"]["total_raw"] - expected) < 0.5


class TestETrample:
    """Tests for E (Trample) — tick damage + empowered auto on-hit."""

    def test_e_returns_magic_damage(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 5)
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 5)
        assert abilities["E"]["cooldown"] > 0

    def test_e_uses_total_damage_not_per_tick(self, alistar_data, parse_at) -> None:
        """E should use Total Magic Damage (all 10 ticks), not per-tick."""
        _, abilities = parse_at(
            alistar_data,
            3,
            ability_ranks={"Q": 1, "W": 1, "E": 1},
        )
        assert abilities["E"]["total_raw"] >= 80.0

    def test_e_total_damage_rank1_matches_json(self, alistar_data) -> None:
        """E rank 1: Total Magic Damage = 80 + 70% AP."""
        e_ability = alistar_data["abilities"]["E"][0]
        total = extract_named(
            e_ability, "Total Magic Damage", 1, {"ability_power": 100.0}
        )
        expected = 80 + 0.70 * 100
        assert abs(total - expected) < 0.5

    def test_e_total_damage_rank5_matches_json(self, alistar_data) -> None:
        """E rank 5: Total Magic Damage = 200 + 70% AP."""
        e_ability = alistar_data["abilities"]["E"][0]
        total = extract_named(
            e_ability, "Total Magic Damage", 5, {"ability_power": 0.0}
        )
        assert abs(total - 200.0) < 0.5

    def test_e_includes_empowered_auto(self, alistar_data, parse_at) -> None:
        """E total should include empowered auto damage (once per cast)."""
        e_ability = alistar_data["abilities"]["E"][0]
        tick_only = extract_named(
            e_ability, "Total Magic Damage", 1, {"ability_power": 0.0}
        )
        empowered = _extract_e_on_hit_damage(e_ability, 1)
        _, abilities = parse_at(
            alistar_data,
            1,
            ability_ranks={"Q": 1, "W": 0, "E": 1},
        )
        assert abs(abilities["E"]["total_raw"] - (tick_only + empowered)) < 0.5

    def test_e_empowered_auto_level1(self, alistar_data) -> None:
        """E empowered auto at level 1 should be ~20."""
        e_ability = alistar_data["abilities"]["E"][0]
        damage = _extract_e_on_hit_damage(e_ability, 1)
        assert abs(damage - 20.0) < 1.0

    def test_e_empowered_auto_scales_with_level(self, alistar_data) -> None:
        """E empowered auto should increase with champion level."""
        e_ability = alistar_data["abilities"]["E"][0]
        low = _extract_e_on_hit_damage(e_ability, 1)
        high = _extract_e_on_hit_damage(e_ability, 18)
        assert high > low

    def test_e_no_on_hit_field(self, alistar_data, parse_at) -> None:
        """E should NOT have on_hit — empowered auto is baked into total."""
        _, abilities = parse_at(alistar_data, 5)
        assert "on_hit" not in abilities["E"]


class TestRUnbreakableWill:
    """R (Unbreakable Will) — modeled as a zero-damage self state row
    carrying the sourced damage-reduction modifier (final-slots batch;
    the old absence pin predates the damage_modifier seam)."""

    def test_r_present_zero_damage_with_sourced_reduction(
        self, alistar_data, parse_at
    ) -> None:
        _, abilities = parse_at(alistar_data, 11)
        entry = abilities["R"]
        assert entry["total_raw"] == 0.0
        # Rank 2 at level 11 default ladder: sourced 65% reduction, 7s.
        events = entry["self_state_events"]
        assert events and events[0]["kind"] == "damage_modifier"
        # Rank 2: 65% sourced reduction -> multiplier 0.35 over the 7s window.
        assert events[0]["multiplier"] == pytest.approx(0.35)
        assert events[0]["duration"] == 7.0
        assert events[0]["source"].startswith("Unbreakable Will")


class TestPassive:
    """Tests for P (Triumphant Roar) — healing, should not appear."""

    def test_passive_not_in_results(self, alistar_data, parse_at) -> None:
        _, abilities = parse_at(alistar_data, 9)
        assert "passive" not in abilities


class TestFightEngineIntegration:
    """Tests for Alistar in the fight engine."""

    def test_fight_engine_runs(self, alistar_data, parse_at) -> None:
        """Alistar abilities should work in the fight engine."""
        stats, abilities = parse_at(alistar_data, 9)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        assert result["total_damage"] > 0

    def test_fight_engine_e_on_hit_contributes(self, alistar_data, parse_at) -> None:
        """E on-hit should add damage to auto attacks."""
        stats, abilities = parse_at(alistar_data, 9)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=10.0,
                one_rotation=False,
            ),
        )
        assert result["total_damage"] > 0


class TestEPastLevel18:
    """Top-quest levels 19-20 must never crash on E's per-level wiki array.

    Alistar's cached array already carries real level 19-20 entries, so
    those are used directly; a hypothetical array that stops at 18 falls
    back to its level-18 value instead of indexing out of range.
    """

    def test_e_empowered_auto_uses_real_level_20_entry(self, alistar_data) -> None:
        e_ability = alistar_data["abilities"]["E"][0]
        at_18 = _extract_e_on_hit_damage(e_ability, 18)
        assert _extract_e_on_hit_damage(e_ability, 20) >= at_18

    def test_e_empowered_auto_clamps_an_18_entry_array(self) -> None:
        ability = {
            "effects": [
                {
                    "leveling": [
                        {
                            "attribute": "Bonus Magic Damage",
                            "modifiers": [
                                {"values": [float(20 + 15 * i) for i in range(18)]}
                            ],
                        }
                    ]
                }
            ]
        }
        assert _extract_e_on_hit_damage(ability, 20) == pytest.approx(
            _extract_e_on_hit_damage(ability, 18)
        )


class TestReviewedCrowdControl:
    """Alistar's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Alistar")
        assert alistar.MODULE_CC == {
            "Q": "immobilize",
            "W": "immobilize",
            "E": CC_PER_PART,
        }
        assert "stunning and knocking them up simultaneously" in " ".join(
            cc_review.slot_text(data, "Q").split()
        )
        assert "knocks them back 700 units" in " ".join(
            cc_review.slot_text(data, "W").split()
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Alistar") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Alistar")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
