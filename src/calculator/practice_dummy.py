"""Explicit data and validation for the League Practice Tool target dummy.

The dummy is a target participant. It has no champion ability package and
never enters an attacker position in the participant timeline. Its item
effects still resolve through the normal cached item path.
"""

from collections.abc import Mapping
import math
from typing import Any

PRACTICE_DUMMY_KIND = "practice_dummy"
PRACTICE_DUMMY_NAME = "Practice Dummy"
PRACTICE_DUMMY_LEVEL = 18
PRACTICE_DUMMY_ICON = (
    "https://raw.communitydragon.org/16.15/game/assets/characters/"
    "practicetool_targetdummy/hud/dummy_enemy.png"
)

# These are the dummy's base values before item stats. The public editor can
# replace any listed final stat with an exact value.
PRACTICE_DUMMY_BASE_STATS = {
    "health": 1000.0,
    "attack_damage": 0.0,
    "armor": 100.0,
    "magic_resistance": 100.0,
    "attack_speed": 1.0,
    "move_speed": 325.0,
    "max_mana": 0.0,
}

PRACTICE_DUMMY_STAT_LIMITS: dict[str, tuple[float, float]] = {
    "health": (1.0, 100_000.0),
    "bonus_health": (0.0, 100_000.0),
    "armor": (0.0, 10_000.0),
    "magic_resistance": (0.0, 10_000.0),
    "attack_damage": (0.0, 100_000.0),
    "ability_power": (0.0, 100_000.0),
    "attack_speed": (0.0, 100.0),
    "ability_haste": (0.0, 10_000.0),
    "move_speed": (0.0, 10_000.0),
    "critical_strike_chance": (0.0, 100.0),
    "max_mana": (0.0, 100_000.0),
}


def practice_dummy_data() -> dict[str, Any]:
    """Return the synthetic champion-shaped record used by item stat math."""
    return {
        "name": PRACTICE_DUMMY_NAME,
        "title": "Practice Tool Target Dummy",
        "icon": PRACTICE_DUMMY_ICON,
        "attackType": "MELEE",
        "adaptiveType": "ADAPTIVE",
        "stats": {
            "health": {"flat": 1000.0, "perLevel": 0.0},
            "attackDamage": {"flat": 0.0, "perLevel": 0.0},
            "armor": {"flat": 100.0, "perLevel": 0.0},
            "magicResistance": {"flat": 100.0, "perLevel": 0.0},
            "attackSpeed": {"flat": 1.0, "perLevel": 0.0},
            "attackSpeedRatio": {"flat": 1.0},
            "movespeed": {"flat": 325.0},
            "mana": {"flat": 0.0, "perLevel": 0.0},
            "manaRegen": {"flat": 0.0, "perLevel": 0.0},
            "healthRegen": {"flat": 0.0, "perLevel": 0.0},
        },
        "abilities": {slot: [] for slot in ("P", "Q", "W", "E", "R")},
    }


def parse_stat_overrides(value: object, *, field: str) -> dict[str, float]:
    """Validate exact final-stat overrides and preserve decimal values."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    unknown = set(value) - set(PRACTICE_DUMMY_STAT_LIMITS)
    if unknown:
        raise ValueError(f"{field} contains unknown stat {sorted(unknown)[0]}")

    parsed: dict[str, float] = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{field}.{key} must be a number")
        numeric = float(raw_value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field}.{key} must be finite")
        minimum, maximum = PRACTICE_DUMMY_STAT_LIMITS[key]
        if numeric < minimum or numeric > maximum:
            raise ValueError(
                f"{field}.{key} must be between {minimum:g} and {maximum:g}"
            )
        parsed[key] = numeric
    return parsed


def apply_stat_overrides(
    stats: Mapping[str, float], overrides: Mapping[str, float]
) -> dict[str, float]:
    """Apply exact values and keep dependent stat fields internally coherent."""
    result = {key: float(value) for key, value in stats.items()}
    result.update({key: float(value) for key, value in overrides.items()})

    if "bonus_health" in overrides and "health" not in overrides:
        result["health"] = result.get("base_health", 0.0) + result["bonus_health"]
    if "health" in overrides:
        result["base_health"] = result["health"] - result.get("bonus_health", 0.0)
    if "armor" in overrides:
        result["bonus_armor"] = max(
            0.0, result["armor"] - PRACTICE_DUMMY_BASE_STATS["armor"]
        )
    if "magic_resistance" in overrides:
        result["bonus_magic_resistance"] = max(
            0.0,
            result["magic_resistance"] - PRACTICE_DUMMY_BASE_STATS["magic_resistance"],
        )
    if "attack_damage" in overrides:
        result["base_attack_damage"] = PRACTICE_DUMMY_BASE_STATS["attack_damage"]
        result["bonus_attack_damage"] = result["attack_damage"]
    return result
