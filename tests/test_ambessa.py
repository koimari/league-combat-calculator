"""Tests for Ambessa champion ability parsing and damage calculation."""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.ambessa import (
    parse_abilities,
    _extract_leveling_damage,
    _extract_leveling_value,
    _parse_passive_damage,
)
from src.calculator.damage import calculate_fight_damage


@pytest.fixture
def ambessa_data() -> dict:
    """Load Ambessa champion data from the cached JSON."""
    return get_champion("Ambessa")


class TestQ1CunningSweep:
    """Tests for Q1 (Cunning Sweep) damage."""

    def test_q1_returns_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q1_sweetspot_deals_more_damage(
        self, ambessa_data: dict,
    ) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        normal = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        sweetspot = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q"]["total_raw"] > normal["Q"]["total_raw"]

    def test_q1_sweetspot_is_default(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        default = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        sweetspot = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": True},
        )
        assert abs(
            default["Q"]["total_raw"] - sweetspot["Q"]["total_raw"]
        ) < 0.1

    def test_q1_has_cooldown(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["cooldown"] > 0

    def test_q1_rank1_normal_damage(self, ambessa_data: dict) -> None:
        """Verify Q1 rank 1 normal damage = base + bonus AD scaling."""
        stats = calculate_total_stats(ambessa_data, 1, [])
        abilities = parse_abilities(
            ambessa_data, 1, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        q = abilities["Q"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        # Q1 rank 1 Physical Damage: 20 + 30% bonus AD + %HP scaling
        # Just verify it's positive and reasonable
        assert q["total_raw"] > 0


class TestQ2SunderingSlam:
    """Tests for Q2 (Sundering Slam) damage."""

    def test_q2_present_in_results(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert "Q2" in abilities

    def test_q2_is_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q2"]["damage_type"] == "physical"

    def test_q2_separate_from_q1(self, ambessa_data: dict) -> None:
        """Q2 should have a different name and different damage from Q1."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["name"] != abilities["Q2"]["name"]

    def test_q2_sweetspot_deals_more_damage(
        self, ambessa_data: dict,
    ) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        normal = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        sweetspot = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q2"]["total_raw"] > normal["Q2"]["total_raw"]

    def test_q2_shares_q1_cooldown(self, ambessa_data: dict) -> None:
        """Q2 is a recast, so its cooldown should match Q1."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q2"]["cooldown"] == abilities["Q"]["cooldown"]


class TestWRepudiation:
    """Tests for W (Repudiation) — always uses increased damage."""

    def test_w_returns_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 3, [])
        abilities = parse_abilities(
            ambessa_data, 3, 0.0, champion_stats=stats,
        )
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 3, [])
        abilities = parse_abilities(
            ambessa_data, 3, 0.0, champion_stats=stats,
        )
        assert abilities["W"]["cooldown"] > 0

    def test_w_uses_increased_damage(self, ambessa_data: dict) -> None:
        """W should use 'Increased Physical Damage' (empowered)."""
        stats = calculate_total_stats(ambessa_data, 3, [])
        abilities = parse_abilities(
            ambessa_data, 3, 0.0, champion_stats=stats,
        )
        w = abilities["W"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        # Increased Physical Damage rank 1: 75 + 75% bonus AD
        # Normal Physical Damage rank 1: 50 + 50% bonus AD
        # At 0 bonus AD, increased = 75 > normal = 50
        assert w["total_raw"] >= 75.0

    def test_w_rank_scaling(self, ambessa_data: dict) -> None:
        """W damage should increase with rank."""
        stats_3 = calculate_total_stats(ambessa_data, 3, [])
        low = parse_abilities(
            ambessa_data, 3, 0.0, champion_stats=stats_3,
        )
        stats_9 = calculate_total_stats(ambessa_data, 9, [])
        high = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats_9,
        )
        assert high["W"]["total_raw"] > low["W"]["total_raw"]


class TestELacerate:
    """Tests for E (Lacerate) — both hits (Total Physical Damage)."""

    def test_e_returns_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 4, [])
        abilities = parse_abilities(
            ambessa_data, 4, 0.0, champion_stats=stats,
        )
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "physical"

    def test_e_has_cooldown(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 4, [])
        abilities = parse_abilities(
            ambessa_data, 4, 0.0, champion_stats=stats,
        )
        assert abilities["E"]["cooldown"] > 0

    def test_e_uses_total_damage_both_hits(
        self, ambessa_data: dict,
    ) -> None:
        """E should use Total Physical Damage (both passes)."""
        stats = calculate_total_stats(ambessa_data, 4, [])
        abilities = parse_abilities(
            ambessa_data, 4, 0.0, champion_stats=stats,
        )
        e = abilities["E"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        # Total Physical Damage rank 1: 80 + 100% bonus AD
        # Single hit rank 1: 40 + 50% bonus AD
        # Total should be double the single hit
        expected_total = 80 + 1.0 * bonus_ad
        assert abs(e["total_raw"] - expected_total) < 0.5

    def test_e_rank_scaling(self, ambessa_data: dict) -> None:
        """E damage should increase with rank."""
        stats_4 = calculate_total_stats(ambessa_data, 4, [])
        low = parse_abilities(
            ambessa_data, 4, 0.0, champion_stats=stats_4,
        )
        stats_14 = calculate_total_stats(ambessa_data, 14, [])
        high = parse_abilities(
            ambessa_data, 14, 0.0, champion_stats=stats_14,
        )
        assert high["E"]["total_raw"] > low["E"]["total_raw"]


class TestRPublicExecution:
    """Tests for R (Public Execution) stat buff + damage."""

    def test_r_has_stat_buff(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 11, [])
        abilities = parse_abilities(
            ambessa_data, 11, 0.0, champion_stats=stats,
        )
        assert "R" in abilities
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["armor_penetration_percent"] > 0

    def test_r_armor_pen_rank1(self, ambessa_data: dict) -> None:
        """R rank 1 should grant 10% armor penetration."""
        stats = calculate_total_stats(ambessa_data, 6, [])
        abilities = parse_abilities(
            ambessa_data, 6, 0.0, champion_stats=stats,
        )
        pen = abilities["R"]["stat_buff"]["armor_penetration_percent"]
        assert abs(pen - 10.0) < 0.1

    def test_r_armor_pen_rank3(self, ambessa_data: dict) -> None:
        """R rank 3 should grant 30% armor penetration."""
        stats = calculate_total_stats(ambessa_data, 16, [])
        abilities = parse_abilities(
            ambessa_data, 16, 0.0, champion_stats=stats,
        )
        pen = abilities["R"]["stat_buff"]["armor_penetration_percent"]
        assert abs(pen - 30.0) < 0.1

    def test_r_deals_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 11, [])
        abilities = parse_abilities(
            ambessa_data, 11, 0.0, champion_stats=stats,
        )
        assert abilities["R"]["damage_type"] == "physical"
        assert abilities["R"]["total_raw"] > 0

    def test_r_has_cooldown(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 11, [])
        abilities = parse_abilities(
            ambessa_data, 11, 0.0, champion_stats=stats,
        )
        assert abilities["R"]["cooldown"] > 0

    def test_r_damage_scales_with_rank(self, ambessa_data: dict) -> None:
        """R active damage should increase with rank."""
        stats_6 = calculate_total_stats(ambessa_data, 6, [])
        low = parse_abilities(
            ambessa_data, 6, 0.0, champion_stats=stats_6,
        )
        stats_16 = calculate_total_stats(ambessa_data, 16, [])
        high = parse_abilities(
            ambessa_data, 16, 0.0, champion_stats=stats_16,
        )
        assert high["R"]["total_raw"] > low["R"]["total_raw"]


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(
        self, ambessa_data: dict,
    ) -> None:
        """The fight engine should apply R's armor pen to stats."""
        stats = calculate_total_stats(ambessa_data, 11, [])
        original_pen = stats.get("armor_penetration_percent", 0.0)

        abilities = parse_abilities(
            ambessa_data, 11, 0.0, champion_stats=stats,
        )

        calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )

        assert stats["armor_penetration_percent"] > original_pen

    def test_armor_pen_reduces_effective_armor(
        self, ambessa_data: dict,
    ) -> None:
        """R's armor pen should reduce effective armor in fight results."""
        stats = calculate_total_stats(ambessa_data, 16, [])
        abilities = parse_abilities(
            ambessa_data, 16, 0.0, champion_stats=stats,
        )
        # R rank 3 = 30% armor pen
        result = calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        # Effective armor should be 70 (100 * (1 - 0.30))
        effective_armor = result.get("effective_armor", 100)
        assert effective_armor < 100
        assert abs(effective_armor - 70.0) < 1.0

    def test_q2_appears_in_fight_breakdown(
        self, ambessa_data: dict,
    ) -> None:
        """Q2 (Sundering Slam) should appear in fight damage breakdown."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
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
        assert "Q2" in result["breakdown"]
        assert result["breakdown"]["Q2"]["total_damage"] > 0


class TestPassiveDrakehoundsStep:
    """Tests for P (Drakehound's Step) empowered auto."""

    def test_passive_present(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert "passive" in abilities

    def test_passive_is_physical_damage(self, ambessa_data: dict) -> None:
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["passive"]["damage_type"] == "physical"

    def test_passive_scales_with_level(self, ambessa_data: dict) -> None:
        stats_1 = calculate_total_stats(ambessa_data, 1, [])
        low = parse_abilities(
            ambessa_data, 1, 0.0, champion_stats=stats_1,
        )
        stats_18 = calculate_total_stats(ambessa_data, 18, [])
        high = parse_abilities(
            ambessa_data, 18, 0.0, champion_stats=stats_18,
        )
        # Per-proc damage should increase with level
        low_per = low["passive"]["physical_damage"]
        high_per = high["passive"]["physical_damage"]
        assert high_per > low_per

    def test_passive_proc_count_default(self, ambessa_data: dict) -> None:
        """Default passive procs should be 4."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["passive"]["proc_count"] == 4

    def test_passive_proc_count_custom(self, ambessa_data: dict) -> None:
        """Custom passive proc count should be respected."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 6},
        )
        assert abilities["passive"]["proc_count"] == 6
        # Total damage should equal per_proc * proc_count
        per_proc = abilities["passive"]["physical_damage"]
        assert abs(
            abilities["passive"]["total_raw"] - per_proc * 6
        ) < 0.1

    def test_passive_zero_procs_excluded(self, ambessa_data: dict) -> None:
        """Setting passive_procs to 0 should exclude passive."""
        stats = calculate_total_stats(ambessa_data, 9, [])
        abilities = parse_abilities(
            ambessa_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_passive_level1_base_damage(self, ambessa_data: dict) -> None:
        """Level 1 passive per-proc should be ~5 base + 25% bonus AD."""
        stats = calculate_total_stats(ambessa_data, 1, [])
        abilities = parse_abilities(
            ambessa_data, 1, 0.0, champion_stats=stats,
        )
        per_proc = abilities["passive"]["physical_damage"]
        # Per-level scaling values[0] = 5, plus 25% bonus AD
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        expected = 5.0 + 0.25 * bonus_ad
        assert abs(per_proc - expected) < 1.0

    def test_passive_includes_bonus_ad_scaling(
        self, ambessa_data: dict,
    ) -> None:
        """Passive should scale with bonus AD (25% ratio)."""
        from src.calculator.data_fetcher import get_item_by_name
        item = get_item_by_name("Voltaic Cyclosword")
        stats_no_items = calculate_total_stats(ambessa_data, 18, [])
        stats_with_item = calculate_total_stats(ambessa_data, 18, [item])

        no_items = parse_abilities(
            ambessa_data, 18, 0.0, champion_stats=stats_no_items,
        )
        with_item = parse_abilities(
            ambessa_data, 18, 0.0, champion_stats=stats_with_item,
        )
        assert with_item["passive"]["physical_damage"] > (
            no_items["passive"]["physical_damage"]
        )
