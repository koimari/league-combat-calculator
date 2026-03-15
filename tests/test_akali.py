"""Tests for Akali champion ability parsing and damage calculation."""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.akali import (
    parse_abilities,
    _parse_passive_damage,
    _extract_leveling_damage,
)
from src.calculator.damage import calculate_fight_damage


@pytest.fixture
def akali_data() -> dict:
    """Load Akali champion data from the cached JSON."""
    return get_champion("Akali")


class TestQFivePointStrike:
    """Tests for Q (Five Point Strike) — standard magic damage."""

    def test_q_is_magic_damage(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_base_plus_scaling(self, akali_data: dict) -> None:
        """Q rank 1: 45 + 65% AD + 60% AP."""
        stats = calculate_total_stats(akali_data, 1, [])
        abilities = parse_abilities(
            akali_data, 1, 0.0, champion_stats=stats,
        )
        q = abilities["Q"]
        ad = stats["attack_damage"]
        # 45 flat + 65% AD + 60% of 0 AP
        expected = 45 + 0.65 * ad
        assert abs(q["total_raw"] - expected) < 0.5


class TestWTwilightShroud:
    """Tests for W (Twilight Shroud) — no damage, should be skipped."""

    def test_w_not_in_results(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0, champion_stats=stats,
        )
        assert "W" not in abilities


class TestEShurikenFlip:
    """Tests for E (Shuriken Flip) — both hits combined."""

    def test_e_is_magic_damage(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0, champion_stats=stats,
        )
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_uses_total_damage(self, akali_data: dict) -> None:
        """E should use Total Magic Damage (shuriken + dash), not single hit."""
        stats = calculate_total_stats(akali_data, 3, [])
        abilities = parse_abilities(
            akali_data, 3, 0.0, champion_stats=stats,
        )
        e = abilities["E"]
        ad = stats["attack_damage"]
        # E rank 1 Total: 70 + 100% AD + 110% AP (AP=0)
        expected_total = 70 + 1.0 * ad
        # Single hit would be: 21 + 30% AD + 33% AP
        single_hit = 21 + 0.30 * ad
        assert abs(e["total_raw"] - expected_total) < 0.5
        assert e["total_raw"] > single_hit * 2

    def test_e_has_cooldown(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 3, [])
        abilities = parse_abilities(
            akali_data, 3, 0.0, champion_stats=stats,
        )
        assert abilities["E"]["cooldown"] > 0


class TestRPerfectExecution:
    """Tests for R (Perfect Execution) — R1 + R2 minimum combined."""

    def test_r_is_magic_damage(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 11, [])
        abilities = parse_abilities(
            akali_data, 11, 0.0, champion_stats=stats,
        )
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_r2_scaling_fields(self, akali_data: dict) -> None:
        """R should have r2_min, r2_max, and missing_hp_scaling."""
        stats = calculate_total_stats(akali_data, 6, [])
        abilities = parse_abilities(
            akali_data, 6, 100.0, champion_stats=stats,
        )
        r = abilities["R"]
        assert "r2_min" in r
        assert "r2_max" in r
        assert r["missing_hp_scaling"] is True
        assert r["r2_max"] > r["r2_min"]

    def test_r_magic_damage_is_r1_only(self, akali_data: dict) -> None:
        """magic_damage field should be R1 only (R2 computed by engine)."""
        stats = calculate_total_stats(akali_data, 6, [])
        abilities = parse_abilities(
            akali_data, 6, 100.0, champion_stats=stats,
        )
        r = abilities["R"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        r1_expected = 110 + 0.50 * bonus_ad + 0.30 * 100
        assert abs(r["magic_damage"] - r1_expected) < 1.0

    def test_r_total_raw_is_r1_plus_r2_max(self, akali_data: dict) -> None:
        """total_raw should be R1 + R2 max (upper bound for display)."""
        stats = calculate_total_stats(akali_data, 6, [])
        abilities = parse_abilities(
            akali_data, 6, 100.0, champion_stats=stats,
        )
        r = abilities["R"]
        assert abs(r["total_raw"] - (r["magic_damage"] + r["r2_max"])) < 0.1

    def test_r_has_cooldown(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 6, [])
        abilities = parse_abilities(
            akali_data, 6, 0.0, champion_stats=stats,
        )
        assert abilities["R"]["cooldown"] > 0

    def test_r_missing_hp_scaling_in_fight_engine(
        self, akali_data: dict,
    ) -> None:
        """R2 damage should be higher when other abilities deal damage first."""
        stats = calculate_total_stats(akali_data, 11, [])
        # With only R (no other abilities deal damage before R2)
        r_only = {"R": parse_abilities(
            akali_data, 11, 200.0, champion_stats=stats,
        )["R"]}
        result_r_only = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=r_only,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        # With Q, E dealing damage before R
        full = parse_abilities(
            akali_data, 11, 200.0, champion_stats=stats,
        )
        result_full = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=full,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
            cast_order=["Q", "E", "R"],
        )
        # R damage should be higher when Q/E dealt damage first
        # (more missing HP = higher R2 damage)
        r_dmg_alone = result_r_only["breakdown"]["R"]["total_damage"]
        r_dmg_after = result_full["breakdown"]["R"]["total_damage"]
        assert r_dmg_after > r_dmg_alone


class TestPassiveAssassinsMark:
    """Tests for P (Assassin's Mark) — empowered auto procs."""

    def test_passive_in_results_with_procs(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 3},
        )
        assert "passive" in abilities

    def test_passive_not_in_results_with_zero_procs(
        self, akali_data: dict,
    ) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_passive_damage_scales_with_level(
        self, akali_data: dict,
    ) -> None:
        low = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 1,
        )
        high = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 18,
        )
        assert high > low

    def test_passive_level1_base(self, akali_data: dict) -> None:
        """Level 1 passive base damage should be 35 (no AD/AP)."""
        damage = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 1,
        )
        assert abs(damage - 35.0) < 0.1

    def test_passive_level18_base(self, akali_data: dict) -> None:
        """Level 18 passive base damage should be 182 (non-linear growth)."""
        damage = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 18,
        )
        assert abs(damage - 182.0) < 0.1

    def test_passive_level20_base(self, akali_data: dict) -> None:
        """Level 20 passive base damage should be 212."""
        damage = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 20,
        )
        assert abs(damage - 212.0) < 0.1

    def test_passive_level7_base(self, akali_data: dict) -> None:
        """Level 7 passive base = 53 (+3/lvl from 35)."""
        damage = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 7,
        )
        assert abs(damage - 53.0) < 0.1

    def test_passive_level8_base(self, akali_data: dict) -> None:
        """Level 8 passive base = 62 (growth jumps to +9/lvl)."""
        damage = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 8,
        )
        assert abs(damage - 62.0) < 0.1

    def test_passive_scales_with_ap(self, akali_data: dict) -> None:
        no_ap = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 9, total_ability_power=0.0,
        )
        with_ap = _parse_passive_damage(
            akali_data["abilities"]["P"][0], 9, total_ability_power=200.0,
        )
        assert with_ap > no_ap

    def test_passive_proc_count_multiplies_total(
        self, akali_data: dict,
    ) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        one = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 1},
        )
        three = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 3},
        )
        assert abs(
            three["passive"]["total_raw"]
            - one["passive"]["total_raw"] * 3
        ) < 0.1

    def test_passive_has_proc_count_field(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 5},
        )
        assert abilities["passive"]["proc_count"] == 5


class TestPassiveInFightEngine:
    """Tests for passive proc_count integration with the fight engine."""

    def test_passive_damage_in_breakdown(self, akali_data: dict) -> None:
        stats = calculate_total_stats(akali_data, 9, [])
        abilities = parse_abilities(
            akali_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"passive_procs": 3},
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

        assert "passive" in result["breakdown"]
        assert result["breakdown"]["passive"]["total_damage"] > 0
        assert result["breakdown"]["passive"]["count"] == 3
