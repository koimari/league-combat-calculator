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

from .common import build_stats_context, extract_leveling_damage, make_rank_fn
from .generic_parser import (
    extract_cooldown,
    parse_abilities as generic_parse,
)


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

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Alistar", ability_ranks, level)
    abilities_data = champion_data.get("abilities", {})

    # ── E: Trample (tick damage + empowered auto on-hit) ─────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]

            # Total tick damage (all 10 ticks over 5 seconds)
            e_total_damage = extract_leveling_damage(
                e_ability, "Total Magic Damage", e_rank, stats_context,
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
