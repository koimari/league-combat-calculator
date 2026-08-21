"""Damage attribute detection (champions/attribute_classifier.py)."""

from src.calculator.champions.attribute_classifier import is_damage_attribute


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
