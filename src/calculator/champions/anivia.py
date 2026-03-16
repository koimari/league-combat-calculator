"""Anivia ability parsing and damage calculation.

Custom module needed because:
- Q (Flash Frost): Uses "Total Magic Damage" (pass-through + detonation combined).
- E (Frostbite): Uses "Enhanced Damage" (assumes target is always Chilled).
- R (Glacial Storm): Two-phase DoT toggle with configurable duration —
  initial ticks (first 1.5s) at lower damage, then fully-formed ticks
  at higher damage. Reported as a single magic_damage value per cast.
- W: Skipped (utility wall, no damage).
- Passive: Skipped (resurrection only, no damage).

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .generic_parser import extract_cooldown
from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------


def _extract_leveling_damage(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract damage for a specific attribute name from ability JSON.

    Searches all effects/leveling entries for a matching attribute and
    sums the flat base + scaling contributions at the given rank.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for.
        rank: Ability rank (1-indexed).
        stats_context: Champion stats for scaling resolution.

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
                        unit, value, stats_context, None,
                    )
            return total

    return 0.0


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,  # pylint: disable=unused-argument
) -> dict[str, dict[str, Any]]:
    """Parse Anivia's abilities and calculate damage.

    Args:
        champion_data: Anivia's champion data dictionary from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options (r_duration).
        champion_stats: Champion's calculated stats (for scaling).
        target_stats: Target stats (unused for Anivia).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    # Build stats context for scaling resolution
    stats_context: dict[str, float] = {}
    if champion_stats:
        stats_context = dict(champion_stats)
    stats_context["ability_power"] = total_ability_power

    # Read champion options
    r_duration = 5.0
    if champion_options and "r_duration" in champion_options:
        r_duration = float(champion_options["r_duration"])
    r_duration = max(r_duration, 1.5)

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Anivia")

    # Q - Flash Frost: total damage (pass-through + detonation)
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability = abilities_data["Q"][0]
        q_damage = _extract_leveling_damage(
            q_ability, "Total Magic Damage", q_rank, stats_context,
        )
        q_cooldown = extract_cooldown(q_ability, q_rank)
        results["Q"] = {
            "name": q_ability.get("name", "Flash Frost"),
            "rank": q_rank,
            "cooldown": q_cooldown,
            "magic_damage": q_damage,
            "total_raw": q_damage,
            "damage_type": "magic",
        }

    # W - Crystallize: no damage, skipped

    # E - Frostbite: always-empowered (target assumed Chilled)
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability = abilities_data["E"][0]
        e_damage = _extract_leveling_damage(
            e_ability, "Enhanced Damage", e_rank, stats_context,
        )
        e_cooldown = extract_cooldown(e_ability, e_rank)
        results["E"] = {
            "name": e_ability.get("name", "Frostbite"),
            "rank": e_rank,
            "cooldown": e_cooldown,
            "magic_damage": e_damage,
            "total_raw": e_damage,
            "damage_type": "magic",
        }

    # R - Glacial Storm: two-phase DoT toggle
    # First 1.5s (3 ticks at 0.5s) = initial damage per tick
    # After 1.5s = empowered damage per tick
    # Total ticks = r_duration / 0.5
    # Initial ticks = 3, empowered ticks = total_ticks - 3
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability = abilities_data["R"][0]

        initial_per_tick = _extract_leveling_damage(
            r_ability, "Magic Damage per Tick", r_rank, stats_context,
        )
        empowered_per_tick = _extract_leveling_damage(
            r_ability, "Empowered Damage per Tick", r_rank, stats_context,
        )

        total_ticks = int(r_duration / 0.5)
        initial_ticks = min(3, total_ticks)
        empowered_ticks = max(0, total_ticks - 3)

        r_total_damage = (
            initial_ticks * initial_per_tick
            + empowered_ticks * empowered_per_tick
        )

        # Use a very high cooldown so the fight engine only casts R once
        results["R"] = {
            "name": r_ability.get("name", "Glacial Storm"),
            "rank": r_rank,
            "cooldown": 999.0,
            "magic_damage": r_total_damage,
            "total_raw": r_total_damage,
            "damage_type": "magic",
        }

    return results
