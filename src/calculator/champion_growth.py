"""A champion's base stat block at a level."""

from collections.abc import Mapping
from typing import Any

from .stat_formulas import growth_stat


def get_champion_base_stats(
    champion_data: Mapping[str, Any], level: int
) -> dict[str, float]:
    """Calculate a champion's base stats at a given level (no items).

    Args:
        champion_data: Champion data dictionary from the CDN.
        level: Champion level (1-20; 19-20 need the completed top quest).

    Returns:
        Dictionary with stat names and their computed values.
    """
    stats = champion_data["stats"]

    health = growth_stat(stats["health"]["flat"], stats["health"]["perLevel"], level)
    attack_damage = growth_stat(
        stats["attackDamage"]["flat"],
        stats["attackDamage"]["perLevel"],
        level,
    )
    armor = growth_stat(stats["armor"]["flat"], stats["armor"]["perLevel"], level)
    magic_resistance = growth_stat(
        stats["magicResistance"]["flat"],
        stats["magicResistance"]["perLevel"],
        level,
    )

    return {
        "health": health,
        "attack_damage": attack_damage,
        "ability_power": 0.0,
        "armor": armor,
        "magic_resistance": magic_resistance,
        "move_speed": stats["movespeed"]["flat"],
    }
