"""Tests for resistance and penetration primitives (src.calculator.resistance).

Covers apply_resistance, apply_magic_penetration, and the lethality-to-flat-pen
conversion -- the mitigation math every damage path funnels through.
"""

from src.calculator.resistance import (
    apply_resistance,
    apply_magic_penetration,
    lethality_to_flat_pen,
)


class TestApplyResistance:
    """Tests for damage mitigation from armor/MR."""

    def test_zero_resistance(self) -> None:
        assert apply_resistance(100, 0) == 100.0

    def test_100_resistance_halves_damage(self) -> None:
        assert apply_resistance(100, 100) == 50.0

    def test_200_resistance(self) -> None:
        result = apply_resistance(300, 200)
        assert abs(result - 100.0) < 0.01

    def test_negative_resistance_amplifies(self) -> None:
        result = apply_resistance(100, -50)
        assert result > 100.0

    def test_zero_damage_returns_zero(self) -> None:
        assert apply_resistance(0, 100) == 0.0


class TestApplyMagicPenetration:
    """Tests for magic penetration calculations."""

    def test_no_penetration(self) -> None:
        assert apply_magic_penetration(100, 0, 0) == 100.0

    def test_flat_penetration_only(self) -> None:
        assert apply_magic_penetration(100, 12, 0) == 88.0

    def test_percent_penetration_only(self) -> None:
        result = apply_magic_penetration(100, 0, 0.40)
        assert abs(result - 60.0) < 0.01

    def test_combined_penetration_percent_first(self) -> None:
        # 100 MR -> 40% pen -> 60 -> -12 flat -> 48
        result = apply_magic_penetration(100, 12, 0.40)
        assert abs(result - 48.0) < 0.01

    def test_cannot_go_below_zero(self) -> None:
        result = apply_magic_penetration(10, 50, 0)
        assert result == 0.0


class TestLethalityToFlatPen:
    """Tests for the lethality → flat armor pen conversion."""

    def test_level_1_gives_60_percent(self) -> None:
        # 0.6 + 0.4 * 1/18 = 0.6222...
        result = lethality_to_flat_pen(18, 1)
        assert abs(result - 18 * (0.6 + 0.4 / 18)) < 1e-9

    def test_level_18_gives_full_value(self) -> None:
        assert lethality_to_flat_pen(30, 18) == 30.0

    def test_level_above_18_clamps(self) -> None:
        assert lethality_to_flat_pen(30, 20) == lethality_to_flat_pen(30, 18)

    def test_level_9_midpoint(self) -> None:
        # 0.6 + 0.4 * 9/18 = 0.8
        assert abs(lethality_to_flat_pen(10, 9) - 8.0) < 1e-9

    def test_zero_lethality(self) -> None:
        assert lethality_to_flat_pen(0, 12) == 0.0
