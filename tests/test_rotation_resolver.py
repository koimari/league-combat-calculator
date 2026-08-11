"""Front-door tests for the rotation resolver.

The F2 and F3 suites keep the historical campaign cases and the broad
champion matrix.  These tests make the resolver easy to find by module name.
"""

from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import fetch_champion_data
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


def test_syndra_100_stack_execute_places_r_last() -> None:
    syndra = next(
        champion
        for champion in fetch_champion_data().values()
        if champion.get("name") == "Syndra"
    )
    stats = {"attack_damage": 80.0, "ability_power": 200.0}
    options = {"splinters": 100, "r_spheres": 3}
    abilities = parse_champion_abilities(
        syndra,
        11,
        200.0,
        ability_ranks={"Q": 5, "W": 3, "E": 1, "R": 2},
        champion_stats=stats,
        champion_options=options,
    )

    order, rule = resolve_cast_order(
        "Syndra",
        abilities,
        champion_data=syndra,
        champion_options=options,
    )

    assert order[-1] == "R"
    assert rule is not None
    assert "execute" in rule.rationale.lower()
