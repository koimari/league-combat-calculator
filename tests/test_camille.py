"""Tests for Camille champion ability parsing and damage calculation.

Reference damage (wiki: https://wiki.leagueoflegends.com/en-us/Camille):
- Q (Precision Protocol) rank 5: next basic attack deals +20-40% total
  AD bonus physical; the delayed recast (Q2) doubles it to 40-80% and
  converts (36% + 4% per level, 100% from level 16) of the WHOLE attack
  (base swing + bonus + spellblade proc) to true damage. Neither Q
  attack can critically strike.
- W (Tactical Sweep) rank 5: 160 + 60% bonus AD physical; the outer
  cone adds (8% + 2.5% per 100 bonus AD) of target max health.
- E (Wall Dive) rank 5: 180 + 75% bonus AD physical + 60% bonus attack
  speed; cooldown lives on E[0] (Hookshot).
- R (The Hextech Ultimatum): no upfront damage — each basic attack on
  the trapped target deals 4/6/8% of its CURRENT health as bonus magic
  damage while the zone lasts (2.5/3.25/4s).
"""

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities as parse_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.resistance import apply_resistance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}

# 300 total AD (100 bonus) — the spec's reference statline.
STATS_300_AD = {
    "attack_damage": 300.0,
    "bonus_attack_damage": 100.0,
}

TARGET_3000 = {
    "target_max_health": 3000.0,
    "target_current_health": 3000.0,
    "target_missing_health": 0.0,
}


def _parse(data, ranks, level=18, stats=None, options=None, target=None):
    """Parse at explicit ranks with the reference statline."""
    return parse_abilities(
        data,
        level,
        0.0,
        ability_ranks=ranks,
        champion_options=options,
        champion_stats=dict(stats or STATS_300_AD),
        target_stats=dict(target or TARGET_3000),
    )


# ---------------------------------------------------------------------------
# Q: Precision Protocol (Q1 + delayed Q2 recast)
# ---------------------------------------------------------------------------


class TestQPrecisionProtocol:
    """Q1: +20-40% AD physical; Q2: doubled bonus, true-converted."""

    def test_q1_is_physical(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q1_rank5_bonus(self, camille_data) -> None:
        """Q1 rank 5 at 300 AD: 40% x 300 = 120 bonus physical."""
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["Q"]["total_raw"] == pytest.approx(120.0)

    def test_q1_rank1_bonus(self, camille_data) -> None:
        """Q1 rank 1 at 300 AD: 20% x 300 = 60."""
        abilities = _parse(camille_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(60.0)

    def test_q1_cannot_crit(self, camille_data) -> None:
        """Neither the bonus nor the forced swing has crit scaling."""
        abilities = _parse(camille_data, ALL_MAXED)
        for part in abilities["Q"]["parts"]:
            assert part.crit_effectiveness == 0.0
        for part in abilities["Q"]["empowers_next_auto"]["swing_parts"]:
            assert part.crit_effectiveness == 0.0

    def test_q1_swing_is_total_ad_physical(self, camille_data) -> None:
        """The forced swing carries the full 300 base-AD attack."""
        abilities = _parse(camille_data, ALL_MAXED)
        (swing,) = abilities["Q"]["empowers_next_auto"]["swing_parts"]
        assert swing.damage_type == "physical"
        assert swing.amount == pytest.approx(300.0)
        assert swing.basic_damage is True

    def test_q2_rank5_doubled_bonus(self, camille_data) -> None:
        """Q2 rank 5 at 300 AD: 80% x 300 = 240."""
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["Q2"]["total_raw"] == pytest.approx(240.0)

    def test_q2_is_recast_of_q(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["Q2"]["recast_of"] == "Q"

    def test_q2_fully_true_at_level_18(self, camille_data) -> None:
        """From level 16 the conversion is 100%: everything is true."""
        abilities = _parse(camille_data, ALL_MAXED, level=18)
        assert abilities["Q2"]["damage_type"] == "true"
        assert all(part.damage_type == "true" for part in abilities["Q2"]["parts"])
        for part in abilities["Q2"]["empowers_next_auto"]["swing_parts"]:
            assert part.damage_type == "true"
        assert abilities["Q2"]["spellblade_true_ratio"] == pytest.approx(1.0)

    def test_q2_split_at_level_9(self, camille_data) -> None:
        """Level 9: 36 + 4x9 = 72% true / 28% physical of the 240 bonus."""
        abilities = _parse(camille_data, ALL_MAXED, level=9)
        entry = abilities["Q2"]
        assert entry["damage_type"] == "mixed"
        true_total = sum(p.amount for p in entry["parts"] if p.damage_type == "true")
        phys_total = sum(
            p.amount for p in entry["parts"] if p.damage_type == "physical"
        )
        assert true_total == pytest.approx(0.72 * 240.0)
        assert phys_total == pytest.approx(0.28 * 240.0)
        assert entry["spellblade_true_ratio"] == pytest.approx(0.72)

    def test_q2_cannot_crit(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        entry = abilities["Q2"]
        for part in entry["parts"] + entry["empowers_next_auto"]["swing_parts"]:
            assert part.crit_effectiveness == 0.0

    def test_q_cooldowns(self, camille_data) -> None:
        """Q cooldown 9/8/7/6/5, shared by Q1 and Q2."""
        r1 = _parse(camille_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        r5 = _parse(camille_data, ALL_MAXED)
        assert r1["Q"]["cooldown"] == pytest.approx(9.0)
        assert r5["Q"]["cooldown"] == pytest.approx(5.0)
        assert r5["Q2"]["cooldown"] == pytest.approx(5.0)

    def test_one_rotation_q_rows_no_crit_at_full_crit(
        self, camille_data, parse_at
    ) -> None:
        """One-rotation Q rows are exactly swing + bonus even at 100%
        crit: Q1 = 420 physical (mitigated), Q2 = 540 fully true."""
        stats, abilities = parse_at(camille_data, 18)
        stats.update(STATS_300_AD)
        stats["critical_strike_chance"] = 100.0
        # Re-parse with the reference statline so swing parts match.
        abilities = _parse(camille_data, ALL_MAXED)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=3000,
                target_armor=100,
                target_magic_resistance=50,
                fight_duration_seconds=3.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        q1 = result["breakdown"]["Q"]["total_damage"]
        q2 = result["breakdown"]["Q2"]["total_damage"]
        assert q1 == pytest.approx(apply_resistance(420.0, 100.0))
        # Q2 is fully true at level 18 — no armor mitigation at all.
        assert q2 == pytest.approx(540.0)

    def test_timed_spellblade_proc_on_q2_is_true(self, camille_data, parse_at) -> None:
        """Trinity Force spellblade procs consumed by Q2 convert to true
        damage; other procs keep the item's physical type."""
        triforce = get_item_by_name("Trinity Force")
        stats, abilities = parse_at(camille_data, 18, items=[triforce])
        result = calculate_fight_damage(
            stats,
            abilities,
            [triforce],
            FightConfig(
                target_health=5000,
                target_armor=100,
                target_magic_resistance=50,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        breakdown = result["breakdown"]
        converted = breakdown["spellblade_Trinity Force_true"]
        assert converted["damage_type"] == "true"
        assert converted["count"] == breakdown["Q2"]["casts"]
        # Against 100 armor a true proc outdamages a physical proc.
        plain = breakdown["spellblade_Trinity Force"]
        assert converted["damage_per_hit"] > plain["damage_per_hit"]

    def test_one_rotation_spellblade_procs_on_both_q_attacks(
        self, camille_data, parse_at
    ) -> None:
        """One-rotation Q1/Q2 forced swings each consume a spellblade
        proc — Q's cadence matches Trinity's 1.5s ICD in-game. Q1's proc
        stays physical, Q2's converts to true (game-verified)."""
        triforce = get_item_by_name("Trinity Force")
        stats, abilities = parse_at(camille_data, 18, items=[triforce])
        result = calculate_fight_damage(
            stats,
            abilities,
            [triforce],
            FightConfig(
                target_health=5000,
                target_armor=100,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        breakdown = result["breakdown"]
        plain = breakdown["spellblade_Trinity Force"]
        converted = breakdown["spellblade_Trinity Force_true"]
        assert plain["count"] == 1
        assert plain["damage_type"] == "physical"
        assert converted["count"] == 1
        assert converted["damage_type"] == "true"
        # Spellblade = 200% base AD; the converted proc is unmitigated.
        assert converted["damage_per_hit"] == pytest.approx(
            2.0 * stats["base_attack_damage"]
        )


# ---------------------------------------------------------------------------
# W: Tactical Sweep
# ---------------------------------------------------------------------------


class TestWTacticalSweep:
    """W: inner cone base + optional outer-cone %maxHP sweet spot."""

    def test_w_is_physical(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["W"]["damage_type"] == "physical"

    def test_w_rank5_outer_cone_default(self, camille_data) -> None:
        """160 + 60 (60% x 100 bAD) + (9% + 2.5%) x 3000 = 565."""
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["W"]["total_raw"] == pytest.approx(565.0)

    def test_w_rank5_inner_only(self, camille_data) -> None:
        """Outer cone off: 160 + 60 = 220."""
        abilities = _parse(camille_data, ALL_MAXED, options={"w_outer_cone": False})
        assert abilities["W"]["total_raw"] == pytest.approx(220.0)

    def test_w_monster_values_never_leak(self, camille_data) -> None:
        """Only inner + outer champion values: with 0 bonus AD the total
        is 160 + 9% x 3000 = 430 — any monster-effect leak breaks this."""
        abilities = _parse(
            camille_data,
            ALL_MAXED,
            stats={"attack_damage": 200.0, "bonus_attack_damage": 0.0},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(430.0)

    def test_w_cooldown(self, camille_data) -> None:
        """W cooldown 12/11.5/11/10.5/10."""
        r1 = _parse(camille_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        r5 = _parse(camille_data, ALL_MAXED)
        assert r1["W"]["cooldown"] == pytest.approx(12.0)
        assert r5["W"]["cooldown"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# E: Hookshot / Wall Dive
# ---------------------------------------------------------------------------


class TestEHookshot:
    """E: Wall Dive damage + always-on attack-speed steroid."""

    def test_e_rank5_damage(self, camille_data) -> None:
        """180 + 75% x 100 bonus AD = 255 physical."""
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["E"]["damage_type"] == "physical"
        assert abilities["E"]["total_raw"] == pytest.approx(255.0)

    def test_e_cooldown_comes_from_hookshot(self, camille_data) -> None:
        """E[1] (Wall Dive) has no cooldown — E[0]'s 16/15/14/13/12."""
        r1 = _parse(camille_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(camille_data, ALL_MAXED)
        assert r1["E"]["cooldown"] == pytest.approx(16.0)
        assert r5["E"]["cooldown"] == pytest.approx(12.0)

    def test_e_attack_speed_buff(self, camille_data) -> None:
        """40-60% bonus attack speed as a stat_buff."""
        r1 = _parse(camille_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(camille_data, ALL_MAXED)
        assert r1["E"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(40.0)
        assert r5["E"]["stat_buff"]["bonus_attack_speed"] == pytest.approx(60.0)

    def test_e_buff_raises_fight_attack_speed(self, camille_data, parse_at) -> None:
        """The fight engine applies E's bonus AS to the champion stats
        panel (the Gnar UI-panel lesson)."""
        stats, abilities = parse_at(camille_data, 13)
        original_as = stats["attack_speed"]
        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        assert stats["attack_speed"] > original_as


# ---------------------------------------------------------------------------
# R: The Hextech Ultimatum
# ---------------------------------------------------------------------------


class TestRHextechUltimatum:
    """R: pure autos-only current-health rider — zero upfront damage."""

    def test_r_zero_upfront_damage(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        assert abilities["R"]["total_raw"] == 0.0
        assert abilities["R"]["parts"] == ()
        assert "detail" in abilities["R"]

    @pytest.mark.parametrize(
        ("rank", "pct", "window"), [(1, 4.0, 2.5), (2, 6.0, 3.25), (3, 8.0, 4.0)]
    )
    def test_r_rider_payload(self, camille_data, rank, pct, window) -> None:
        abilities = _parse(camille_data, {"Q": 0, "W": 0, "E": 0, "R": rank})
        rider = abilities["R"]["on_hit"]
        assert rider["damage_type"] == "magic"
        assert rider["current_health_percent"] == pytest.approx(pct)
        assert rider["proc_window"] == pytest.approx(window)

    def test_r_cooldown(self, camille_data) -> None:
        """R cooldown 140/115/90."""
        r1 = _parse(camille_data, {"Q": 0, "W": 0, "E": 0, "R": 1})
        r3 = _parse(camille_data, {"Q": 0, "W": 0, "E": 0, "R": 3})
        assert r1["R"]["cooldown"] == pytest.approx(140.0)
        assert r3["R"]["cooldown"] == pytest.approx(90.0)

    def test_r_zero_in_one_rotation_mode(self, camille_data, parse_at) -> None:
        """No autos -> no rider procs, R row stays zero (mode-consistent)."""
        stats, abilities = parse_at(camille_data, 18)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=3000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=3.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["R"]["total_damage"] == 0.0
        assert "on_hit_ability_R" not in result["breakdown"]

    def test_r_rider_procs_within_zone_in_timed_mode(
        self, camille_data, parse_at
    ) -> None:
        """Timed fight with autos: rider procs = autos landing inside the
        zone duration, each vs decaying current health from 3000 (first
        proc 8% x 3000 = 240 magic vs 0 MR)."""
        stats, abilities = parse_at(camille_data, 18)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=3000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        row = result["breakdown"]["on_hit_ability_R"]
        # E's stat buff mutates stats in place — fight-effective AS.
        autos_in_fight = int(stats["attack_speed"] * 8.0)
        # A swing at index i lands at i / AS; it procs iff it lands before
        # the zone expires (landing-time rule, not a floor of rate x window).
        autos_in_zone = max(
            1,
            len([i for i in range(autos_in_fight) if i / stats["attack_speed"] < 4.0]),
        )
        assert row["unit"] == "procs"
        assert row["damage_type"] == "magic"
        assert row["count"] == min(autos_in_zone, autos_in_fight)
        # First proc is a full 240; later procs decay with current HP.
        assert row["total_damage"] >= 240.0
        assert row["total_damage"] < 240.0 * row["count"]

    def test_r_rider_silent_in_auto_only_mode(self, camille_data, parse_at) -> None:
        """auto_attacks_only never casts R — the rider must not fire."""
        stats, abilities = parse_at(camille_data, 18)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=3000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                auto_attacks_only=True,
                deterministic=True,
            ),
        )
        assert "on_hit_ability_R" not in result["breakdown"]


# ---------------------------------------------------------------------------
# Passive / options metadata
# ---------------------------------------------------------------------------


class TestPassiveAndMeta:
    """P (Adaptive Defenses) is a shield; no standalone row in
    ``abilities`` — it rides W's ``self_shield_events`` payload (see
    tests/test_e8_shields.py) — but MODULE_COVERAGE reports it modeled,
    not out_of_scope (roadmap session 4 batch B); options declared."""

    def test_passive_not_in_results(self, camille_data, parse_at) -> None:
        _, abilities = parse_at(camille_data, 9)
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_slot_keys(self, camille_data) -> None:
        abilities = _parse(camille_data, ALL_MAXED)
        assert set(abilities) == {"Q", "Q2", "W", "E", "R"}

    def test_options_meta(self) -> None:
        meta = get_champion_options_meta("Camille")
        keys = {opt["key"] for opt in meta["options"]}
        assert keys == {"w_outer_cone"}
        assert meta["assumptions"]


class TestModuleCoverage:
    def test_all_five_slots_covered(self) -> None:
        from src.calculator.champions.camille import MODULE_COVERAGE

        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
