"""Tests for Caitlyn champion ability parsing and damage calculation.

Reference damage (200 total AD unless stated, level 13, 2000 HP target):
- P headshot bonus: total_AD x (level_pct + crit x (1 + bonus_crit_dmg)),
  level_pct = 0.60 (1-6) / 0.80 (7-12) / 1.00 (13+).
  200 AD, 100% crit, IE -> 200 x (1.00 + 1.30) = 460 per proc.
- Q rank 3: 130 + 1.65 x 200 = 460 physical (primary target, full damage).
- W: no standalone damage row; its 35-215 (+30% bonus AD) increase lands
  on the single trap headshot inside P.
- E rank 5, 0 AP: 280 magic. Rank 1, 100 AP: 80 + 80 = 160.
- R rank 2, 100 bonus AD: 475 + 100 = 575; crits at 0.3 effectiveness
  (100% crit -> 747.5; 100% crit + IE -> 799.25).
"""

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities as parse_abilities,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.pipeline import FightParams, run_fight

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_RANKED = {"Q": 5, "W": 5, "E": 5, "R": 3}

AD_200 = {
    "attack_damage": 200.0,
    "bonus_attack_damage": 100.0,
    "critical_strike_chance": 0.0,
}


@pytest.fixture
def infinity_edge() -> dict:
    """Infinity Edge item data (crit chance + 30% bonus crit damage)."""
    return get_item_by_name("Infinity Edge")


# ---------------------------------------------------------------------------
# Q: Piltover Peacemaker
# ---------------------------------------------------------------------------


class TestQPiltoverPeacemaker:
    """Q reads the primary 'Physical Damage' entry, never 'Reduced Damage'."""

    def test_q_is_physical(self, caitlyn_data, parse_at) -> None:
        _, abilities = parse_at(caitlyn_data, 9)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_rank3_damage_reference(self, caitlyn_data) -> None:
        """Q rank 3 with 200 total AD: 130 + 1.65 x 200 = 460."""
        abilities = parse_abilities(
            caitlyn_data,
            9,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 0, "R": 0},
            champion_stats=dict(AD_200),
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(460.0, abs=0.5)

    def test_q_rank5_uses_primary_not_reduced_damage(self, caitlyn_data) -> None:
        """Rank 5 with 200 AD: 210 + 2.05 x 200 = 620 (secondary would be 536)."""
        abilities = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks=ALL_RANKED,
            champion_stats=dict(AD_200),
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(620.0, abs=0.5)

    def test_q_cooldown_rank1(self, caitlyn_data) -> None:
        abilities = parse_abilities(
            caitlyn_data,
            1,
            0.0,
            ability_ranks={"Q": 1, "W": 0, "E": 0, "R": 0},
            champion_stats=dict(AD_200),
        )
        assert abilities["Q"]["cooldown"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# W: Yordle Snap Trap (no standalone damage row)
# ---------------------------------------------------------------------------


class TestWYordleSnapTrap:
    """W deals no damage itself: no W row; its value lives in P's trap."""

    def test_w_absent_from_results(self, caitlyn_data) -> None:
        abilities = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks=ALL_RANKED,
            champion_stats=dict(AD_200),
        )
        assert "W" not in abilities

    def test_w_rank_changes_trap_headshot_only(self, caitlyn_data) -> None:
        """Ranking W up increases only the passive (trap headshot) row."""
        low = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 5, "R": 3},
            champion_stats=dict(AD_200),
        )
        high = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks=ALL_RANKED,
            champion_stats=dict(AD_200),
        )
        assert high["passive"]["total_raw"] > low["passive"]["total_raw"]
        assert high["Q"]["total_raw"] == low["Q"]["total_raw"]


# ---------------------------------------------------------------------------
# E: 90 Caliber Net
# ---------------------------------------------------------------------------


class TestE90CaliberNet:
    """E is a simple magic damage read with an 80% AP ratio."""

    def test_e_is_magic(self, caitlyn_data, parse_at) -> None:
        _, abilities = parse_at(caitlyn_data, 9)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_rank5_no_ap(self, caitlyn_data) -> None:
        abilities = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks=ALL_RANKED,
            champion_stats=dict(AD_200),
        )
        assert abilities["E"]["total_raw"] == pytest.approx(280.0, abs=0.5)

    def test_e_rank1_with_ap(self, caitlyn_data) -> None:
        """E rank 1 with 100 AP: 80 + 0.80 x 100 = 160."""
        abilities = parse_abilities(
            caitlyn_data,
            3,
            100.0,
            ability_ranks={"Q": 1, "W": 0, "E": 1, "R": 0},
            champion_stats=dict(AD_200),
        )
        assert abilities["E"]["total_raw"] == pytest.approx(160.0, abs=0.5)

    def test_e_cooldown_rank1(self, caitlyn_data) -> None:
        abilities = parse_abilities(
            caitlyn_data,
            3,
            0.0,
            ability_ranks={"Q": 1, "W": 0, "E": 1, "R": 0},
            champion_stats=dict(AD_200),
        )
        assert abilities["E"]["cooldown"] == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# R: Ace in the Hole
# ---------------------------------------------------------------------------


class TestRAceInTheHole:
    """R: bonus-AD physical with 0.3 crit effectiveness (Akshan pattern)."""

    def test_r_is_physical_with_cooldown(self, caitlyn_data, parse_at) -> None:
        _, abilities = parse_at(caitlyn_data, 11)
        assert abilities["R"]["damage_type"] == "physical"
        assert abilities["R"]["cooldown"] == pytest.approx(90.0)

    def test_r_rank2_damage_reference(self, caitlyn_data) -> None:
        """R rank 2 with 100 bonus AD: 475 + 1.00 x 100 = 575."""
        abilities = parse_abilities(
            caitlyn_data,
            11,
            0.0,
            ability_ranks={"Q": 5, "W": 3, "E": 1, "R": 2},
            champion_stats=dict(AD_200),
        )
        assert abilities["R"]["total_raw"] == pytest.approx(575.0, abs=0.5)

    def test_r_part_declares_crit_effectiveness(self, caitlyn_data, parse_at) -> None:
        _, abilities = parse_at(caitlyn_data, 11)
        assert abilities["R"]["parts"][0].crit_effectiveness == pytest.approx(0.3)

    def test_r_full_crit_in_fight(self, caitlyn_data, attacker_stats, fight) -> None:
        """100% crit, no IE, 0 armor: 575 x 1.3 = 747.5."""
        stats = attacker_stats(
            attack_damage=200.0,
            bonus_attack_damage=100.0,
            critical_strike_chance=100.0,
        )
        abilities = parse_abilities(
            caitlyn_data,
            11,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 2},
            champion_stats=dict(stats),
        )
        result = fight(
            stats,
            {"R": abilities["R"]},
            target_armor=0.0,
            target_magic_resistance=0.0,
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(747.5)

    def test_r_full_crit_with_ie_in_fight(
        self, caitlyn_data, attacker_stats, fight, infinity_edge
    ) -> None:
        """100% crit + IE, 0 armor: 575 x (1 + 0.3 + 0.3 x 0.3) = 799.25."""
        stats = attacker_stats(
            attack_damage=200.0,
            bonus_attack_damage=100.0,
            critical_strike_chance=100.0,
        )
        abilities = parse_abilities(
            caitlyn_data,
            11,
            0.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 2},
            champion_stats=dict(stats),
        )
        result = fight(
            stats,
            {"R": abilities["R"]},
            items=[infinity_edge],
            target_armor=0.0,
            target_magic_resistance=0.0,
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(799.25)


# ---------------------------------------------------------------------------
# P: Headshot — one-rotation (per-cast) model
# ---------------------------------------------------------------------------


class TestHeadshotOneRotation:
    """Without a fight window, granted headshots are forced basic attacks:
    each carries the expected-crit base swing plus the headshot rider."""

    def test_absent_when_nothing_grants_a_headshot(self, caitlyn_data) -> None:
        """No autos, no E, no W trap: no headshot row."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 2},
            champion_stats=dict(AD_200),
        )
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_e_granted_headshot_is_swing_plus_bonus(self, caitlyn_data) -> None:
        """Level 13+, 200 AD, 0% crit: swing 200 + bonus 200 x 1.00 = 400."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 1, "R": 2},
            champion_stats=dict(AD_200),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(400.0)
        assert abilities["passive"]["damage_type"] == "physical"

    def test_level_bracket_60_percent(self, caitlyn_data) -> None:
        """Level 6: swing 200 + bonus 200 x 0.60 = 320."""
        abilities = parse_abilities(
            caitlyn_data,
            6,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 1, "R": 1},
            champion_stats=dict(AD_200),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(320.0)

    def test_level_bracket_80_percent(self, caitlyn_data) -> None:
        """Level 7: swing 200 + bonus 200 x 0.80 = 360."""
        abilities = parse_abilities(
            caitlyn_data,
            7,
            0.0,
            ability_ranks={"Q": 3, "W": 0, "E": 1, "R": 1},
            champion_stats=dict(AD_200),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(360.0)

    def test_trap_headshot_adds_w_increase(self, caitlyn_data) -> None:
        """W rank 1, 0 bonus AD: swing 200 + bonus 200 + trap increase 35."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 0, "R": 2},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 0.0,
                "critical_strike_chance": 0.0,
            },
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(435.0)

    def test_trap_plus_e_grant_two_forced_attacks(self, caitlyn_data) -> None:
        """W rank 3 (125 + 0.3 x 100 = 155) + one E grant, 200 AD:
        2 swings (400) + E bonus (200) + trap bonus (200 + 155) = 955."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 3, "E": 1, "R": 2},
            champion_stats=dict(AD_200),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(955.0)

    def test_headshot_crit_scaling_without_ie(self, caitlyn_data) -> None:
        """100% crit, base crit damage: bonus = 200 x (1.00 + 1.00) = 400;
        swing = 200 x 2.0 = 400 -> total 800."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 1, "R": 2},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 100.0,
                "critical_strike_chance": 100.0,
            },
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(800.0)

    def test_headshot_spec_example_full_crit_plus_ie(self, caitlyn_data) -> None:
        """Spec check: level 13+, 200 AD, 100% crit, IE (+0.3):
        headshot bonus = 200 x (1.00 + 1.30) = 460 raw physical."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 1, "R": 2},
            champion_stats={
                "attack_damage": 200.0,
                "bonus_attack_damage": 100.0,
                "critical_strike_chance": 100.0,
                "crit_damage_bonus": 0.3,
            },
        )
        bonus_part = abilities["passive"]["parts"][1]
        assert bonus_part.amount == pytest.approx(460.0)
        # The forced swing crits at full expected value: 200 x (1 + 1.3).
        swing_part = abilities["passive"]["parts"][0]
        assert swing_part.amount == pytest.approx(460.0)


# ---------------------------------------------------------------------------
# P: Headshot — timed-fight model
# ---------------------------------------------------------------------------

TIMED_10S = {"fight_duration_seconds": 10.0, "auto_attack_uptime": 1.0}


class TestHeadshotTimedFight:
    """With a fight window, headshots convert autos already in the auto
    stream: only the rider bonuses are emitted (no swing parts)."""

    def _stats(self, attack_speed: float = 1.2) -> dict:
        return {
            "attack_damage": 200.0,
            "bonus_attack_damage": 0.0,
            "critical_strike_chance": 0.0,
            "attack_speed": attack_speed,
        }

    def test_cadence_plus_grants(self, caitlyn_data) -> None:
        """12 autos -> 2 cadence procs; +1 E grant, +1 trap (W rank 1):
        3 x 200 + (200 + 35) = 835."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 1, "R": 2},
            champion_stats=self._stats(),
            champion_options=dict(TIMED_10S),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(835.0)

    def test_no_w_drops_the_trap_proc(self, caitlyn_data) -> None:
        """W unranked: 2 cadence + 1 E grant = 3 x 200 = 600."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 1, "R": 2},
            champion_stats=self._stats(),
            champion_options=dict(TIMED_10S),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(600.0)

    def test_procs_capped_by_auto_count(self, caitlyn_data) -> None:
        """1 auto in the window: only the trap conversion fires (235)."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 1, "R": 2},
            champion_stats=self._stats(attack_speed=0.5),
            champion_options={
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 0.2,
            },
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(235.0)

    def test_zero_uptime_grants_become_forced_attacks(self, caitlyn_data) -> None:
        """Zero uptime: no auto stream to convert, but the combo still
        forces its granted headshots — 1 E cast (16s cd over 10s) + 1
        trap, each swing + rider: 2 x 200 + 200 + 235 = 835."""
        abilities = parse_abilities(
            caitlyn_data,
            13,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 1, "R": 2},
            champion_stats=self._stats(),
            champion_options={
                "fight_duration_seconds": 10.0,
                "auto_attack_uptime": 0.0,
            },
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(835.0)
        assert "forced" in abilities["passive"]["detail"]

    def test_e_casts_on_cooldown_grant_more_headshots(self, caitlyn_data) -> None:
        """E rank 5 (8s cd) over 10s = 2 casts: 2 cadence + 2 E + 1 trap
        -> 4 x 200 + 235 = 1035."""
        abilities = parse_abilities(
            caitlyn_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 1, "E": 5, "R": 3},
            champion_stats=self._stats(),
            champion_options=dict(TIMED_10S),
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(1035.0)


# ---------------------------------------------------------------------------
# Hexoptics C44: Headshot is basic damage
# ---------------------------------------------------------------------------


class TestHexopticsBasicDamage:
    """Headshot (swing AND rider) is classified basic damage in-game, so
    Hexoptics C44 Magnification amplifies the whole passive row; spell
    rows (Q/E/R) are never amplified."""

    def test_one_rotation_headshot_amped(self, caitlyn_data, parse_at, fight) -> None:
        """Ranged amp 1.10 on the passive row; bonus shown on the info row."""
        stats, abilities = parse_at(caitlyn_data, 13)
        result = fight(
            stats,
            abilities,
            items=[{"name": "Hexoptics C44"}],
            target_armor=0.0,
            target_magic_resistance=0.0,
        )
        raw = abilities["passive"]["total_raw"]
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(
            raw * 1.10
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            abilities["Q"]["total_raw"]
        )
        amp_row = result["breakdown"]["basic_amp_Hexoptics C44"]
        assert amp_row["total_damage"] == pytest.approx(raw * 0.10)


# ---------------------------------------------------------------------------
# Fight-engine and pipeline integration
# ---------------------------------------------------------------------------


class TestFightIntegration:
    """Headshot rides the fight as a fixed proc entry."""

    def test_headshot_emits_an_event_ordered_ledger_for_optimizer(
        self, caitlyn_data
    ) -> None:
        """Forced Headshots are exact events, not an aggregate coarse proc."""
        result = run_fight(
            caitlyn_data,
            6,
            [],
            FightParams(
                target_health=4000.0,
                target_bonus_health=0.0,
                target_armor=80.0,
                target_magic_resistance=50.0,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                include_actives=True,
                cast_order=None,
                auto_attacks_only=False,
                ability_ranks={"Q": 3, "W": 1, "E": 1, "R": 1},
                champion_options=None,
                deterministic=True,
            ),
        )

        passive = result["breakdown"]["passive"]
        assert passive["damage_events"]
        assert sum(
            event["damage"] for event in passive["damage_events"]
        ) == pytest.approx(passive["total_damage"])
        assert result["timeline_coverage"]["complete"] is True
        assert "passive" in result["timeline_coverage"]["exact_sources"]
        assert "passive" not in result["timeline_coverage"]["coarse_sources"]

    def test_one_rotation_passive_row_matches_raw(
        self, caitlyn_data, parse_at, fight
    ) -> None:
        """0 armor: the passive breakdown equals its raw parts total."""
        stats, abilities = parse_at(caitlyn_data, 11)
        result = fight(
            stats,
            abilities,
            target_armor=0.0,
            target_magic_resistance=0.0,
        )
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(
            abilities["passive"]["total_raw"]
        )

    def test_run_fight_champion_stats_sane(self, caitlyn_data) -> None:
        """run_fight reports Caitlyn's stats panel untouched by parsing."""
        params = self._one_rotation_params()
        result = run_fight(caitlyn_data, 13, [], params)
        stats = result["champion_stats"]
        assert stats["attack_damage"] > 0
        assert "crit_damage_bonus" not in stats
        assert result["breakdown"]["passive"]["total_damage"] > 0

    def test_pipeline_surfaces_ie_crit_damage_to_headshot(
        self, caitlyn_data, infinity_edge
    ) -> None:
        """With IE, the pipeline prices headshots at +30% bonus crit damage.

        Level 13 (ranks Q5/W5/E1/R2), one rotation, 0 armor: 2 forced
        headshot attacks = 2 x swing + E bonus + (trap bonus + W increase),
        where swing = bonus = AD x (1 + crit x 1.3) at level 13+.
        """
        params = self._one_rotation_params(
            ability_ranks={"Q": 5, "W": 5, "E": 1, "R": 2}
        )
        result = run_fight(caitlyn_data, 13, [infinity_edge], params)
        stats = result["champion_stats"]
        ad = stats["attack_damage"]
        crit = min(stats["critical_strike_chance"] / 100.0, 1.0)
        assert crit > 0  # IE grants crit chance
        per_headshot = ad * (1.0 + crit * (1.0 + 0.3))
        w_increase = 215.0 + 0.3 * stats["bonus_attack_damage"]  # W rank 5
        expected = 2 * per_headshot + per_headshot + (per_headshot + w_increase)
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(expected)

    @staticmethod
    def _one_rotation_params(ability_ranks: dict | None = None) -> FightParams:
        return FightParams(
            target_health=2000.0,
            target_bonus_health=0.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            include_actives=False,
            cast_order=None,
            auto_attacks_only=False,
            ability_ranks=ability_ranks,
            champion_options=None,
            deterministic=True,
        )


# ---------------------------------------------------------------------------
# Options and assumptions metadata
# ---------------------------------------------------------------------------


class TestOptionsMeta:
    """The single E3 headshot pre-stack option, plus assumptions."""

    def test_pre_stacks_option_declared(self) -> None:
        meta = get_champion_options_meta("Caitlyn")
        assert [option["key"] for option in meta["options"]] == ["p_pre_stacks"]
        assert meta["options"][0]["min"] == 0
        assert meta["options"][0]["max"] == 5
        assert meta["options"][0]["default"] == 0

    def test_assumptions_documented(self) -> None:
        meta = get_champion_options_meta("Caitlyn")
        assert meta["assumptions"]
