"""Alistar ability parsing and damage calculation.

Custom module needed because:
- E (Trample): Tick-based damage (10 ticks over 5 seconds) where the full
  duration damage should be used, plus a secondary on-hit empowered auto
  that scales with champion level (not ability rank).

Q and W are standard single-hit magic damage abilities handled by the
generic parser.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .generic_parser import (
    extract_cooldown,
    parse_abilities as generic_parse,
)
from .scaling import resolve_scaling, is_flat_unit
from .skill_orders import get_ability_rank


def _extract_e_on_hit_damage(
    ability: dict[str, Any],
    level: int,
) -> float:
    """Extract E empowered auto bonus magic damage from JSON.

    The empowered auto-attack bonus damage scales with champion level
    (not ability rank). The JSON stores it in effect[1] under the
    ``"Bonus Magic Damage"`` attribute.

    Args:
        ability: E ability dict from champion JSON.
        level: Champion level (1-18).

    Returns:
        Bonus magic damage for the empowered auto at the given level.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Bonus Magic Damage":
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            # Per-level values may have fewer entries than 18.
            # Linearly interpolate across available values.
            if len(values) >= level:
                return float(values[level - 1])

            # Interpolate: map level (1-18) into the values array
            num_values = len(values)
            if num_values == 1:
                return float(values[0])

            fraction = (level - 1) / 17.0  # 0.0 at level 1, 1.0 at 18
            index_float = fraction * (num_values - 1)
            low_idx = int(index_float)
            high_idx = min(low_idx + 1, num_values - 1)
            weight = index_float - low_idx
            return float(values[low_idx]) * (1 - weight) + float(values[high_idx]) * weight

    return 0.0


def _extract_e_total_damage(
    ability: dict[str, Any],
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract E total tick damage from the ``Total Magic Damage`` attribute.

    Args:
        ability: E ability dict from champion JSON.
        rank: E ability rank (1-5).
        stats_context: Champion stats for scaling resolution.

    Returns:
        Total raw magic damage from all ticks at the given rank.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Total Magic Damage":
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
                        unit, value, stats_context, None,
                    )
            return total

    return 0.0


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,  # pylint: disable=unused-argument
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Alistar's abilities and calculate damage.

    Args:
        champion_data: Alistar's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options (unused for Alistar).
        champion_stats: Champion's calculated stats (for scaling).
        target_stats: Target stats (for %HP abilities).

    Returns:
        Dictionary with ability key -> damage information.
    """
    # Let generic parser handle Q and W
    results = generic_parse(
        champion_data, level, total_ability_power, ability_ranks,
        champion_stats=champion_stats, target_stats=target_stats,
    )

    # Remove any generic E parse — we handle it custom
    results.pop("E", None)
    # Remove R (utility only — damage reduction, no damage)
    results.pop("R", None)
    # Remove passive (healing, not damage)
    results.pop("passive", None)

    # Build stats context for scaling
    stats_context: dict[str, float] = {}
    if champion_stats:
        stats_context = dict(champion_stats)
    stats_context["ability_power"] = total_ability_power

    abilities_data = champion_data.get("abilities", {})

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Alistar")

    # ── E: Trample (tick damage + empowered auto on-hit) ─────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]

            # Total tick damage (all 10 ticks over 5 seconds)
            e_total_damage = _extract_e_total_damage(
                e_ability, e_rank, stats_context,
            )
            e_cooldown = extract_cooldown(e_ability, e_rank)

            # Empowered auto bonus damage (scales with champion level).
            # This procs once per E cast (not every auto), so add it
            # directly to E's total damage.
            e_on_hit_damage = _extract_e_on_hit_damage(e_ability, level)
            e_total_damage += e_on_hit_damage

            results["E"] = {
                "name": e_ability.get("name", "Trample"),
                "rank": e_rank,
                "cooldown": e_cooldown,
                "damage_type": "magic",
                "magic_damage": e_total_damage,
                "total_raw": e_total_damage,
            }

    return results
