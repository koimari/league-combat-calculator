"""Tests for the engine's generic champion path (GENERIC_SLOTS).

The classifier-driven slot map every unregistered champion runs on —
formerly generic_parser.py, now ``build_parser(GENERIC_SLOTS, ...)``.
Covers the scaling/classifier/skill-order building blocks, per-champion
generic behavior (Annie/Garen/Vayne shapes), and the mass-coverage
guarantees (every champion parses; >=95% with damage).
"""

import json
import pytest

from src.calculator.champions import GENERIC_SLOTS
from src.calculator.champions.engine import build_parser
from src.calculator.champions.scaling import resolve_scaling
from src.calculator.champions.attribute_classifier import (
    is_damage_attribute,
)
from src.calculator.champions.skill_orders import get_ability_rank


def parse_abilities(champ: dict, *args, **kwargs) -> dict:
    """Run a champion through the engine's generic slot map.

    The exact path the dispatcher takes for unregistered champions
    (Annie/Vayne below are registered — these tests deliberately
    exercise the generic path on their data).
    """
    return build_parser(GENERIC_SLOTS, champ.get("name", ""))(champ, *args, **kwargs)


@pytest.fixture(scope="module")
def champions_data() -> dict:
    """Load all champion data from JSON."""
    with open("data/champions.json") as f:
        return json.load(f)


def _find_champion(champions_data: dict, name: str) -> dict:
    """Find a champion by display name."""
    for _, champ in champions_data.items():
        if champ.get("name") == name:
            return champ
    raise KeyError(f"Champion '{name}' not found")


def _default_stats(**overrides: float) -> dict[str, float]:
    """Create a default champion stats dict for testing."""
    stats = {
        "attack_damage": 150.0,
        "bonus_attack_damage": 50.0,
        "base_attack_damage": 100.0,
        "ability_power": 200.0,
        "health": 2500.0,
        "bonus_health": 500.0,
        "armor": 80.0,
        "magic_resistance": 60.0,
        "max_mana": 1000.0,
        "bonus_mana": 400.0,
    }
    stats.update(overrides)
    return stats


def _default_target(**overrides: float) -> dict[str, float]:
    """Create a default target stats dict."""
    stats = {
        "target_max_health": 2500.0,
        "target_current_health": 2500.0,
        "target_missing_health": 0.0,
    }
    stats.update(overrides)
    return stats


# ---------------------------------------------------------------------------
# Scaling resolution tests
# ---------------------------------------------------------------------------


class TestScaling:
    """Tests for unit string scaling resolution."""

    def test_flat_damage(self) -> None:
        assert resolve_scaling("", 100.0) == 100.0

    def test_ap_scaling(self) -> None:
        stats = {"ability_power": 200.0}
        # 50% AP with 200 AP = 100
        assert resolve_scaling("% AP", 50.0, stats) == 100.0

    def test_ad_scaling(self) -> None:
        stats = {"attack_damage": 150.0}
        # 100% AD with 150 AD = 150
        assert resolve_scaling("% AD", 100.0, stats) == 150.0

    def test_bonus_ad_scaling(self) -> None:
        stats = {"bonus_attack_damage": 80.0}
        # 75% bonus AD with 80 bonus AD = 60
        assert resolve_scaling("% bonus AD", 75.0, stats) == 60.0

    def test_target_max_hp_scaling(self) -> None:
        target = {"target_max_health": 3000.0}
        # 10% target max HP = 300
        result = resolve_scaling(
            "% of target's maximum health",
            10.0,
            target_stats=target,
        )
        assert abs(result - 300.0) < 0.1

    def test_unknown_unit_returns_zero(self) -> None:
        assert resolve_scaling("bananas", 50.0) == 0.0

    def test_empty_unit_is_flat(self) -> None:
        assert resolve_scaling("  ", 42.0) == 42.0


# ---------------------------------------------------------------------------
# Attribute classifier tests
# ---------------------------------------------------------------------------


class TestAttributeClassifier:
    """Tests for damage attribute detection."""

    def test_magic_damage_is_damage(self) -> None:
        assert is_damage_attribute("Magic Damage") is True

    def test_physical_damage_is_damage(self) -> None:
        assert is_damage_attribute("Physical Damage") is True

    def test_bonus_damage_is_damage(self) -> None:
        assert is_damage_attribute("Bonus Physical Damage") is True

    def test_shield_is_not_damage(self) -> None:
        assert is_damage_attribute("Shield Strength") is False

    def test_slow_is_not_damage(self) -> None:
        assert is_damage_attribute("Slow") is False

    def test_total_damage_excluded(self) -> None:
        assert is_damage_attribute("Total Mixed Damage") is False

    def test_minion_damage_excluded(self) -> None:
        assert is_damage_attribute("Minion Damage") is False

    def test_monster_damage_excluded(self) -> None:
        assert is_damage_attribute("Monster Damage") is False

    def test_damage_reduction_excluded(self) -> None:
        assert is_damage_attribute("Damage Reduction") is False


# ---------------------------------------------------------------------------
# Skill order tests
# ---------------------------------------------------------------------------


class TestSkillOrder:
    """Tests for ability rank calculation."""

    def test_level_1_q_rank_1(self) -> None:
        assert get_ability_rank("Q", 1) == 1

    def test_level_6_r_rank_1(self) -> None:
        assert get_ability_rank("R", 6) == 1

    def test_level_11_r_rank_2(self) -> None:
        assert get_ability_rank("R", 11) == 2

    def test_level_16_r_rank_3(self) -> None:
        assert get_ability_rank("R", 16) == 3

    def test_level_9_q_max(self) -> None:
        assert get_ability_rank("Q", 9) == 5

    def test_level_18_all_maxed(self) -> None:
        assert get_ability_rank("Q", 18) == 5
        assert get_ability_rank("W", 18) == 5
        assert get_ability_rank("E", 18) == 5
        assert get_ability_rank("R", 18) == 3


# ---------------------------------------------------------------------------
# Generic parser integration tests
# ---------------------------------------------------------------------------


class TestGenericParserAnnie:
    """Test generic parser with Annie (simple AP mage)."""

    def test_q_damage(self, champions_data: dict) -> None:
        """Annie Q rank 5 at 200 AP: 260 + 80% AP = 420."""
        champ = _find_champion(champions_data, "Annie")
        result = parse_abilities(champ, 18, 200.0)
        assert "Q" in result
        assert abs(result["Q"]["total_raw"] - 420.0) < 1.0
        assert result["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, champions_data: dict) -> None:
        champ = _find_champion(champions_data, "Annie")
        result = parse_abilities(champ, 18, 200.0)
        assert result["Q"]["cooldown"] > 0

    def test_all_abilities_parsed(self, champions_data: dict) -> None:
        champ = _find_champion(champions_data, "Annie")
        result = parse_abilities(champ, 18, 200.0)
        assert "Q" in result
        assert "W" in result
        assert "R" in result


class TestGenericParserGaren:
    """Test generic parser with Garen (AD bruiser)."""

    def test_q_physical_damage(self, champions_data: dict) -> None:
        """Garen Q at rank 5 with 150 AD: 150 + 50%AD = 150+75 = 225."""
        champ = _find_champion(champions_data, "Garen")
        stats = _default_stats()
        result = parse_abilities(champ, 18, 0.0, champion_stats=stats)
        assert "Q" in result
        assert result["Q"]["damage_type"] == "physical"
        assert result["Q"]["total_raw"] > 0

    def test_r_true_damage(self, champions_data: dict) -> None:
        """Garen R deals true damage."""
        champ = _find_champion(champions_data, "Garen")
        stats = _default_stats()
        result = parse_abilities(champ, 18, 0.0, champion_stats=stats)
        assert "R" in result
        assert result["R"]["damage_type"] == "true"


class TestGenericParserVayne:
    """Test generic parser with Vayne (on-hit passive W)."""

    def test_w_is_on_hit(self, champions_data: dict) -> None:
        """Vayne W Silver Bolts should be parsed as on-hit, not castable."""
        champ = _find_champion(champions_data, "Vayne")
        target = _default_target(target_max_health=3000.0)
        result = parse_abilities(
            champ,
            18,
            0.0,
            champion_stats=_default_stats(),
            target_stats=target,
        )
        assert "W" in result
        assert "on_hit" in result["W"]

    def test_w_on_hit_damage(self, champions_data: dict) -> None:
        """Vayne W rank 5: 10% target max HP true damage."""
        champ = _find_champion(champions_data, "Vayne")
        target = _default_target(target_max_health=3000.0)
        result = parse_abilities(
            champ,
            18,
            0.0,
            champion_stats=_default_stats(),
            target_stats=target,
        )
        on_hit = result["W"]["on_hit"]
        assert on_hit["damage_type"] == "true"
        # 10% of 3000 = 300
        assert abs(on_hit["damage_per_hit"] - 300.0) < 1.0

    def test_q_is_castable(self, champions_data: dict) -> None:
        """Vayne Q Tumble is a normal castable ability."""
        champ = _find_champion(champions_data, "Vayne")
        result = parse_abilities(
            champ,
            18,
            0.0,
            champion_stats=_default_stats(),
            target_stats=_default_target(),
        )
        assert "Q" in result
        assert "on_hit" not in result["Q"]
        assert result["Q"]["damage_type"] == "physical"


class TestGenericParserMassCoverage:
    """Mass coverage test — verify all champions parse without errors."""

    def test_all_champions_parse_without_errors(
        self,
        champions_data: dict,
    ) -> None:
        """Every champion should parse without raising exceptions."""
        stats = _default_stats()
        target = _default_target()
        errors = []
        for cid, champ in champions_data.items():
            name = champ.get("name", cid)
            try:
                parse_abilities(
                    champ,
                    13,
                    200.0,
                    champion_stats=stats,
                    target_stats=target,
                )
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        assert errors == [], f"Champions with errors: {errors}"

    def test_most_champions_have_damage(
        self,
        champions_data: dict,
    ) -> None:
        """At least 95% of champions should have parseable damage."""
        stats = _default_stats()
        target = _default_target()
        has_damage = 0
        total = 0
        for _, champ in champions_data.items():
            total += 1
            result = parse_abilities(
                champ,
                13,
                200.0,
                champion_stats=stats,
                target_stats=target,
            )
            if any(v.get("total_raw", 0) > 0 or "on_hit" in v for v in result.values()):
                has_damage += 1
        coverage = has_damage / total
        assert coverage >= 0.95, (
            f"Only {has_damage}/{total} ({coverage:.1%}) champions have "
            f"parseable damage, expected >= 95%"
        )


class TestAbilityRankOverride:
    """Test that ability_ranks parameter overrides auto-calculated ranks."""

    def test_rank_override(self, champions_data: dict) -> None:
        champ = _find_champion(champions_data, "Annie")
        # Force all abilities to rank 1
        ranks = {"Q": 1, "W": 1, "E": 1, "R": 1}
        result = parse_abilities(champ, 18, 200.0, ability_ranks=ranks)
        # Q rank 1: 80 + 80% * 200 = 240
        assert abs(result["Q"]["total_raw"] - 240.0) < 1.0
