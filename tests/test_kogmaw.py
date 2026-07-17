"""Tests for Kog'Maw custom champion module.

Reference damage (level 9, rank 5 Q, rank 3 W, rank 3 E, rank 1 R, 80 AP):
- Q: 260 + 72 = 332 magic damage
- W on-hit (vs 2000 HP target): (4.5% + 1.2%) * 2000 = 114 magic per auto
- E: 150 + 52 = 202 magic damage
- R min (full HP target): 100 + 28 AP = 128 magic damage (0 bonus AD)
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_2000_HP = {"target_max_health": 2000.0}

# The module's reference loadout (level 9): Q maxed, W/E rank 3, R rank 1.
# Tests that isolate a single ability declare their own rank dicts inline.
STANDARD_RANKS = {"Q": 5, "W": 3, "E": 3, "R": 1}


# ---------------------------------------------------------------------------
# Q: Caustic Spittle
# ---------------------------------------------------------------------------


class TestQCausticSpittle:
    """Tests for Q ability damage, resistance shred, and bonus AS."""

    def test_q_is_magic_damage(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["Q"]["cooldown"] > 0

    def test_q_damage_reference(self, kogmaw_data) -> None:
        """Q rank 5 with 80 AP: 260 + 0.9*80 = 260 + 72 = 332."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_stats={"attack_damage": 80.0, "bonus_attack_damage": 0.0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(332.0, abs=1.0)

    def test_q_resistance_shred_present(self, kogmaw_data) -> None:
        """Q should have target_debuff when q_shred is enabled."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"q_shred": True},
        )
        assert "target_debuff" in abilities["Q"]
        debuff = abilities["Q"]["target_debuff"]
        assert debuff["armor_reduction_percent"] > 0
        assert debuff["mr_reduction_percent"] > 0

    def test_q_shred_disabled(self, kogmaw_data) -> None:
        """Q should NOT have target_debuff when q_shred is disabled."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"q_shred": False},
        )
        assert "target_debuff" not in abilities["Q"]

    def test_q_shred_values_scale_with_rank(self, kogmaw_data) -> None:
        """Resistance shred: 16/20/24/28/32% by Q rank."""
        expected = {1: 16.0, 3: 24.0, 5: 32.0}
        for rank, expected_pct in expected.items():
            abilities = parse_abilities(
                kogmaw_data,
                9,
                0.0,
                ability_ranks={"Q": rank, "W": 0, "E": 0, "R": 0},
                champion_options={"q_shred": True},
            )
            debuff = abilities["Q"]["target_debuff"]
            assert debuff["armor_reduction_percent"] == pytest.approx(
                expected_pct,
                abs=0.5,
            )

    def test_q_bonus_attack_speed_stat_buff(self, kogmaw_data) -> None:
        """Q should include a stat_buff with bonus_attack_speed."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
        )
        assert "stat_buff" in abilities["Q"]
        assert abilities["Q"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(
            25.0,
            abs=0.5,
        )


# ---------------------------------------------------------------------------
# W: Bio-Arcane Barrage
# ---------------------------------------------------------------------------


class TestWBioArcaneBarrage:
    """Tests for W on-hit % max HP magic damage."""

    def test_w_on_hit_present(self, kogmaw_data) -> None:
        """W should return an on_hit entry when w_active is True."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": True},
            target_stats=TARGET_2000_HP,
        )
        assert "W" in abilities
        assert "on_hit" in abilities["W"]

    def test_w_disabled(self, kogmaw_data) -> None:
        """W should NOT be in results when w_active is False."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": False},
            target_stats=TARGET_2000_HP,
        )
        assert "W" not in abilities

    def test_w_on_hit_damage_reference(self, kogmaw_data) -> None:
        """W rank 3 with 80 AP vs 2000 HP target:
        (4.5% + 80*1.5%/100) * 2000 = (0.045 + 0.012) * 2000 = 114.
        """
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": True},
            target_stats=TARGET_2000_HP,
        )
        on_hit = abilities["W"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(114.0, abs=1.0)
        assert on_hit["damage_type"] == "magic"

    def test_w_no_direct_damage(self, kogmaw_data) -> None:
        """W has no direct cast damage (purely on-hit buff)."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": True},
            target_stats=TARGET_2000_HP,
        )
        assert abilities["W"]["total_raw"] == 0.0

    def test_w_on_hit_scales_with_rank(self, kogmaw_data) -> None:
        """W base % increases: 3/3.75/4.5/5.25/6% max HP."""
        abilities_r1 = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 1, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        abilities_r5 = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        # Rank 1: 3% of 2000 = 60, Rank 5: 6% of 2000 = 120
        assert abilities_r1["W"]["on_hit"]["damage_per_hit"] == pytest.approx(
            60.0,
            abs=1.0,
        )
        assert abilities_r5["W"]["on_hit"]["damage_per_hit"] == pytest.approx(
            120.0,
            abs=1.0,
        )

    def test_w_has_cooldown(self, kogmaw_data) -> None:
        abilities = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 3, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        assert abilities["W"]["cooldown"] > 0


# ---------------------------------------------------------------------------
# E: Void Ooze
# ---------------------------------------------------------------------------


class TestEVoidOoze:
    """Tests for E ability damage."""

    def test_e_is_magic_damage(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["E"]["cooldown"] > 0

    def test_e_damage_reference(self, kogmaw_data) -> None:
        """E rank 3 with 80 AP: 150 + 0.65*80 = 150 + 52 = 202."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["E"]["total_raw"] == pytest.approx(202.0, abs=1.0)


# ---------------------------------------------------------------------------
# R: Living Artillery
# ---------------------------------------------------------------------------


class TestRLivingArtillery:
    """Tests for R ability damage and missing HP scaling."""

    def test_r_is_magic_damage(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_cooldown(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert abilities["R"]["cooldown"] > 0

    def test_r_min_damage_reference(self, kogmaw_data) -> None:
        """R rank 1 with 80 AP, 0 bonus AD: 100 + 0.35*80 = 100 + 28 = 128."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_stats={
                "attack_damage": 80.0,
                "bonus_attack_damage": 0.0,
            },
        )
        assert abilities["R"]["total_raw"] == pytest.approx(128.0, abs=1.0)

    def test_r_part_scales_with_missing_hp_curve(self, kogmaw_data) -> None:
        """R's part follows the wiki curve: +50% to 60% missing, then +100%."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
        )
        (part,) = abilities["R"]["parts"]
        base = part.hp_scaled_damage(0.0)
        assert base > 0
        assert part.hp_scaled_damage(0.3) == pytest.approx(base * 1.25)
        assert part.hp_scaled_damage(0.6) == pytest.approx(base * 2.0)
        assert part.hp_scaled_damage(1.0) == pytest.approx(base * 2.0)

    def test_r_scales_with_bonus_ad(self, kogmaw_data) -> None:
        """R should include bonus AD scaling (75% bonus AD)."""
        abilities_no_ad = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 1},
            champion_stats={
                "attack_damage": 80.0,
                "bonus_attack_damage": 0.0,
            },
        )
        abilities_with_ad = parse_abilities(
            kogmaw_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 1},
            champion_stats={
                "attack_damage": 180.0,
                "bonus_attack_damage": 100.0,
            },
        )
        # 75% bonus AD = 75 extra damage with 100 bonus AD
        diff = abilities_with_ad["R"]["total_raw"] - abilities_no_ad["R"]["total_raw"]
        assert diff == pytest.approx(75.0, abs=1.0)


# ---------------------------------------------------------------------------
# Passive: Icathian Surprise (not modeled)
# ---------------------------------------------------------------------------


class TestPassive:
    """Passive should not be present in results."""

    def test_passive_not_in_results(self, kogmaw_data, parse_at) -> None:
        _, abilities = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
        )
        assert "passive" not in abilities
        assert "P" not in abilities


# ---------------------------------------------------------------------------
# Champion options toggle behavior
# ---------------------------------------------------------------------------


class TestChampionOptions:
    """Tests for champion option toggles."""

    def test_default_options(self, kogmaw_data) -> None:
        """Default: both q_shred and w_active should be True."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            target_stats=TARGET_2000_HP,
        )
        # Q shred present (default True)
        assert "target_debuff" in abilities["Q"]
        # W present (default True)
        assert "W" in abilities

    def test_all_options_disabled(self, kogmaw_data) -> None:
        """Both options disabled: no shred, no W."""
        abilities = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"q_shred": False, "w_active": False},
            target_stats=TARGET_2000_HP,
        )
        assert "target_debuff" not in abilities["Q"]
        assert "W" not in abilities


# ---------------------------------------------------------------------------
# Fight engine integration
# ---------------------------------------------------------------------------


class TestFightEngineIntegration:
    """Tests for integration with the fight damage engine."""

    def test_q_shred_increases_total_damage(self, kogmaw_data, parse_at) -> None:
        """With Q shred enabled, total damage should be higher."""
        stats, _ = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
            ap=80.0,
        )

        abilities_shred = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"q_shred": True},
            champion_stats=dict(stats),
        )
        abilities_no_shred = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"q_shred": False},
            champion_stats=dict(stats),
        )

        result_shred = calculate_fight_damage(
            dict(stats),
            abilities_shred,
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=60.0,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.7,
            one_rotation=True,
        )
        result_no_shred = calculate_fight_damage(
            dict(stats),
            abilities_no_shred,
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=60.0,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.7,
            one_rotation=True,
        )
        assert result_shred["total_damage"] > result_no_shred["total_damage"]

    def test_w_on_hit_in_fight_engine(self, kogmaw_data, parse_at) -> None:
        """W on-hit damage should contribute to total fight damage."""
        stats, _ = parse_at(
            kogmaw_data,
            9,
            ability_ranks=STANDARD_RANKS,
            ap=80.0,
        )

        abilities_w_on = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": True},
            champion_stats=dict(stats),
            target_stats=TARGET_2000_HP,
        )
        abilities_w_off = parse_abilities(
            kogmaw_data,
            9,
            80.0,
            ability_ranks=STANDARD_RANKS,
            champion_options={"w_active": False},
            champion_stats=dict(stats),
        )

        result_w_on = calculate_fight_damage(
            dict(stats),
            abilities_w_on,
            target_health=2000.0,
            target_armor=50.0,
            target_magic_resistance=50.0,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.7,
        )
        result_w_off = calculate_fight_damage(
            dict(stats),
            abilities_w_off,
            target_health=2000.0,
            target_armor=50.0,
            target_magic_resistance=50.0,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.7,
        )
        assert result_w_on["total_damage"] > result_w_off["total_damage"]
