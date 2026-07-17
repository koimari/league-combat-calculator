"""Tests for resistance and penetration primitives (src.calculator.resistance).

Covers apply_resistance and apply_magic_penetration -- the mitigation math
every damage path funnels through. (Lethality needs no conversion since
V14.1: it is 1:1 flat armor penetration, covered in test_stats.py.)
"""

from src.calculator.resistance import (
    apply_resistance,
    apply_magic_penetration,
    apply_armor_penetration,
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


class TestApplyArmorPenetration:
    """Tests for armor penetration calculations (flat pen = lethality)."""

    def test_no_penetration(self) -> None:
        assert apply_armor_penetration(100, 0, 0) == 100.0

    def test_flat_penetration_only(self) -> None:
        assert apply_armor_penetration(100, 20, 0) == 80.0

    def test_combined_penetration_percent_first(self) -> None:
        # 100 armor -> 30% pen -> 70 -> -20 flat -> 50
        result = apply_armor_penetration(100, 20, 0.30)
        assert abs(result - 50.0) < 0.01

    def test_lethality_cannot_reduce_armor_below_zero(self) -> None:
        # 20 lethality vs 10 armor floors at 0 -- it must never produce
        # negative armor (which apply_resistance would amplify).
        assert apply_armor_penetration(10, 20, 0) == 0.0
