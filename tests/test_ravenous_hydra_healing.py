"""Focused receipt tests for Ravenous Hydra's life-steal active packet."""

import math
from typing import cast

import pytest

from src.calculator.data_fetcher import fetch_item_data, get_champion, get_item_by_name
from src.calculator.damage import _active_lifesteal_amount
from src.calculator.passive_parser import parse_item_effect
from src.calculator.pipeline import FightParams, run_fight


def test_ravenous_hydra_parser_sources_full_lifesteal_effectiveness() -> None:
    """Read 100% life-steal effectiveness from the cached branch text."""
    parsed = parse_item_effect("Ravenous Hydra", fetch_item_data())

    if parsed is None:
        pytest.fail("Ravenous Hydra parser returned no values")
    parsed_values = cast(dict[str, float], parsed)
    assert parsed_values.get("lifesteal_effectiveness") == pytest.approx(1.0)


def test_ravenous_hydra_active_emits_exact_lifesteal_event(
    attacker_stats, fight
) -> None:
    """Pair the active's exact damage event with its life-steal heal."""
    stats = attacker_stats(lifesteal_percent=12.0)
    result = fight(
        stats,
        include_actives=True,
        items=[get_item_by_name("Ravenous Hydra")],
        target_armor=100.0,
    )

    active = result["breakdown"]["active_Ravenous Hydra"]
    heal = result["breakdown"]["heal_Ravenous Hydra"]
    assert [event["time"] for event in active["damage_events"]] == [0.0]
    assert heal["proc_times"] == [0.0]
    assert heal["amount_per_proc"] == pytest.approx(
        active["damage_events"][0]["damage"] * stats["lifesteal_percent"] / 100.0
    )


@pytest.mark.parametrize(
    "lifesteal", [None, True, "12", "bad", math.nan, math.inf, -1.0]
)
def test_ravenous_hydra_withholds_malformed_lifesteal_stat(
    attacker_stats, fight, lifesteal
) -> None:
    """Withhold the heal when the cached life-steal receipt is malformed."""
    stats = attacker_stats(lifesteal_percent=lifesteal)
    result = fight(
        stats,
        include_actives=True,
        items=[get_item_by_name("Ravenous Hydra")],
    )

    assert "active_Ravenous Hydra" in result["breakdown"]
    assert "heal_Ravenous Hydra" not in result["breakdown"]


def test_ravenous_hydra_withholds_incomplete_damage_event(attacker_stats) -> None:
    """Withhold a heal when the source damage event lacks its timestamp."""
    stats = attacker_stats(lifesteal_percent=12.0)

    state = type("State", (), {"champion_stats": stats})()
    assert _active_lifesteal_amount(state, {}, 1.0) is None
    assert _active_lifesteal_amount(state, {"time": "0", "damage": 40.0}, 1.0) is None


def test_ravenous_hydra_withholds_missing_parser_effect(attacker_stats) -> None:
    """Withhold a heal when parser-owned effectiveness is absent."""
    stats = attacker_stats(lifesteal_percent=12.0)
    assert (
        _active_lifesteal_amount(
            type("State", (), {"champion_stats": stats})(),
            {"time": 0.0, "damage": 40.0},
            0.0,
        )
        is None
    )


def test_basic_and_physical_on_hit_events_emit_generic_life_steal(
    attacker_stats, fight
) -> None:
    """Primary-target life steal follows each exact physical attack packet."""
    stats = attacker_stats(lifesteal_percent=10.0)
    result = fight(
        stats,
        include_actives=False,
        items=[get_item_by_name("Blade of the Ruined King")],
        auto_attack_uptime=1.0,
        one_rotation=False,
        fight_duration_seconds=3.0,
    )

    auto_events = result["breakdown"]["auto_attacks"]["damage_events"]
    on_hit_events = result["breakdown"]["on_hit_Blade of the Ruined King"][
        "damage_events"
    ]
    heal = result["breakdown"]["heal_lifesteal"]
    assert heal["count"] == len(auto_events) + len(on_hit_events)
    assert heal["total_amount"] == pytest.approx(
        sum(event["damage"] for event in auto_events + on_hit_events) * 0.10
    )
    assert [event["time"] for event in heal["heal_events"]] == sorted(
        event["time"] for event in heal["heal_events"]
    )


def test_generic_life_steal_excludes_magic_on_hit_packets(
    attacker_stats, fight
) -> None:
    """Life steal does not consume magic-only on-hit damage rows."""
    stats = attacker_stats(lifesteal_percent=10.0)
    result = fight(
        stats,
        include_actives=False,
        items=[get_item_by_name("Wit's End")],
        auto_attack_uptime=1.0,
        one_rotation=False,
        fight_duration_seconds=3.0,
    )

    heal = result["breakdown"]["heal_lifesteal"]
    auto_events = result["breakdown"]["auto_attacks"]["damage_events"]
    assert heal["count"] == len(auto_events)
    assert heal["total_amount"] == pytest.approx(
        sum(event["damage"] for event in auto_events) * 0.10
    )


def test_forced_basic_attack_ability_rows_emit_life_steal():
    """A Vayne Q swing remains life-steal eligible without ambient autos."""
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "cast_order": ["Q", "W", "E", "R"],
        }
    )
    result = run_fight(
        get_champion("Vayne"),
        18,
        [get_item_by_name("Blade of the Ruined King")],
        params,
    )

    heal = result["breakdown"]["heal_lifesteal"]
    q_damage = next(
        event["damage"]
        for event in result["damage_events"]
        if event["source_key"] == "Q" and event.get("basic_attack")
    )
    assert heal["count"] == 1
    assert heal["total_amount"] == pytest.approx(q_damage * 0.10)
