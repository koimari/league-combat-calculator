"""Tests for Bard champion ability parsing and damage calculation.

Reference damage (raw, pre-mitigation — meep formula is wiki prose since
the P[0] JSON has no effects/leveling):
- Meep on-hit: 30 + 6 * floor(chimes / 5) + 40% AP magic damage
  (0 AP: 36 @ 5 chimes, 48 @ 15, 60 @ 25, 72 @ 35, 90 @ 50;
  35 chimes + 100 AP: 112)
- Meep availability: min(autos, stock + floor(fight_duration / recharge))
  with independent chime breakpoints (verbatim wiki pp templates):
  stock 1-9 at 0/10/30/50/65/80/90/95/100, recharge 8-4s at 0/20/40/55/70
- Q rank 5 at 100 AP: 240 + 80 = 320 magic
"""

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities as parse_abilities,
)
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}

STATS_100AP = {
    "attack_damage": 100.0,
    "bonus_attack_damage": 0.0,
    "ability_power": 100.0,
}


def _parse(bard_data, ap=100.0, options=None, ranks=None):
    """Parse Bard at level 18 with explicit AP and champion options."""
    return parse_abilities(
        bard_data,
        18,
        ap,
        ability_ranks=ranks or dict(ALL_MAXED),
        champion_stats=dict(STATS_100AP, ability_power=ap),
        champion_options=options,
    )


def _fight(stats, abilities, **overrides):
    """Unmitigated deterministic fight (0 resistances) for exact numbers."""
    config = {
        "target_health": 5000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 10.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


def _meep(abilities):
    """The passive's emitted on-hit payload."""
    return abilities["passive"]["on_hit"]


# ---------------------------------------------------------------------------
# P: Traveler's Call (meeps)
# ---------------------------------------------------------------------------


class TestPassiveTravelersCall:
    """P: meep on-hit magic damage scaling with the chime counter."""

    def test_passive_present_with_on_hit(self, bard_data) -> None:
        abilities = _parse(bard_data)
        assert "passive" in abilities
        assert "on_hit" in abilities["passive"]

    def test_passive_damage_type_is_magic(self, bard_data) -> None:
        assert _meep(_parse(bard_data))["damage_type"] == "magic"

    def test_passive_no_direct_damage(self, bard_data) -> None:
        """The passive shell carries no castable damage."""
        assert _parse(bard_data)["passive"]["total_raw"] == 0.0

    @pytest.mark.parametrize(
        "chimes,expected",
        [(5, 36.0), (15, 48.0), (25, 60.0), (35, 72.0), (50, 90.0)],
    )
    def test_meep_damage_reference_no_ap(self, bard_data, chimes, expected) -> None:
        """Wiki reference values at 0 AP: 30 + 6 per 5 chimes."""
        abilities = _parse(bard_data, ap=0.0, options={"chimes": chimes})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(expected)

    def test_meep_damage_35_chimes_100ap(self, bard_data) -> None:
        """35 chimes + 100 AP: 72 + 40 = 112 per meep."""
        abilities = _parse(bard_data, ap=100.0, options={"chimes": 35})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(112.0)

    def test_meep_damage_uncapped_past_50_chimes(self, bard_data) -> None:
        """100 chimes at 0 AP: 30 + 6 * 20 = 150 (formula has no cap)."""
        abilities = _parse(bard_data, ap=0.0, options={"chimes": 100})
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(150.0)

    def test_default_chimes_is_35(self, bard_data) -> None:
        """No options -> the declared default (35 chimes, 72 at 0 AP)."""
        abilities = _parse(bard_data, ap=0.0)
        assert _meep(abilities)["damage_per_hit"] == pytest.approx(72.0)

    @pytest.mark.parametrize(
        "chimes,stock",
        [
            # Every boundary of {{pp|1 to 9 for 9|0;10;30;50;65;80;90;95;100}}
            (0, 1),
            (9, 1),
            (10, 2),
            (29, 2),
            (30, 3),
            (49, 3),
            (50, 4),
            (64, 4),
            (65, 5),
            (79, 5),
            (80, 6),
            (89, 6),
            (90, 7),
            (94, 7),
            (95, 8),
            (99, 8),
            (100, 9),
        ],
    )
    def test_meep_stock_tiers(self, bard_data, chimes, stock) -> None:
        """Without a fight window, max_procs is the stocked meeps only."""
        abilities = _parse(bard_data, options={"chimes": chimes})
        assert _meep(abilities)["max_procs"] == stock

    @pytest.mark.parametrize(
        "chimes,expected",
        [
            # Every boundary of {{pp|8 to 4 for 5|0;20;40;55;70}} over a
            # 10s window: expected = stock + floor(10 / recharge).
            (0, 1 + 1),  # stock 1, 8s: floor(10/8) = 1
            (19, 2 + 1),  # stock 2, 8s: 1
            (20, 2 + 1),  # stock 2, 7s: floor(10/7) = 1
            (39, 3 + 1),  # stock 3, 7s: 1
            (40, 3 + 1),  # stock 3, 6s: floor(10/6) = 1
            (54, 4 + 1),  # stock 4, 6s: 1
            (55, 4 + 2),  # stock 4, 5s: floor(10/5) = 2
            (69, 5 + 2),  # stock 5, 5s: 2
            (70, 5 + 2),  # stock 5, 4s: floor(10/4) = 2
        ],
    )
    def test_meep_recharge_over_fight_window(self, bard_data, chimes, expected) -> None:
        """Timed fights add floor(fight_duration / recharge) meeps."""
        abilities = _parse(
            bard_data,
            options={"chimes": chimes, "fight_duration_seconds": 10.0},
        )
        assert _meep(abilities)["max_procs"] == expected


# ---------------------------------------------------------------------------
# Q: Cosmic Binding
# ---------------------------------------------------------------------------


class TestQCosmicBinding:
    """Q: one clean magic hit on the primary target."""

    def test_q_is_magic_damage(self, bard_data) -> None:
        assert _parse(bard_data)["Q"]["damage_type"] == "magic"

    def test_q_rank5_reference(self, bard_data) -> None:
        """Rank 5 at 100 AP: 240 + 80 = 320 magic."""
        assert _parse(bard_data)["Q"]["total_raw"] == pytest.approx(320.0)

    def test_q_rank1_reference(self, bard_data) -> None:
        """Rank 1 at 0 AP: 80 magic."""
        abilities = _parse(bard_data, ap=0.0, ranks={"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(80.0)

    def test_q_cooldown(self, bard_data) -> None:
        """Cooldown 11/10/9/8/7."""
        assert _parse(bard_data)["Q"]["cooldown"] == pytest.approx(7.0)
        rank1 = _parse(bard_data, ranks={"Q": 1, "W": 0, "E": 0, "R": 0})
        assert rank1["Q"]["cooldown"] == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# W / E / R: zero-damage state rows (roadmap session 2, 2026-08-20)
# ---------------------------------------------------------------------------


class TestNonDamageSlots:
    """W (ally heal), E (portal), R (stasis) deal no enemy damage but each
    emits an explicit, user-visible zero-damage row (module_helpers.no_damage)
    instead of staying silently absent — same pattern used across dozens of
    other champion modules (e.g. janna.py, milio.py) for utility slots."""

    @pytest.mark.parametrize("slot", ["W", "E", "R"])
    def test_slot_present_zero_damage(self, bard_data, slot) -> None:
        entry = _parse(bard_data)[slot]
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]

    def test_w_reason_cites_heal_not_damage(self, bard_data) -> None:
        entry = _parse(bard_data)["W"]
        assert entry["name"] == "Caretaker's Shrine"
        assert "heal" in entry["detail"].lower()

    def test_e_reason_cites_zero_leveling(self, bard_data) -> None:
        entry = _parse(bard_data)["E"]
        assert entry["name"] == "Magical Journey"
        assert "leveling" in entry["detail"].lower()

    def test_r_reason_cites_zero_proc_true_damage(self, bard_data) -> None:
        entry = _parse(bard_data)["R"]
        assert entry["name"] == "Tempered Fate"
        assert "0" in entry["detail"] and "true damage" in entry["detail"]


# ---------------------------------------------------------------------------
# Options metadata
# ---------------------------------------------------------------------------


class TestOptionsMeta:
    """Chime counter is served to the frontend with the parse-path default."""

    def test_chimes_option_declared(self) -> None:
        meta = get_champion_options_meta("Bard")
        (chimes,) = [o for o in meta["options"] if o["key"] == "chimes"]
        assert chimes["type"] == "int"
        assert chimes["default"] == 35
        assert chimes["min"] == 0
        assert chimes["max"] == 200

    def test_skill_order_q_maxed_first(self) -> None:
        assert get_ability_rank("Q", 9, "Bard") == 5


# ---------------------------------------------------------------------------
# Fight-engine integration (max_procs cap)
# ---------------------------------------------------------------------------


class TestFightEngineIntegration:
    """Meep availability caps empowered autos in the fight sim."""

    def _passive_only(self, bard_data, stats, options=None):
        return parse_abilities(
            bard_data,
            18,
            stats["ability_power"],
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options=options,
        )

    def test_meeps_capped_by_availability(self, bard_data, attacker_stats) -> None:
        """10 autos over 10s, 35 chimes: 3 stock + floor(10/7) = 4 meeps
        at 72 raw each -> 288 unmitigated."""
        stats = attacker_stats()
        abilities = self._passive_only(
            bard_data,
            stats,
            options={"chimes": 35, "fight_duration_seconds": 10.0},
        )
        result = _fight(stats, abilities)
        meeps = result["breakdown"]["on_hit_ability_passive"]
        assert meeps["count"] == 4
        assert meeps["total_damage"] == pytest.approx(4 * 72.0, abs=0.1)

    def test_meeps_capped_by_autos(self, bard_data, attacker_stats) -> None:
        """3 autos (30% uptime) with 4 meeps available -> only 3 land."""
        stats = attacker_stats()
        abilities = self._passive_only(
            bard_data,
            stats,
            options={"chimes": 35, "fight_duration_seconds": 10.0},
        )
        result = _fight(stats, abilities, auto_attack_uptime=0.3)
        meeps = result["breakdown"]["on_hit_ability_passive"]
        assert meeps["count"] == 3
        assert meeps["total_damage"] == pytest.approx(3 * 72.0, abs=0.1)

    def test_one_rotation_uses_stock_only(self, bard_data, attacker_stats) -> None:
        """No fight-window option (one-rotation model): stock 3 meeps
        empower 3 of the 10 autos."""
        stats = attacker_stats()
        abilities = self._passive_only(bard_data, stats, options={"chimes": 35})
        result = _fight(stats, abilities, one_rotation=True)
        meeps = result["breakdown"]["on_hit_ability_passive"]
        assert meeps["count"] == 3
        assert meeps["total_damage"] == pytest.approx(3 * 72.0, abs=0.1)

    def test_regression_10_chimes_7s_fight_two_meeps(
        self, bard_data, attacker_stats
    ) -> None:
        """User repro: 10 chimes, 7s timed fight -> exactly 2 meep autos
        (stock 2 + floor(7/8) = 0 recharges), 42 raw each at 0 AP."""
        stats = attacker_stats()
        abilities = self._passive_only(
            bard_data,
            stats,
            options={"chimes": 10, "fight_duration_seconds": 7.0},
        )
        result = _fight(stats, abilities, fight_duration_seconds=7.0)
        meeps = result["breakdown"]["on_hit_ability_passive"]
        assert meeps["count"] == 2
        assert meeps["total_damage"] == pytest.approx(2 * 42.0, abs=0.1)
