"""Tests for champion-layer primitives shared by all champion modules.

Covers calculate_ability_damage / effective_cooldown (champions.common) and
skill-order rank resolution (champions.skill_orders).
"""

from src.calculator.champions.common import (
    calculate_ability_damage,
    effective_cooldown,
)
from src.calculator.champions.skill_orders import get_ability_rank


class TestCalculateAbilityDamage:
    """Tests for raw ability damage calculation."""

    def test_base_only(self) -> None:
        assert calculate_ability_damage(100, 0.5, 0) == 100.0

    def test_with_scaling(self) -> None:
        result = calculate_ability_damage(100, 0.5, 200)
        assert result == 200.0

    def test_zero_base_with_scaling(self) -> None:
        result = calculate_ability_damage(0, 0.5, 200)
        assert result == 100.0


class TestGetAbilityRank:
    """Tests for skill order (Q > W > E, R at 6/11/16)."""

    def test_level_1_q_rank_1(self) -> None:
        assert get_ability_rank("Q", 1) == 1

    def test_level_6_q_rank_3(self) -> None:
        assert get_ability_rank("Q", 6) == 3

    def test_level_6_w_rank_1(self) -> None:
        assert get_ability_rank("W", 6) == 1

    def test_level_6_e_rank_1(self) -> None:
        assert get_ability_rank("E", 6) == 1

    def test_level_6_r_rank_1(self) -> None:
        assert get_ability_rank("R", 6) == 1

    def test_level_11_q_rank_5(self) -> None:
        assert get_ability_rank("Q", 11) == 5

    def test_level_11_w_rank_3(self) -> None:
        assert get_ability_rank("W", 11) == 3

    def test_level_11_e_rank_1(self) -> None:
        assert get_ability_rank("E", 11) == 1

    def test_level_11_r_rank_2(self) -> None:
        assert get_ability_rank("R", 11) == 2

    def test_level_18_all_maxed(self) -> None:
        assert get_ability_rank("Q", 18) == 5
        assert get_ability_rank("W", 18) == 5
        assert get_ability_rank("E", 18) == 5
        assert get_ability_rank("R", 18) == 3


class TestGetEffectiveCooldown:
    """Tests for cooldown reduction from ability haste."""

    def test_no_haste(self) -> None:
        assert effective_cooldown(7.0, 0.0) == 7.0

    def test_with_haste(self) -> None:
        result = effective_cooldown(7.0, 15.0)
        expected = 7.0 * 100 / 115
        assert abs(result - expected) < 0.01
