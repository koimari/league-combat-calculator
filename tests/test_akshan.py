"""Tests for Akshan champion ability parsing and damage calculation."""

import pytest

from src.calculator.stats import calculate_total_stats
from src.calculator.champions.common import extract_leveling_damage
from src.calculator.champions.akshan import (
    parse_abilities,
    _extract_e_per_shot,
    _parse_passive_proc_damage,
    _extract_double_shot_ratio,
)
from src.calculator.damage import calculate_fight_damage


class TestQAvengerang:
    """Tests for Q (Avengerang) — both passes combined."""

    def test_q_is_physical_damage(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 5)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_has_cooldown(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 5)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_total_damage(self, akshan_data, parse_at) -> None:
        """Q rank 1 Total: 90 + 140% bonus AD."""
        stats, abilities = parse_at(akshan_data, 1)
        q = abilities["Q"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        expected = 90 + 1.40 * bonus_ad
        assert abs(q["total_raw"] - expected) < 0.5

    def test_q_uses_total_not_single_pass(self, akshan_data, parse_at) -> None:
        """Q should use Total Physical Damage, not single-pass Physical Damage."""
        stats, abilities = parse_at(akshan_data, 1)
        q = abilities["Q"]
        bonus_ad = stats.get("bonus_attack_damage", 0.0)
        single_pass = 45 + 0.70 * bonus_ad
        assert q["total_raw"] > single_pass


class TestWGoingRogue:
    """Tests for W (Going Rogue) — utility, should be skipped."""

    def test_w_not_in_results(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 9)
        assert "W" not in abilities


class TestEHeroicSwing:
    """Tests for E (Heroic Swing) — configurable shot count."""

    def test_e_is_physical_damage(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"e_shots": 5},
        )
        assert abilities["E"]["damage_type"] == "physical"

    def test_e_has_cooldown(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"e_shots": 5},
        )
        assert abilities["E"]["cooldown"] > 0

    def test_e_per_shot_rank1(self, akshan_data) -> None:
        """E rank 1 per shot: 8 + 25% AD."""
        stats = calculate_total_stats(akshan_data, 1, [])
        e_ability = akshan_data["abilities"]["E"][0]
        per_shot = _extract_e_per_shot(e_ability, 1, stats)
        ad = stats["attack_damage"]
        expected = 8 + 0.25 * ad
        assert abs(per_shot - expected) < 1.0

    def test_e_total_scales_with_shots(self, akshan_data, parse_at) -> None:
        """E total damage should scale linearly with shot count."""
        _, three = parse_at(
            akshan_data, 5, champion_options={"e_shots": 3},
        )
        _, six = parse_at(
            akshan_data, 5, champion_options={"e_shots": 6},
        )
        assert abs(six["E"]["total_raw"] - three["E"]["total_raw"] * 2) < 0.1

    def test_e_zero_shots_excluded(self, akshan_data, parse_at) -> None:
        """E with 0 shots should not appear in results."""
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"e_shots": 0},
        )
        assert "E" not in abilities


class TestRComeuppance:
    """Tests for R (Comeuppance) — fully charged with crit scaling."""

    def test_r_is_physical_damage(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 6)
        assert abilities["R"]["damage_type"] == "physical"

    def test_r_has_cooldown(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 6)
        assert abilities["R"]["cooldown"] > 0

    def test_r_rank1_base_damage(self, akshan_data, parse_at) -> None:
        """R rank 1: 5 bullets * (25 + 15% AD) min per bullet (no missing HP)."""
        stats, abilities = parse_at(akshan_data, 6)
        r = abilities["R"]
        ad = stats["attack_damage"]
        expected_per_bullet = 25 + 0.15 * ad
        expected_total = expected_per_bullet * 5
        assert abs(r["physical_damage"] - expected_total) < 1.0

    def test_r_has_crit_effectiveness(self, akshan_data, parse_at) -> None:
        """R should have crit_effectiveness field for damage.py."""
        _, abilities = parse_at(akshan_data, 6)
        assert abilities["R"]["crit_effectiveness"] == 0.3

    def test_r_has_missing_hp_max_bonus(self, akshan_data, parse_at) -> None:
        """R should have missing_hp_max_bonus of 2.0 (0-200% scaling)."""
        _, abilities = parse_at(akshan_data, 6)
        assert abilities["R"]["missing_hp_max_bonus"] == 2.0

    def test_r_rank2_has_6_bullets(self, akshan_data, parse_at) -> None:
        """R rank 2: 6 bullets * (35 + 15% AD) min per bullet."""
        stats, abilities = parse_at(akshan_data, 11)
        r = abilities["R"]
        ad = stats["attack_damage"]
        per_bullet = 35 + 0.15 * ad
        expected = per_bullet * 6
        assert abs(r["physical_damage"] - expected) < 1.0


class TestPassiveDoubleShot:
    """Tests for P (Dirty Fighting) — double shot on auto attacks."""

    def test_double_shot_in_results(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 5)
        assert "passive_double_shot" in abilities

    def test_double_shot_has_ad_ratio(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(akshan_data, 5)
        ds = abilities["passive_double_shot"]["double_shot"]
        assert ds["ad_ratio"] == 0.5

    def test_double_shot_ratio_extraction(self, akshan_data) -> None:
        """Double shot ratio should be extracted from the passive description."""
        passive = akshan_data["abilities"]["P"][0]
        ratio = _extract_double_shot_ratio(passive)
        assert ratio == 0.5


class TestPassiveDirtyFighting:
    """Tests for P (Dirty Fighting) — 3-stack magic damage proc."""

    def test_passive_in_results_with_procs(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 3},
        )
        assert "passive" in abilities

    def test_passive_not_in_results_with_zero_procs(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_passive_is_magic_damage(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 3},
        )
        assert abilities["passive"]["damage_type"] == "magic"

    def test_passive_proc_damage_level1(self, akshan_data) -> None:
        """Level 1 passive proc damage should be 15 (no AP)."""
        passive = akshan_data["abilities"]["P"][0]
        damage = _parse_passive_proc_damage(passive, 1)
        assert abs(damage - 15.0) < 0.1

    def test_passive_proc_damage_level6(self, akshan_data) -> None:
        """Level 6 passive proc damage should be 40."""
        passive = akshan_data["abilities"]["P"][0]
        damage = _parse_passive_proc_damage(passive, 6)
        assert abs(damage - 40.0) < 0.1

    def test_passive_proc_damage_level11(self, akshan_data) -> None:
        """Level 11 passive proc damage should be 80."""
        passive = akshan_data["abilities"]["P"][0]
        damage = _parse_passive_proc_damage(passive, 11)
        assert abs(damage - 80.0) < 0.1

    def test_passive_proc_damage_level16(self, akshan_data) -> None:
        """Level 16 passive proc damage should be 150."""
        passive = akshan_data["abilities"]["P"][0]
        damage = _parse_passive_proc_damage(passive, 16)
        assert abs(damage - 150.0) < 0.1

    def test_passive_scales_with_ap(self, akshan_data) -> None:
        """Passive should scale with 60% AP."""
        passive = akshan_data["abilities"]["P"][0]
        no_ap = _parse_passive_proc_damage(passive, 11)
        with_ap = _parse_passive_proc_damage(
            passive, 11, {"ability_power": 200.0},
        )
        expected_bonus = 0.60 * 200.0
        assert abs((with_ap - no_ap) - expected_bonus) < 0.1

    def test_passive_proc_count_multiplies_total(self, akshan_data, parse_at) -> None:
        _, one = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 1},
        )
        _, three = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 3},
        )
        assert abs(
            three["passive"]["total_raw"] - one["passive"]["total_raw"] * 3
        ) < 0.1

    def test_passive_has_proc_count_field(self, akshan_data, parse_at) -> None:
        _, abilities = parse_at(
            akshan_data, 5, champion_options={"passive_procs": 5},
        )
        assert abilities["passive"]["proc_count"] == 5


class TestFightEngineIntegration:
    """Tests for Akshan integration with the fight engine."""

    def test_double_shot_in_breakdown(self, akshan_data, parse_at) -> None:
        """Double shot should appear in the fight breakdown."""
        stats, abilities = parse_at(
            akshan_data, 9, champion_options={"passive_procs": 0},
        )
        result = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
        )
        assert "double_shot" in result["breakdown"]
        assert result["breakdown"]["double_shot"]["total_damage"] > 0

    def test_passive_proc_in_breakdown(self, akshan_data, parse_at) -> None:
        """Passive procs should appear in the fight breakdown."""
        stats, abilities = parse_at(
            akshan_data, 9, champion_options={"passive_procs": 3},
        )
        result = calculate_fight_damage(
            champion_stats=dict(stats),
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

    def test_crit_effectiveness_amplifies_r(self, akshan_data, parse_at) -> None:
        """R damage should be higher with crit chance due to 30% effectiveness."""
        stats_no_crit, _ = parse_at(akshan_data, 6)
        stats_no_crit["critical_strike_chance"] = 0.0
        stats_with_crit = dict(stats_no_crit)
        stats_with_crit["critical_strike_chance"] = 100.0

        _, abilities_no_crit = parse_at(akshan_data, 6)
        _, abilities_with_crit = parse_at(akshan_data, 6)

        result_no_crit = calculate_fight_damage(
            champion_stats=dict(stats_no_crit),
            ability_damages={"R": abilities_no_crit["R"]},
            target_health=100000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        result_with_crit = calculate_fight_damage(
            champion_stats=dict(stats_with_crit),
            ability_damages={"R": abilities_with_crit["R"]},
            target_health=100000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )

        r_no_crit = result_no_crit["breakdown"]["R"]["total_damage"]
        r_with_crit = result_with_crit["breakdown"]["R"]["total_damage"]
        assert r_with_crit > r_no_crit
        ratio = r_with_crit / r_no_crit
        assert abs(ratio - 1.30) < 0.05

    def test_r_missing_hp_scaling(self, akshan_data, parse_at) -> None:
        """R damage should be higher when Q/E deal damage first (more missing HP)."""
        stats, abilities_full = parse_at(
            akshan_data, 11,
            champion_options={"passive_procs": 0, "e_shots": 5},
        )
        stats["critical_strike_chance"] = 0.0

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

        abilities_for_test = {
            k: v for k, v in abilities_full.items() if k != "passive_double_shot"
        }
        result_full = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages=abilities_for_test,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
            cast_order=["Q", "Q2", "E", "R", "W"],
        )

        r_alone = result_r_only["breakdown"]["R"]["total_damage"]
        r_after = result_full["breakdown"]["R"]["total_damage"]
        assert r_after > r_alone

    def test_r_crit_formula_matches_wiki(self, akshan_data, parse_at) -> None:
        """Verify R crit formula: 3% per 10% crit chance."""
        stats, abilities = parse_at(akshan_data, 18)
        stats["critical_strike_chance"] = 75.0
        r_base = abilities["R"]["physical_damage"]

        result = calculate_fight_damage(
            champion_stats=dict(stats),
            ability_damages={"R": abilities["R"]},
            target_health=1000000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )

        r_damage = result["breakdown"]["R"]["total_damage"]
        expected = r_base * 1.225
        assert abs(r_damage - expected) / expected < 0.02

    def test_all_abilities_present(self, akshan_data, parse_at) -> None:
        """All expected abilities should be present at level 9."""
        _, abilities = parse_at(
            akshan_data, 9,
            champion_options={"passive_procs": 3, "e_shots": 5},
        )
        assert "Q" in abilities
        assert "W" not in abilities
        assert "E" in abilities
        assert "R" in abilities
        assert "passive_double_shot" in abilities
        assert "passive" in abilities
