"""Shared helpers used by all champion ability modules.

Functions here are champion-agnostic. Champion-specific data (base damages,
scaling ratios, cooldowns, skill orders) lives in each champion's own module.
"""

from typing import Any, Callable

from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


# ---------------------------------------------------------------------------
# Simple damage helpers
# ---------------------------------------------------------------------------


def calculate_ability_damage(
    base_damage: float,
    scaling_ratio: float,
    scaling_stat: float,
) -> float:
    """Calculate raw ability damage before resistances.

    Formula: base_damage + (scaling_ratio * scaling_stat)

    Args:
        base_damage: Base damage at current rank.
        scaling_ratio: Scaling ratio as a decimal (e.g., 0.5 for 50%).
        scaling_stat: The stat value to scale with (e.g., total AP).

    Returns:
        Total raw ability damage.
    """
    return base_damage + (scaling_ratio * scaling_stat)


def effective_cooldown(base_cooldown: float, ability_haste: float) -> float:
    """Calculate effective cooldown after ability haste.

    Formula: base_cd * 100 / (100 + ability_haste)

    Args:
        base_cooldown: Base cooldown in seconds.
        ability_haste: Total ability haste.

    Returns:
        Effective cooldown in seconds.
    """
    if base_cooldown <= 0:
        return 0.0
    return base_cooldown * (100.0 / (100.0 + ability_haste))


# ---------------------------------------------------------------------------
# JSON leveling extraction (shared across all champion modules)
# ---------------------------------------------------------------------------


def extract_leveling_damage(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    stats_context: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> float:
    """Extract damage for a specific attribute name from ability JSON.

    Searches all effects/leveling entries for a matching attribute and
    sums the flat base + scaling contributions at the given rank.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for (e.g.
            ``"First Cast Damage"``).
        rank: Ability rank (1-indexed).
        stats_context: Champion stats for scaling resolution.
        target_stats: Target stats for %HP scaling resolution.

    Returns:
        Total raw damage for this attribute at the given rank.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute_name:
                continue

            total = 0.0
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue

                idx = min(rank - 1, len(values) - 1)
                value = float(values[idx])
                unit = units[idx] if idx < len(units) else ""

                if is_flat_unit(unit):
                    total += value
                else:
                    total += resolve_scaling(
                        unit, value, stats_context, target_stats,
                    )
            return total

    return 0.0


def extract_leveling_value(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    modifier_index: int = 0,
) -> float:
    """Extract a simple numeric value from ability JSON leveling data.

    Returns only the specified modifier's flat value without resolving
    scaling. Used for values like armor penetration percentages, attack
    speed bonuses, or bullet counts.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for.
        rank: Ability rank (1-indexed).
        modifier_index: Which modifier to read (default 0 = first).

    Returns:
        The flat numeric value at the given rank, or 0.0 if not found.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute_name:
                continue

            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0

            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0

            idx = min(rank - 1, len(values) - 1)
            return float(values[idx])

    return 0.0


# ---------------------------------------------------------------------------
# Parse context boilerplate
# ---------------------------------------------------------------------------


def build_stats_context(
    champion_stats: dict[str, float] | None,
    total_ability_power: float,
) -> dict[str, float]:
    """Build a stats context dict for scaling resolution.

    Merges champion_stats with the AP value, providing an empty base
    if champion_stats is None.

    Args:
        champion_stats: Champion's calculated stats dict.
        total_ability_power: Total AP (may be more up-to-date than stats).

    Returns:
        Stats context dict usable by ``resolve_scaling()``.
    """
    ctx = dict(champion_stats) if champion_stats else {}
    ctx["ability_power"] = total_ability_power
    return ctx


def make_rank_fn(
    champion_name: str,
    ability_ranks: dict[str, int] | None,
    level: int,
) -> Callable[[str], int]:
    """Create a rank_for() closure for a champion module.

    Args:
        champion_name: Display name for skill order lookup.
        ability_ranks: Optional rank overrides per ability key.
        level: Champion level (1-18).

    Returns:
        A function ``rank_for(key) -> int`` that resolves ability rank.
    """
    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, champion_name)
    return rank_for
