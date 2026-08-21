"""Tests for Jarvan IV custom champion module.

Reference damage (hand-derived from the wiki):
- Q rank 3 with 100 bonus AD: 170 + 1.45*100 = 315 physical
- Q armor reduction: 10/14/18/22/26% of target's armor by rank
- E rank 5 with 0 AP: 240 magic; bonus AS 30% (60% near the flag)
- R rank 2 with 100 bonus AD: 325 + 1.80*100 = 505 physical
- P: 8% current HP (min 20) physical, per-target CD 6/5/4/3s at
  levels 1/6/11/16 — proc schedule derived from the fight timeline
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import (
    FightConfig,
    _schedule_cooldown_procs,
    calculate_fight_damage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NO_AD = {"attack_damage": 80.0, "bonus_attack_damage": 0.0}
BONUS_100_AD = {"attack_damage": 180.0, "bonus_attack_damage": 100.0}


def _fight_config(**overrides) -> FightConfig:
    """Deterministic all-autos fight vs a squishy 2000 HP / 0-resist dummy."""
    config = {
        "target_health": 2000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 10.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    return FightConfig(**config)


# ---------------------------------------------------------------------------
# Q: Dragon Strike
# ---------------------------------------------------------------------------


class TestQDragonStrike:
    """Q damage and the option-gated armor reduction debuff."""

    def test_q_damage_reference(self, jarvan_iv_data) -> None:
        """Q rank 3 with 100 bonus AD: 170 + 145 = 315 physical."""
        abilities = parse_abilities(
            jarvan_iv_data,
            5,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
            champion_stats=dict(BONUS_100_AD),
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(315.0, abs=1.0)
        assert abilities["Q"]["damage_type"] == "physical"
        assert abilities["Q"]["cooldown"] > 0

    def test_q_armor_shred_default_on(self, jarvan_iv_data) -> None:
        """Shred present by default, armor-only (no MR component)."""
        abilities = parse_abilities(
            jarvan_iv_data,
            9,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
            champion_stats=dict(NO_AD),
        )
        debuff = abilities["Q"]["target_debuff"]
        assert debuff == {
            "armor_reduction_percent": pytest.approx(18.0),
            "duration": pytest.approx(3.0),
        }

    def test_q_armor_shred_scales_with_rank(self, jarvan_iv_data) -> None:
        """Armor reduction: 10/18/26% at ranks 1/3/5."""
        expected = {1: 10.0, 3: 18.0, 5: 26.0}
        for rank, pct in expected.items():
            abilities = parse_abilities(
                jarvan_iv_data,
                9,
                0.0,
                ability_ranks={"Q": rank, "W": 0, "E": 0, "R": 0},
                champion_stats=dict(NO_AD),
            )
            debuff = abilities["Q"]["target_debuff"]
            assert debuff["armor_reduction_percent"] == pytest.approx(pct)

    def test_q_shred_disabled(self, jarvan_iv_data) -> None:
        abilities = parse_abilities(
            jarvan_iv_data,
            9,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
            champion_options={"q_armor_shred": False},
            champion_stats=dict(NO_AD),
        )
        assert "target_debuff" not in abilities["Q"]


# ---------------------------------------------------------------------------
# W: Golden Aegis (zero-damage cast row; the shield rides the scanner)
# ---------------------------------------------------------------------------


class TestWGoldenAegis:
    """W deals no direct damage; the row exists to carry the self-shield."""

    def test_w_emits_zero_damage_row(self, jarvan_iv_data, parse_at) -> None:
        _, abilities = parse_at(jarvan_iv_data, 18)
        assert abilities["W"]["name"] == "Golden Aegis"
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)
        assert abilities["W"]["parts"] == ()

    def test_w_absent_at_rank_zero(self, jarvan_iv_data) -> None:
        abilities = parse_abilities(
            jarvan_iv_data,
            5,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
            champion_stats=dict(NO_AD),
        )
        assert "W" not in abilities


# ---------------------------------------------------------------------------
# E: Demacian Standard
# ---------------------------------------------------------------------------


class TestEDemacianStandard:
    """E active magic damage and the near-flag doubled AS buff."""

    def test_e_damage_reference(self, jarvan_iv_data) -> None:
        """E rank 5 with 0 AP: 240 magic."""
        abilities = parse_abilities(
            jarvan_iv_data,
            13,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=dict(NO_AD),
        )
        assert abilities["E"]["total_raw"] == pytest.approx(240.0, abs=1.0)
        assert abilities["E"]["damage_type"] == "magic"
        assert abilities["E"]["cooldown"] > 0

    def test_e_scales_with_ap(self, jarvan_iv_data) -> None:
        """E has an 80% AP ratio."""
        abilities = parse_abilities(
            jarvan_iv_data,
            13,
            100.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=dict(NO_AD),
        )
        assert abilities["E"]["total_raw"] == pytest.approx(320.0, abs=1.0)

    def test_e_bonus_as_doubled_near_flag(self, jarvan_iv_data) -> None:
        """Default (near flag): rank 5 AS buff is 60%, not 30%."""
        abilities = parse_abilities(
            jarvan_iv_data,
            13,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=dict(NO_AD),
        )
        assert abilities["E"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)

    def test_e_bonus_as_away_from_flag(self, jarvan_iv_data) -> None:
        """near_flag off: rank 1 buff is the plain aura 20%."""
        abilities = parse_abilities(
            jarvan_iv_data,
            13,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 1, "R": 0},
            champion_options={"near_flag": False},
            champion_stats=dict(NO_AD),
        )
        assert abilities["E"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# R: Cataclysm
# ---------------------------------------------------------------------------


class TestRCataclysm:
    def test_r_damage_reference(self, jarvan_iv_data) -> None:
        """R rank 2 with 100 bonus AD: 325 + 180 = 505 physical."""
        abilities = parse_abilities(
            jarvan_iv_data,
            13,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 2},
            champion_stats=dict(BONUS_100_AD),
        )
        assert abilities["R"]["total_raw"] == pytest.approx(505.0, abs=1.0)
        assert abilities["R"]["damage_type"] == "physical"
        assert abilities["R"]["cooldown"] > 0


# ---------------------------------------------------------------------------
# P: Martial Cadence (parse shape)
# ---------------------------------------------------------------------------


class TestPassiveParse:
    def test_passive_on_hit_payload(self, jarvan_iv_data, parse_at) -> None:
        _, abilities = parse_at(jarvan_iv_data, 9)
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["damage_type"] == "physical"
        assert on_hit["current_health_percent"] == pytest.approx(8.0)
        assert on_hit["min_damage"] == pytest.approx(20.0)

    def test_passive_cooldown_by_level(self, jarvan_iv_data, parse_at) -> None:
        """Per-target CD: 6/5/4/3s with breakpoints at levels 1/6/11/16."""
        expected = {1: 6.0, 5: 6.0, 6: 5.0, 11: 4.0, 16: 3.0, 18: 3.0}
        for level, cooldown in expected.items():
            _, abilities = parse_at(jarvan_iv_data, level)
            assert abilities["passive"]["on_hit"]["proc_cooldown"] == pytest.approx(
                cooldown
            ), f"level {level}"


# ---------------------------------------------------------------------------
# Proc scheduler unit tests
# ---------------------------------------------------------------------------


class TestCooldownProcScheduler:
    """_schedule_cooldown_procs: first swing procs, then CD-gated re-procs.

    The scheduler consumes the authored per-swing schedule — the same one
    that stamps damage events — so scheduling decisions and stamped times
    can never diverge.
    """

    def test_one_auto_per_second_cd6(self) -> None:
        """Autos at t=0..9, CD 6: procs at t=0 and t=6."""
        swings = [float(i) for i in range(10)]
        assert _schedule_cooldown_procs(swings, 6.0) == [0, 6]

    def test_fractional_spacing(self) -> None:
        """2 autos/s (t=i*0.5), CD 3: procs at t=0 and t=3 (auto 6)."""
        swings = [i * 0.5 for i in range(10)]
        assert _schedule_cooldown_procs(swings, 3.0) == [0, 6]

    def test_cooldown_not_multiple_of_spacing(self) -> None:
        """1.375 autos/s, CD 5: first auto at/after t=5 is index 7."""
        swings = [i / 1.375 for i in range(14)]
        assert _schedule_cooldown_procs(swings, 5.0) == [0, 7]

    def test_no_autos_no_procs(self) -> None:
        assert not _schedule_cooldown_procs([], 6.0)

    def test_buffed_opening_window_schedules_from_real_swing_times(self) -> None:
        """An empowered attack-speed opening compresses the early swings.

        A uniform 1/s reading of the same seven swings would proc on
        [0, 2, 4, 6]; the authored schedule lands the early swings faster,
        so CD=2.0 re-procs at t=2.4 (index 4) and t=4.4 (index 6).
        """
        swings = [0.0, 0.4, 0.8, 1.2, 2.4, 3.4, 4.4]
        assert _schedule_cooldown_procs(swings, 2.0) == [0, 4, 6]


# ---------------------------------------------------------------------------
# Fight engine integration
# ---------------------------------------------------------------------------


def _parse_for_fight(data, stats, level, ranks, options=None):
    """Parse abilities with the stats dict a fight will also receive."""
    return parse_abilities(
        data,
        level,
        0.0,
        ability_ranks=ranks,
        champion_options=options,
        champion_stats=stats,
    )


class TestFightEngineIntegration:
    """Passive proc scheduling, near-flag AS, and Q shred at fight time."""

    def test_passive_procs_on_decaying_hp(self, jarvan_iv_data, attacker_stats) -> None:
        """Level 1, AS 1.0, 10s vs 2000 HP / 0 armor: procs at t=0 and t=6.

        Proc 1: 8% * 2000 = 160. Autos (100 dmg) and the proc then decay
        HP to 1240 by t=6, so proc 2 = 8% * 1240 = 99.2. Total 259.2.
        """
        stats = attacker_stats(level=1)
        abilities = _parse_for_fight(
            jarvan_iv_data, stats, 1, {"Q": 0, "W": 0, "E": 0, "R": 0}
        )
        result = calculate_fight_damage(stats, abilities, [], _fight_config())
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(259.2, abs=0.1)
        assert row["damage_type"] == "physical"

    def test_passive_minimum_damage_floor(self, jarvan_iv_data, attacker_stats) -> None:
        """Vs a 100 HP target, 8% = 8 raw is floored to the 20 minimum."""
        stats = attacker_stats(level=1)
        abilities = _parse_for_fight(
            jarvan_iv_data, stats, 1, {"Q": 0, "W": 0, "E": 0, "R": 0}
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            _fight_config(target_health=100.0, fight_duration_seconds=1.0),
        )
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(20.0, abs=0.01)

    def test_passive_procs_mitigated_by_armor(
        self, jarvan_iv_data, attacker_stats
    ) -> None:
        """First proc vs 100 armor: 160 raw -> 80 mitigated."""
        stats = attacker_stats(level=1)
        abilities = _parse_for_fight(
            jarvan_iv_data, stats, 1, {"Q": 0, "W": 0, "E": 0, "R": 0}
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            _fight_config(target_armor=100.0, fight_duration_seconds=1.0),
        )
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["total_damage"] == pytest.approx(80.0, abs=0.01)

    def test_near_flag_raises_auto_count_and_damage(
        self, jarvan_iv_data, attacker_stats
    ) -> None:
        """E's doubled AS buff: 1.0 + 0.625*0.6 = 1.375 AS -> 13 autos in
        10s, vs 1.1875 AS -> 11 autos with near_flag off."""
        stats_near = attacker_stats(level=9)
        abilities_near = _parse_for_fight(
            jarvan_iv_data, stats_near, 9, {"Q": 0, "W": 0, "E": 5, "R": 0}
        )
        result_near = calculate_fight_damage(
            stats_near, abilities_near, [], _fight_config()
        )

        stats_away = attacker_stats(level=9)
        abilities_away = _parse_for_fight(
            jarvan_iv_data,
            stats_away,
            9,
            {"Q": 0, "W": 0, "E": 5, "R": 0},
            options={"near_flag": False},
        )
        result_away = calculate_fight_damage(
            stats_away, abilities_away, [], _fight_config()
        )

        assert result_near["breakdown"]["auto_attacks"]["count"] == 13
        assert result_away["breakdown"]["auto_attacks"]["count"] == 11
        assert result_near["total_damage"] > result_away["total_damage"]

    def test_q_shred_applies_to_post_q_damage(
        self, jarvan_iv_data, attacker_stats
    ) -> None:
        """Q rank 5 shreds 26% of 20 armor -> 14.8: autos mitigate at
        100/(100+14.8) = 87.11 per hit (vs 83.33 unshredded)."""
        stats = attacker_stats(level=9)
        abilities = _parse_for_fight(
            jarvan_iv_data, stats, 9, {"Q": 5, "W": 0, "E": 0, "R": 0}
        )
        result = calculate_fight_damage(
            stats, abilities, [], _fight_config(target_armor=20.0)
        )
        autos = result["breakdown"]["auto_attacks"]
        assert autos["damage_per_hit"] == pytest.approx(100.0 * 100 / 114.8, abs=0.05)

        abilities_off = _parse_for_fight(
            jarvan_iv_data,
            stats,
            9,
            {"Q": 5, "W": 0, "E": 0, "R": 0},
            options={"q_armor_shred": False},
        )
        result_off = calculate_fight_damage(
            stats, abilities_off, [], _fight_config(target_armor=20.0)
        )
        autos_off = result_off["breakdown"]["auto_attacks"]
        assert autos_off["damage_per_hit"] == pytest.approx(100.0 * 100 / 120, abs=0.05)
        assert result["total_damage"] > result_off["total_damage"]
