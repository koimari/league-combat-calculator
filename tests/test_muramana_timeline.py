"""Focused tests for Muramana's cast-boundary proc receipt."""

from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.damage import (
    FightConfig,
    RotationResult,
    _muramana_proc_events,
    calculate_fight_damage,
)


def _stats() -> dict[str, float]:
    return {
        "attack_damage": 80.0,
        "base_attack_damage": 60.0,
        "attack_speed": 0.7,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_flat": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_power": 100.0,
        "max_mana": 1500.0,
        "is_melee": False,
        "level": 18,
    }


def test_muramana_multicast_emits_one_boundary_event_per_instance() -> None:
    """A three-instance R gets three timestamped Muramana proc events."""
    abilities = {
        "R": {
            "name": "Spirit Rush",
            "parts": (DamagePart("magic", 200.0, count=3),),
            "cast_instances": 3,
            "total_raw": 600.0,
            "damage_type": "magic",
        }
    }
    fight = calculate_fight_damage(
        _stats(),
        abilities,
        [{"name": "Muramana"}],
        FightConfig(
            target_health=2000.0,
            target_armor=100.0,
            target_magic_resistance=100.0,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            cast_order=["R"],
        ),
    )

    row = fight["breakdown"]["muramana_ability"]
    assert [event["time"] for event in row["damage_events"]] == [0.0, 0.0, 0.0]
    # R is a certified single-hit cast (cast_order membership, no DoT), so
    # the per-instance Shock events ride exact precision.
    assert all(event["event_precision"] == "exact" for event in row["damage_events"])
    assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
        row["total_damage"]
    )


def test_muramana_event_builder_withholds_incomplete_cast_receipt() -> None:
    """A missing cast timestamp withholds events instead of guessing time zero."""
    state = SimpleNamespace(
        ability_damages={"Q": {"cast_instances": 1}},
    )
    rotation = RotationResult(
        total_muramana_procs=1,
        cast_events=[{"slot": "Q"}],
    )

    assert _muramana_proc_events(state, rotation) is None


def test_muramana_event_builder_withholds_count_mismatch() -> None:
    """An authored receipt count mismatch remains aggregate-only."""
    state = SimpleNamespace(
        ability_damages={"Q": {"cast_instances": 2}},
    )
    rotation = RotationResult(
        total_muramana_procs=1,
        cast_events=[{"slot": "Q", "time": 0.0}],
    )

    assert _muramana_proc_events(state, rotation) is None


def test_muramana_prefers_authored_ability_hit_time() -> None:
    """A sourced ability packet replaces the cast-boundary fallback."""
    state = SimpleNamespace(
        ability_damages={"Q": {"cast_instances": 1}},
        breakdown={
            "Q": {
                "damage_events": [
                    {"time": 0.25, "damage": 100.0, "event_precision": "exact"}
                ]
            }
        },
    )
    rotation = RotationResult(
        total_muramana_procs=1,
        cast_events=[{"slot": "Q", "time": 0.0}],
    )

    assert _muramana_proc_events(state, rotation) == [
        {"time": 0.25, "damage": 0.0, "event_precision": "exact"}
    ]
