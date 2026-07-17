"""Tests for Akali champion ability parsing and damage calculation."""

import pytest

from src.calculator.stats import calculate_total_stats
from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions.slotlib import build_stats_context, extract_named
from src.calculator.damage import calculate_fight_damage


def _passive_damage(
    passive: dict,
    level: int,
    total_ability_power: float = 0.0,
) -> float:
    """Per-proc Assassin's Mark damage at a level.

    The same "Bonus Magic Damage" extraction the P slot's proc_damage
    archetype performs — validated here directly against wiki values.
    """
    stats = build_stats_context(None, total_ability_power)
    return extract_named(passive, "Bonus Magic Damage", level, stats)


class TestQFivePointStrike:
    """Tests for Q (Five Point Strike) — standard magic damage."""

    def test_q_is_magic_damage(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 9)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_base_plus_scaling(self, akali_data, parse_at) -> None:
        """Q rank 1: 45 + 65% AD + 60% AP."""
        stats, abilities = parse_at(akali_data, 1)
        q = abilities["Q"]
        ad = stats["attack_damage"]
        expected = 45 + 0.65 * ad
        assert abs(q["total_raw"] - expected) < 0.5


class TestWTwilightShroud:
    """Tests for W (Twilight Shroud) — no damage, should be skipped."""

    def test_w_not_in_results(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 9)
        assert "W" not in abilities


class TestEShurikenFlip:
    """Tests for E (Shuriken Flip) — both hits combined."""

    def test_e_is_magic_damage(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 9)
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_uses_total_damage(self, akali_data, parse_at) -> None:
        """E should use Total Magic Damage (shuriken + dash), not single hit."""
        stats, abilities = parse_at(akali_data, 3)
        e = abilities["E"]
        ad = stats["attack_damage"]
        expected_total = 70 + 1.0 * ad
        single_hit = 21 + 0.30 * ad
        assert abs(e["total_raw"] - expected_total) < 0.5
        assert e["total_raw"] > single_hit * 2

    def test_e_has_cooldown(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 3)
        assert abilities["E"]["cooldown"] > 0


class TestRPerfectExecution:
    """Tests for R (Perfect Execution) — R1 + R2 minimum combined."""

    def test_r_is_magic_damage(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 11)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_parts_are_flat_r1_plus_scaling_r2(self, akali_data, parse_at) -> None:
        """R is two parts: a flat R1 and an R2 that interpolates min-max."""
        _, abilities = parse_at(akali_data, 6, ap=100.0)
        r1, r2 = abilities["R"]["parts"]
        assert r1.hp_scaled_damage is None
        r2_min = r2.hp_scaled_damage(0.0)
        r2_max = r2.hp_scaled_damage(1.0)
        assert r2_max > r2_min > 0

    def test_r_first_part_is_r1_only(self, akali_data, parse_at) -> None:
        """The flat part is R1 only (R2 resolved by the engine at cast)."""
        stats, abilities = parse_at(akali_data, 6, ap=100.0)
        r1, _ = abilities["R"]["parts"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        r1_expected = 110 + 0.50 * bonus_ad + 0.30 * 100
        assert abs(r1.amount - r1_expected) < 1.0

    def test_r_total_raw_is_r1_plus_r2_max(self, akali_data, parse_at) -> None:
        """total_raw should be R1 + R2 max (upper bound for display)."""
        _, abilities = parse_at(akali_data, 6, ap=100.0)
        r = abilities["R"]
        r1, r2 = r["parts"]
        assert abs(r["total_raw"] - (r1.amount + r2.hp_scaled_damage(1.0))) < 0.1

    def test_r_has_cooldown(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(akali_data, 6)
        assert abilities["R"]["cooldown"] > 0

    def test_r_missing_hp_scaling_in_fight_engine(self, akali_data, parse_at) -> None:
        """R2 damage should be higher when other abilities deal damage first."""
        stats, abilities_full = parse_at(akali_data, 11, ap=200.0)
        r_only = {"R": abilities_full["R"]}

        result_r_only = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=r_only,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        result_full = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=abilities_full,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
            cast_order=["Q", "E", "R"],
        )
        r_dmg_alone = result_r_only["breakdown"]["R"]["total_damage"]
        r_dmg_after = result_full["breakdown"]["R"]["total_damage"]
        assert r_dmg_after > r_dmg_alone


class TestPassiveAssassinsMark:
    """Tests for P (Assassin's Mark) — empowered auto procs."""

    def test_passive_in_results_with_procs(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(
            akali_data,
            9,
            champion_options={"passive_procs": 3},
        )
        assert "passive" in abilities

    def test_passive_not_in_results_with_zero_procs(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(
            akali_data,
            9,
            champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_passive_damage_scales_with_level(self, akali_data) -> None:
        low = _passive_damage(akali_data["abilities"]["P"][0], 1)
        high = _passive_damage(akali_data["abilities"]["P"][0], 18)
        assert high > low

    def test_passive_level1_base(self, akali_data) -> None:
        """Level 1 passive base damage should be 35 (no AD/AP)."""
        damage = _passive_damage(akali_data["abilities"]["P"][0], 1)
        assert abs(damage - 35.0) < 0.1

    def test_passive_level18_base(self, akali_data) -> None:
        """Level 18 passive base damage should be 182 (non-linear growth)."""
        damage = _passive_damage(akali_data["abilities"]["P"][0], 18)
        assert abs(damage - 182.0) < 0.1

    def test_passive_level20_base(self, akali_data) -> None:
        """Level 20 passive base damage should be 212."""
        damage = _passive_damage(akali_data["abilities"]["P"][0], 20)
        assert abs(damage - 212.0) < 0.1

    def test_passive_level7_base(self, akali_data) -> None:
        """Level 7 passive base = 53 (+3/lvl from 35)."""
        damage = _passive_damage(akali_data["abilities"]["P"][0], 7)
        assert abs(damage - 53.0) < 0.1

    def test_passive_level8_base(self, akali_data) -> None:
        """Level 8 passive base = 62 (growth jumps to +9/lvl)."""
        damage = _passive_damage(akali_data["abilities"]["P"][0], 8)
        assert abs(damage - 62.0) < 0.1

    def test_passive_scales_with_ap(self, akali_data) -> None:
        no_ap = _passive_damage(
            akali_data["abilities"]["P"][0],
            9,
            total_ability_power=0.0,
        )
        with_ap = _passive_damage(
            akali_data["abilities"]["P"][0],
            9,
            total_ability_power=200.0,
        )
        assert with_ap > no_ap

    def test_passive_proc_count_multiplies_total(self, akali_data, parse_at) -> None:
        _, one = parse_at(
            akali_data,
            9,
            champion_options={"passive_procs": 1},
        )
        _, three = parse_at(
            akali_data,
            9,
            champion_options={"passive_procs": 3},
        )
        assert (
            abs(three["passive"]["total_raw"] - one["passive"]["total_raw"] * 3) < 0.1
        )

    def test_passive_has_proc_count_field(self, akali_data, parse_at) -> None:
        _, abilities = parse_at(
            akali_data,
            9,
            champion_options={"passive_procs": 5},
        )
        assert abilities["passive"]["proc_count"] == 5


class TestPassiveInFightEngine:
    """Tests for passive proc_count integration with the fight engine."""

    def test_passive_damage_in_breakdown(self, akali_data, parse_at) -> None:
        stats, abilities = parse_at(
            akali_data,
            9,
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
