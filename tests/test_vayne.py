"""Tests for Vayne champion ability parsing and damage calculation.

Reference damage (rank 5 abilities, 200 total AD, 100 AP, 2000 target max HP,
level 18):
- Q: 200 * 1.15 + 100 * 0.50 = 230 + 50 = 280 bonus physical damage
- W proc: max(2000 * 0.10, 110) = 200 true damage per proc
- E (with wall): 475 + bonus_AD * 1.25 physical damage
- R: 0 damage (stat buff only, +65 AD)
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_2000_HP = {"target_max_health": 2000.0}


# ---------------------------------------------------------------------------
# Q: Tumble
# ---------------------------------------------------------------------------


class TestQTumble:
    """Tests for Q (Tumble) empowered auto attack."""

    def test_q_is_physical_damage(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 9)
        assert "Q" in abilities
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_has_cooldown(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank5_damage_reference(self, vayne_data) -> None:
        """Q rank 5 with 200 total AD and 100 AP:
        200 * 1.15 + 100 * 0.50 = 230 + 50 = 280.
        """
        abilities = parse_abilities(
            vayne_data,
            18,
            100.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 100.0,
            },
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(280.0, abs=1.0)

    def test_q_damage_scales_with_rank(self, vayne_data) -> None:
        """Q damage should increase with rank."""
        abilities_r1 = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        abilities_r5 = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        assert abilities_r5["Q"]["total_raw"] > abilities_r1["Q"]["total_raw"]

    def test_q_rank1_damage(self, vayne_data) -> None:
        """Q rank 1 with 100 AD, 0 AP: 100 * 0.75 = 75."""
        abilities = parse_abilities(
            vayne_data,
            1,
            0.0,
            ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(75.0, abs=1.0)


# ---------------------------------------------------------------------------
# Q cooldown reduction from R
# ---------------------------------------------------------------------------


class TestQCooldownWithR:
    """Tests for Q cooldown reduction when R is active."""

    def test_q_cooldown_reduced_by_r(self, vayne_data) -> None:
        """R rank 3 reduces Q cooldown by 50%."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        # Q rank 5 base CD = 2s, with 50% reduction = 1.0s
        assert abilities["Q"]["cooldown"] == pytest.approx(1.0, abs=0.1)

    def test_q_cooldown_no_r(self, vayne_data) -> None:
        """Without R, Q cooldown is not reduced."""
        abilities = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        # Q rank 5 base CD = 2s
        assert abilities["Q"]["cooldown"] == pytest.approx(2.0, abs=0.1)

    def test_q_cooldown_r_rank1(self, vayne_data) -> None:
        """R rank 1 reduces Q cooldown by 30%."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 1},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        # Q rank 5 base CD = 2s, with 30% reduction = 1.4s
        assert abilities["Q"]["cooldown"] == pytest.approx(1.4, abs=0.1)


# ---------------------------------------------------------------------------
# Q: Tumble ↔ auto-attack coupling (time-based fights)
# ---------------------------------------------------------------------------


class TestTumbleAutoCoupling:
    """Q empowers the next auto: casts are gated by the auto stream.

    Reference scenario (mirrors the observed optimizer bug): level 18,
    R rank 3 (Q CD 2.0s -> 1.0s), 50 ability haste (-> 0.667s), 1.29
    attack speed, 10s fight, 100% AA uptime. Uncoupled, the engine cast
    Q 16 times against only 12 autos — impossible, since Tumble only
    deals damage through the empowered auto.

    Coupled model: casts = min(cooldown casts, autos) = min(16, 12)
    = 12. The auto count itself stays floor(1.29 * 10) = 12: Tumble is
    an attack reset, its dash spent in attack-cooldown dead time (the
    in-game reset acceleration is not modeled — conservative).
    """

    @staticmethod
    def _run_fight(stats: dict, abilities: dict, **overrides) -> dict:
        config = {
            "target_health": 1000.0,
            "target_armor": 100.0,
            "target_magic_resistance": 100.0,
            "fight_duration_seconds": 10.0,
            "auto_attack_uptime": 1.0,
            "one_rotation": False,
            "deterministic": True,
        }
        config.update(overrides)
        return calculate_fight_damage(stats, abilities, [], FightConfig(**config))

    @pytest.fixture
    def reference_setup(self, vayne_data, parse_at) -> tuple[dict, dict]:
        stats, abilities = parse_at(
            vayne_data,
            18,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        )
        stats["ability_haste"] = 50.0
        stats["attack_speed"] = 1.29
        return stats, abilities

    def test_q_casts_capped_by_auto_count(self, reference_setup) -> None:
        """Tumble only damages via the empowered auto: casts <= autos."""
        stats, abilities = reference_setup
        result = self._run_fight(stats, abilities)
        q_casts = result["breakdown"]["Q"]["casts"]
        autos = result["breakdown"]["auto_attacks"]["count"]
        assert q_casts <= autos

    def test_autos_unchanged_by_tumbling(self, reference_setup) -> None:
        """Tumble is an attack reset: the auto count is not reduced."""
        stats, abilities = reference_setup
        result = self._run_fight(stats, abilities)
        autos = result["breakdown"]["auto_attacks"]["count"]
        assert autos == int(1.29 * 10.0)  # 12, same as without Q casts

    def test_reference_cast_and_auto_counts(self, reference_setup) -> None:
        """Hand-derived: min(16 cooldown casts, 12 autos) -> 12 and 12."""
        stats, abilities = reference_setup
        result = self._run_fight(stats, abilities)
        assert result["breakdown"]["Q"]["casts"] == 12
        assert result["breakdown"]["auto_attacks"]["count"] == 12

    def test_one_rotation_q_casts_once(self, reference_setup) -> None:
        """One-rotation mode is unaffected: Q casts exactly once."""
        stats, abilities = reference_setup
        result = self._run_fight(stats, abilities, one_rotation=True)
        assert result["breakdown"]["Q"]["casts"] == 1

    def test_no_autos_means_no_tumbles(self, reference_setup) -> None:
        """With zero AA uptime there is no auto to empower: Q never lands."""
        stats, abilities = reference_setup
        result = self._run_fight(stats, abilities, auto_attack_uptime=0.0)
        assert result["breakdown"]["Q"]["casts"] == 0


# ---------------------------------------------------------------------------
# W: Silver Bolts
# ---------------------------------------------------------------------------


class TestWSilverBolts:
    """Tests for W (Silver Bolts) passive 3-stack proc."""

    def test_w_has_on_hit_data(self, vayne_data) -> None:
        """W should return on_hit data for fight engine integration."""
        abilities = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        assert "W" in abilities
        assert "on_hit" in abilities["W"]

    def test_w_damage_type_is_true(self, vayne_data) -> None:
        abilities = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        assert abilities["W"]["on_hit"]["damage_type"] == "true"

    def test_w_rank5_damage_per_hit_reference(self, vayne_data) -> None:
        """W rank 5 vs 2000 HP target: max(2000*0.10, 110)=200 per proc,
        damage_per_hit = 200 / 3 ≈ 66.67."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        on_hit = abilities["W"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(200.0 / 3, abs=0.5)

    def test_w_minimum_damage_applies(self, vayne_data) -> None:
        """Against low-HP targets, minimum damage should apply.
        Rank 5 minimum is 110, 10% of 500 = 50 < 110.
        damage_per_hit = 110 / 3 ≈ 36.67."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            target_stats={"target_max_health": 500.0},
        )
        on_hit = abilities["W"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(110.0 / 3, abs=0.5)

    def test_w_scales_with_rank(self, vayne_data) -> None:
        """W on-hit damage increases with rank."""
        abilities_r1 = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 1, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        abilities_r5 = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        r1_dmg = abilities_r1["W"]["on_hit"]["damage_per_hit"]
        r5_dmg = abilities_r5["W"]["on_hit"]["damage_per_hit"]
        assert r5_dmg > r1_dmg

    def test_w_rank1_per_hit(self, vayne_data) -> None:
        """W rank 1: 6% of 2000 = 120 per proc, damage_per_hit = 40."""
        abilities = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 1, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        on_hit = abilities["W"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(120.0 / 3, abs=0.5)

    def test_w_no_direct_damage(self, vayne_data) -> None:
        """W should have no direct cast damage."""
        abilities = parse_abilities(
            vayne_data,
            9,
            0.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            target_stats=TARGET_2000_HP,
        )
        assert abilities["W"]["total_raw"] == 0.0


# ---------------------------------------------------------------------------
# E: Condemn
# ---------------------------------------------------------------------------


class TestECondemn:
    """Tests for E (Condemn) damage with wall bonus toggle."""

    def test_e_is_physical_damage(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 9)
        assert "E" in abilities
        assert abilities["E"]["damage_type"] == "physical"

    def test_e_has_cooldown(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 9)
        assert abilities["E"]["cooldown"] > 0

    def test_e_wall_damage_higher_than_no_wall(self, vayne_data) -> None:
        """E with wall should deal more damage than without."""
        stats = {
            "attack_damage": 200.0,
            "bonus_attack_damage": 100.0,
        }
        abilities_wall = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": True},
            champion_stats=stats,
        )
        abilities_no_wall = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": False},
            champion_stats=stats,
        )
        assert abilities_wall["E"]["total_raw"] > abilities_no_wall["E"]["total_raw"]

    def test_e_wall_is_default(self, vayne_data) -> None:
        """condemn_wall defaults to True."""
        stats = {
            "attack_damage": 200.0,
            "bonus_attack_damage": 100.0,
        }
        default = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_stats=stats,
        )
        wall = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": True},
            champion_stats=stats,
        )
        assert abs(default["E"]["total_raw"] - wall["E"]["total_raw"]) < 0.1

    def test_e_rank5_wall_damage_reference(self, vayne_data) -> None:
        """E rank 5 with wall, 100 bonus AD: 475 + 1.25 * 100 = 600."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": True},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 100.0,
            },
        )
        assert abilities["E"]["total_raw"] == pytest.approx(600.0, abs=1.0)

    def test_e_rank5_no_wall_damage_reference(self, vayne_data) -> None:
        """E rank 5 without wall, 100 bonus AD: 190 + 0.50 * 100 = 240."""
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": False},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 100.0,
            },
        )
        assert abilities["E"]["total_raw"] == pytest.approx(240.0, abs=1.0)


# ---------------------------------------------------------------------------
# R: Final Hour
# ---------------------------------------------------------------------------


class TestRFinalHour:
    """Tests for R (Final Hour) stat buff."""

    def test_r_deals_no_damage(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 11)
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_has_stat_buff(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 11)
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] > 0

    def test_r_rank1_bonus_ad(self, vayne_data) -> None:
        """R rank 1 grants 35 bonus AD."""
        abilities = parse_abilities(
            vayne_data,
            11,
            0.0,
            ability_ranks={"Q": 5, "W": 3, "E": 1, "R": 1},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            35.0,
            abs=1.0,
        )

    def test_r_rank3_bonus_ad(self, vayne_data) -> None:
        """R rank 3 grants 65 bonus AD."""
        abilities = parse_abilities(
            vayne_data,
            16,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 3, "R": 3},
            champion_stats={
                "attack_damage": 100.0,
                "bonus_attack_damage": 0.0,
            },
        )
        assert abilities["R"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(
            65.0,
            abs=1.0,
        )

    def test_r_buff_increases_q_damage(self, vayne_data) -> None:
        """Q damage should be higher when R is ranked (bonus AD applied)."""
        stats = {
            "attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
        }
        no_r = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_stats=dict(stats),
        )
        with_r = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=dict(stats),
        )
        assert with_r["Q"]["total_raw"] > no_r["Q"]["total_raw"]

    def test_r_buff_increases_e_damage(self, vayne_data) -> None:
        """E damage should be higher when R is ranked (bonus AD applied)."""
        stats = {
            "attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
        }
        no_r = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_stats=dict(stats),
        )
        with_r = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=dict(stats),
        )
        assert with_r["E"]["total_raw"] > no_r["E"]["total_raw"]


# ---------------------------------------------------------------------------
# R stat buff in fight engine
# ---------------------------------------------------------------------------


class TestRStatBuffInFightEngine:
    """Tests for R stat buff integration with the fight engine."""

    def test_stat_buff_applied_to_champion_stats(self, vayne_data, parse_at) -> None:
        """The fight engine should apply R's bonus AD to champion stats."""
        stats, abilities = parse_at(vayne_data, 11)
        original_ad = stats["attack_damage"]

        calculate_fight_damage(
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
        assert stats["attack_damage"] > original_ad

    def test_r_zero_damage_in_breakdown(self, vayne_data, parse_at) -> None:
        """R should appear in fight engine but contribute 0 damage."""
        stats, abilities = parse_at(vayne_data, 11)
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
        r_entry = result["breakdown"].get("R", {})
        assert r_entry.get("total_damage", 0.0) == 0.0


# ---------------------------------------------------------------------------
# Passive: Night Hunter (skip — movement speed only)
# ---------------------------------------------------------------------------


class TestPassiveNightHunter:
    """Passive should not be present in results (MS only)."""

    def test_passive_not_in_results(self, vayne_data, parse_at) -> None:
        _, abilities = parse_at(vayne_data, 9)
        assert "passive" not in abilities
        assert "P" not in abilities


# ---------------------------------------------------------------------------
# Champion options toggle behavior
# ---------------------------------------------------------------------------


class TestChampionOptions:
    """Tests for champion option toggles."""

    def test_default_condemn_wall(self, vayne_data) -> None:
        """Default: condemn_wall should be True."""
        stats = {
            "attack_damage": 200.0,
            "bonus_attack_damage": 100.0,
        }
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_stats=stats,
        )
        # E should use total (wall) damage by default
        assert abilities["E"]["total_raw"] == pytest.approx(600.0, abs=1.0)

    def test_condemn_wall_disabled(self, vayne_data) -> None:
        """With condemn_wall=False, E uses base damage only."""
        stats = {
            "attack_damage": 200.0,
            "bonus_attack_damage": 100.0,
        }
        abilities = parse_abilities(
            vayne_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
            champion_options={"condemn_wall": False},
            champion_stats=stats,
        )
        assert abilities["E"]["total_raw"] == pytest.approx(240.0, abs=1.0)
