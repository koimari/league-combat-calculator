"""Front-door tests for the rotation resolver.

The F2 and F3 suites keep the historical campaign cases and the broad
champion matrix.  These tests make the resolver easy to find by module name.
"""

from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.rotation_resolver import rank_ability_dps, resolve_cast_order


def test_unknown_empty_kit_uses_the_engine_default_order() -> None:
    order, rule = resolve_cast_order("Synthetic Fixture", {})

    assert order == list(DEFAULT_CAST_ORDER)
    assert rule is None


def test_dps_ranking_uses_the_effective_cooldown() -> None:
    ranked = rank_ability_dps(
        {
            "Q": {"total_raw": 100.0, "cooldown": 10.0},
            "W": {"total_raw": 100.0, "cooldown": 5.0},
        }
    )

    assert [slot for slot, *_ in ranked] == ["W", "Q"]
