"""Unit string scaling resolution (champions/scaling.py)."""

from src.calculator.champions.scaling import resolve_scaling


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
