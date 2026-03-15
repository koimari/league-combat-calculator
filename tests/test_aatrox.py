"""Tests for Aatrox champion ability parsing and damage calculation."""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.aatrox import (
    parse_abilities,
    _extract_leveling_damage,
    _extract_r_bonus_ad_percent,
    _parse_passive_on_hit,
)
from src.calculator.damage import calculate_fight_damage


@pytest.fixture
def aatrox_data() -> dict:
    """Load Aatrox champion data from the cached JSON."""
    return get_champion("Aatrox")


class TestQThreeCasts:
    """Tests for Q (The Darkin Blade) three-cast mechanic."""

    def test_q_returns_physical_damage(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        abilities = parse_abilities(
            aatrox_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_sweetspot_deals_more_damage(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        normal = parse_abilities(
            aatrox_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        sweetspot = parse_abilities(
            aatrox_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": True},
        )
        assert sweetspot["Q"]["total_raw"] > normal["Q"]["total_raw"]

    def test_q_sweetspot_is_default(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        default = parse_abilities(
            aatrox_data, 9, 0.0, champion_stats=stats,
        )
        sweetspot = parse_abilities(
            aatrox_data, 9, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": True},
        )
        assert abs(default["Q"]["total_raw"] - sweetspot["Q"]["total_raw"]) < 0.1

    def test_q_has_cooldown(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        abilities = parse_abilities(
            aatrox_data, 9, 0.0, champion_stats=stats,
        )
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank1_normal_damage_matches_json(
        self, aatrox_data: dict,
    ) -> None:
        """Verify Q rank 1 normal damage = sum of 3 casts at base AD."""
        stats = calculate_total_stats(aatrox_data, 1, [])
        # No R buff at level 1, so AD = base stats
        abilities = parse_abilities(
            aatrox_data, 1, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        q = abilities["Q"]
        ad = stats["attack_damage"]
        # First Cast: 10 + 60% AD
        # Second Cast: 12.5 + 75% AD
        # Third Cast: 15 + 90% AD
        expected = (10 + 0.60 * ad) + (12.5 + 0.75 * ad) + (15 + 0.90 * ad)
        assert abs(q["total_raw"] - expected) < 0.5

    def test_q_three_casts_sum(self, aatrox_data: dict) -> None:
        """Q total damage equals sum of all three individual casts.

        Uses level 5 (R not yet ranked) so no R buff distorts the
        comparison between manual extraction and parse_abilities.
        """
        q_ability = aatrox_data["abilities"]["Q"][0]
        stats = calculate_total_stats(aatrox_data, 5, [])
        rank = 3  # Q rank 3 at level 5
        stats_ctx = dict(stats)

        first = _extract_leveling_damage(
            q_ability, "First Cast Damage", rank, stats_ctx,
        )
        second = _extract_leveling_damage(
            q_ability, "Second Cast Damage", rank, stats_ctx,
        )
        third = _extract_leveling_damage(
            q_ability, "Third Cast Damage", rank, stats_ctx,
        )

        abilities = parse_abilities(
            aatrox_data, 5, 0.0,
            champion_stats=stats,
            champion_options={"sweetspot": False},
        )
        assert abs(abilities["Q"]["total_raw"] - (first + second + third)) < 0.5


class TestPassiveOnHit:
    """Tests for P (Deathbringer Stance) on-hit parsing."""

    def test_passive_returns_on_hit(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 9, 0.0,
            champion_stats=stats,
            target_stats=target_stats,
        )
        assert "passive" in abilities
        assert "on_hit" in abilities["passive"]

    def test_passive_damage_type_is_magic(self, aatrox_data: dict) -> None:
        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 9, 0.0,
            target_stats=target_stats,
        )
        assert abilities["passive"]["on_hit"]["damage_type"] == "magic"

    def test_passive_scales_with_level(self, aatrox_data: dict) -> None:
        target_stats = {"target_max_health": 2000.0}
        low = parse_abilities(
            aatrox_data, 1, 0.0, target_stats=target_stats,
        )
        high = parse_abilities(
            aatrox_data, 18, 0.0, target_stats=target_stats,
        )
        low_dmg = low["passive"]["on_hit"]["damage_per_hit"]
        high_dmg = high["passive"]["on_hit"]["damage_per_hit"]
        assert high_dmg > low_dmg

    def test_passive_level1_percent(self, aatrox_data: dict) -> None:
        """Level 1 passive should deal ~4% of target max health."""
        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 1, 0.0, target_stats=target_stats,
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        # 4% of 2000 = 80
        assert abs(damage - 80.0) < 1.0

    def test_passive_level18_percent(self, aatrox_data: dict) -> None:
        """Level 18 passive should deal ~10.71% of target max health."""
        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 18, 0.0, target_stats=target_stats,
        )
        damage = abilities["passive"]["on_hit"]["damage_per_hit"]
        # 10.71% of 2000 = 214.2
        assert abs(damage - 214.2) < 1.0


class TestRWorldEnder:
    """Tests for R (World Ender) stat buff."""

    def test_r_deals_no_damage(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 11, [])
        abilities = parse_abilities(
            aatrox_data, 11, 0.0, champion_stats=stats,
        )
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_has_stat_buff(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 11, [])
        abilities = parse_abilities(
            aatrox_data, 11, 0.0, champion_stats=stats,
        )
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] > 0

    def test_r_buff_increases_q_damage(self, aatrox_data: dict) -> None:
        """Q damage should be higher when R is ranked (buff applied)."""
        stats = calculate_total_stats(aatrox_data, 5, [])
        # Level 5: R is not ranked yet
        no_r = parse_abilities(
            aatrox_data, 5, 0.0, champion_stats=stats,
        )
        stats_11 = calculate_total_stats(aatrox_data, 11, [])
        # Level 11: R rank 2
        with_r = parse_abilities(
            aatrox_data, 11, 0.0, champion_stats=stats_11,
        )
        # Both have Q at rank 3 at level 5 vs Q at rank 5 at level 11,
        # R buff should increase damage beyond just rank difference
        assert with_r["Q"]["total_raw"] > no_r["Q"]["total_raw"]

    def test_r_bonus_ad_percent_rank1(self, aatrox_data: dict) -> None:
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = _extract_r_bonus_ad_percent(r_ability, 1)
        assert abs(bonus - 0.20) < 0.01

    def test_r_bonus_ad_percent_rank3(self, aatrox_data: dict) -> None:
        r_ability = aatrox_data["abilities"]["R"][0]
        bonus = _extract_r_bonus_ad_percent(r_ability, 3)
        assert abs(bonus - 0.40) < 0.01


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(
        self, aatrox_data: dict,
    ) -> None:
        """The fight engine should apply R's bonus AD to champion stats."""
        stats = calculate_total_stats(aatrox_data, 11, [])
        original_ad = stats["attack_damage"]

        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 11, 0.0,
            champion_stats=stats,
            target_stats=target_stats,
        )

        # Run fight engine — it should mutate champion_stats with the buff
        calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )

        # champion_stats AD should now be higher than original
        assert stats["attack_damage"] > original_ad

    def test_r_zero_damage_in_breakdown(self, aatrox_data: dict) -> None:
        """R should appear in fight engine but contribute 0 damage."""
        stats = calculate_total_stats(aatrox_data, 11, [])
        target_stats = {"target_max_health": 2000.0}
        abilities = parse_abilities(
            aatrox_data, 11, 0.0,
            champion_stats=stats,
            target_stats=target_stats,
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

        r_entry = result["breakdown"].get("R", {})
        assert r_entry.get("total_damage", 0.0) == 0.0


class TestWInfernalChains:
    """Tests for W (Infernal Chains) damage parsing."""

    def test_w_returns_physical_damage(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 3, [])
        abilities = parse_abilities(
            aatrox_data, 3, 0.0, champion_stats=stats,
        )
        assert "W" in abilities
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_has_cooldown(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 3, [])
        abilities = parse_abilities(
            aatrox_data, 3, 0.0, champion_stats=stats,
        )
        assert abilities["W"]["cooldown"] > 0

    def test_w_uses_total_damage_both_hits(self, aatrox_data: dict) -> None:
        """W should use Total Damage (initial + pull-back), not single hit."""
        # Level 3: W rank 1 (no R yet, so AD = base stats)
        stats = calculate_total_stats(aatrox_data, 3, [])
        abilities = parse_abilities(
            aatrox_data, 3, 0.0, champion_stats=stats,
        )
        w = abilities["W"]
        ad = stats["attack_damage"]
        # W rank 1 Total Damage: 60 + 80% AD (both hits combined)
        expected_total = 60 + 0.80 * ad
        # Single hit would be: 30 + 40% AD (half the total)
        single_hit = 30 + 0.40 * ad
        assert abs(w["total_raw"] - expected_total) < 0.5
        assert w["total_raw"] > single_hit * 1.5


class TestEUmbralDash:
    """Tests for E (Umbral Dash) — should not appear in abilities."""

    def test_e_not_in_results(self, aatrox_data: dict) -> None:
        stats = calculate_total_stats(aatrox_data, 9, [])
        abilities = parse_abilities(
            aatrox_data, 9, 0.0, champion_stats=stats,
        )
        assert "E" not in abilities
