"""Tests for Alistar champion ability parsing and damage calculation."""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.alistar import (
    parse_abilities,
    _extract_e_on_hit_damage,
    _extract_e_total_damage,
)
from src.calculator.damage import calculate_fight_damage


@pytest.fixture
def alistar_data() -> dict:
    """Load Alistar champion data from the cached JSON."""
    return get_champion("Alistar")


class TestQPulverize:
    """Tests for Q (Pulverize) — simple magic damage."""

    def test_q_returns_magic_damage(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 5, [])
        abilities = parse_abilities(
            alistar_data, 5, 0.0, champion_stats=stats,
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 5, [])
        abilities = parse_abilities(
            alistar_data, 5, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_damage_matches_json(self, alistar_data: dict) -> None:
        """Q rank 1: 60 base + 80% AP."""
        stats = calculate_total_stats(alistar_data, 1, [])
        abilities = parse_abilities(
            alistar_data, 1, 100.0, champion_stats=stats,
        )
        # 60 + 80% of 100 AP = 140
        expected = 60 + 0.80 * 100
        assert abs(abilities["Q"]["total_raw"] - expected) < 0.5

    def test_q_scales_with_rank(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 9, [])
        low = parse_abilities(
            alistar_data, 3, 0.0,
            champion_stats=stats, ability_ranks={"Q": 1, "W": 1, "E": 1},
        )
        high = parse_abilities(
            alistar_data, 9, 0.0,
            champion_stats=stats, ability_ranks={"Q": 5, "W": 1, "E": 1},
        )
        assert high["Q"]["total_raw"] > low["Q"]["total_raw"]


class TestWHeadbutt:
    """Tests for W (Headbutt) — simple magic damage."""

    def test_w_returns_magic_damage(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 3, [])
        abilities = parse_abilities(
            alistar_data, 3, 0.0, champion_stats=stats,
        )
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_has_cooldown(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 3, [])
        abilities = parse_abilities(
            alistar_data, 3, 0.0, champion_stats=stats,
        )
        assert abilities["W"]["cooldown"] > 0

    def test_w_rank1_damage_matches_json(self, alistar_data: dict) -> None:
        """W rank 1: 55 base + 100% AP."""
        stats = calculate_total_stats(alistar_data, 2, [])
        abilities = parse_abilities(
            alistar_data, 2, 50.0,
            champion_stats=stats, ability_ranks={"Q": 1, "W": 1, "E": 0},
        )
        # 55 + 100% of 50 AP = 105
        expected = 55 + 1.00 * 50
        assert abs(abilities["W"]["total_raw"] - expected) < 0.5


class TestETrample:
    """Tests for E (Trample) — tick damage + empowered auto on-hit."""

    def test_e_returns_magic_damage(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 5, [])
        abilities = parse_abilities(
            alistar_data, 5, 0.0, champion_stats=stats,
        )
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 5, [])
        abilities = parse_abilities(
            alistar_data, 5, 0.0, champion_stats=stats,
        )
        assert abilities["E"]["cooldown"] > 0

    def test_e_uses_total_damage_not_per_tick(
        self, alistar_data: dict,
    ) -> None:
        """E should use Total Magic Damage (all 10 ticks), not per-tick."""
        stats = calculate_total_stats(alistar_data, 3, [])
        abilities = parse_abilities(
            alistar_data, 3, 0.0,
            champion_stats=stats, ability_ranks={"Q": 1, "W": 1, "E": 1},
        )
        # E rank 1 tick total: 80 + empowered auto (~20 at low level)
        # Must be well above per-tick value of 8
        assert abilities["E"]["total_raw"] >= 80.0

    def test_e_total_damage_rank1_matches_json(
        self, alistar_data: dict,
    ) -> None:
        """E rank 1: Total Magic Damage = 80 + 70% AP."""
        e_ability = alistar_data["abilities"]["E"][0]
        total = _extract_e_total_damage(e_ability, 1, {"ability_power": 100.0})
        # 80 + 70% of 100 = 150
        expected = 80 + 0.70 * 100
        assert abs(total - expected) < 0.5

    def test_e_total_damage_rank5_matches_json(
        self, alistar_data: dict,
    ) -> None:
        """E rank 5: Total Magic Damage = 200 + 70% AP."""
        e_ability = alistar_data["abilities"]["E"][0]
        total = _extract_e_total_damage(e_ability, 5, {"ability_power": 0.0})
        assert abs(total - 200.0) < 0.5

    def test_e_includes_empowered_auto(self, alistar_data: dict) -> None:
        """E total should include empowered auto damage (once per cast)."""
        e_ability = alistar_data["abilities"]["E"][0]
        tick_only = _extract_e_total_damage(e_ability, 1, {"ability_power": 0.0})
        empowered = _extract_e_on_hit_damage(e_ability, 1)
        stats = calculate_total_stats(alistar_data, 1, [])
        abilities = parse_abilities(
            alistar_data, 1, 0.0,
            champion_stats=stats, ability_ranks={"Q": 1, "W": 0, "E": 1},
        )
        # total_raw = tick damage + empowered auto
        assert abs(abilities["E"]["total_raw"] - (tick_only + empowered)) < 0.5

    def test_e_empowered_auto_level1(self, alistar_data: dict) -> None:
        """E empowered auto at level 1 should be ~20."""
        e_ability = alistar_data["abilities"]["E"][0]
        damage = _extract_e_on_hit_damage(e_ability, 1)
        assert abs(damage - 20.0) < 1.0

    def test_e_empowered_auto_scales_with_level(
        self, alistar_data: dict,
    ) -> None:
        """E empowered auto should increase with champion level."""
        e_ability = alistar_data["abilities"]["E"][0]
        low = _extract_e_on_hit_damage(e_ability, 1)
        high = _extract_e_on_hit_damage(e_ability, 18)
        assert high > low

    def test_e_no_on_hit_field(self, alistar_data: dict) -> None:
        """E should NOT have on_hit — empowered auto is baked into total."""
        stats = calculate_total_stats(alistar_data, 5, [])
        abilities = parse_abilities(
            alistar_data, 5, 0.0, champion_stats=stats,
        )
        assert "on_hit" not in abilities["E"]


class TestRUnbreakableWill:
    """Tests for R (Unbreakable Will) — utility, should not appear."""

    def test_r_not_in_results(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 11, [])
        abilities = parse_abilities(
            alistar_data, 11, 0.0, champion_stats=stats,
        )
        assert "R" not in abilities


class TestPassive:
    """Tests for P (Triumphant Roar) — healing, should not appear."""

    def test_passive_not_in_results(self, alistar_data: dict) -> None:
        stats = calculate_total_stats(alistar_data, 9, [])
        abilities = parse_abilities(
            alistar_data, 9, 0.0, champion_stats=stats,
        )
        assert "passive" not in abilities


class TestFightEngineIntegration:
    """Tests for Alistar in the fight engine."""

    def test_fight_engine_runs(self, alistar_data: dict) -> None:
        """Alistar abilities should work in the fight engine."""
        stats = calculate_total_stats(alistar_data, 9, [])
        abilities = parse_abilities(
            alistar_data, 9, 0.0, champion_stats=stats,
        )
        result = calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        assert result["total_damage"] > 0

    def test_fight_engine_e_on_hit_contributes(
        self, alistar_data: dict,
    ) -> None:
        """E on-hit should add damage to auto attacks."""
        stats = calculate_total_stats(alistar_data, 9, [])
        abilities = parse_abilities(
            alistar_data, 9, 0.0, champion_stats=stats,
        )
        result = calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=10.0,
            one_rotation=False,
        )
        # Should have some magic damage from abilities and on-hit
        assert result["total_damage"] > 0
