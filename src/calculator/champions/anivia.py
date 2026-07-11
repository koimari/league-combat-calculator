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

from .common import build_stats_context, extract_leveling_damage, make_rank_fn
from .generic_parser import extract_cooldown


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

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Anivia", ability_ranks, level)

    # Read champion options
    r_duration = 5.0
    if champion_options and "r_duration" in champion_options:
        r_duration = float(champion_options["r_duration"])
    r_duration = max(r_duration, 1.5)

    # Q - Flash Frost: total damage (pass-through + detonation)
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if not q_ability_list:
            return results
        q_ability = q_ability_list[0]
        q_damage = extract_leveling_damage(
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
        e_ability_list = abilities_data.get("E", [])
        if not e_ability_list:
            return results
        e_ability = e_ability_list[0]
        e_damage = extract_leveling_damage(
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
        r_ability_list = abilities_data.get("R", [])
        if not r_ability_list:
            return results
        r_ability = r_ability_list[0]

        initial_per_tick = extract_leveling_damage(
            r_ability, "Magic Damage per Tick", r_rank, stats_context,
        )
        empowered_per_tick = extract_leveling_damage(
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
