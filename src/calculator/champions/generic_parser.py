"""Generic champion ability parser — reads ability data from JSON.

Handles the majority of champions (~80%+) without champion-specific code.
Parses base damages, scaling ratios, cooldowns, and damage types from the
wiki-scraped JSON data structure.

Champions with unique mechanics (transforms, mega kits, weapon systems)
should use dedicated modules that can import shared utilities from here.
"""

from typing import Any

from .attribute_classifier import (
    classify_damage_type,
    is_damage_attribute,
    is_primary_damage_attribute,
)
from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


# ---------------------------------------------------------------------------
# Cooldown extraction
# ---------------------------------------------------------------------------


def extract_cooldown(ability: dict[str, Any], rank: int) -> float:
    """Extract the base cooldown for an ability at a given rank.

    Args:
        ability: Single ability dict from champion JSON.
        rank: Ability rank (1-indexed).

    Returns:
        Base cooldown in seconds, or 0.0 if not found.
    """
    cd_data = ability.get("cooldown")
    if not cd_data or not cd_data.get("modifiers"):
        return 0.0

    values = cd_data["modifiers"][0].get("values", [])
    if not values:
        return 0.0

    idx = min(rank - 1, len(values) - 1)
    return float(values[idx])


# ---------------------------------------------------------------------------
# Damage extraction
# ---------------------------------------------------------------------------


def _find_damage_leveling(
    ability: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Find leveling entries that represent primary damage.

    Scans all effects and returns the first primary damage leveling entry.
    Prefers exact matches like "Magic Damage" over partial matches like
    "Damage Per Pass".

    Args:
        ability: Single ability dict from champion JSON.

    Returns:
        List of matching leveling entries, or None if no damage found.
    """
    primary_matches: list[dict[str, Any]] = []
    fallback_matches: list[dict[str, Any]] = []

    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            attribute = leveling.get("attribute", "")
            if is_primary_damage_attribute(attribute):
                primary_matches.append(leveling)
            elif is_damage_attribute(attribute):
                fallback_matches.append(leveling)

    if primary_matches:
        return [primary_matches[0]]
    if fallback_matches:
        return [fallback_matches[0]]
    return None


def extract_damage(
    ability: dict[str, Any],
    rank: int,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> tuple[float, str]:
    """Extract total damage for an ability at a given rank.

    Sums flat base damage and all scaling contributions.

    Args:
        ability: Single ability dict from champion JSON.
        rank: Ability rank (1-indexed).
        champion_stats: Champion's stats for scaling resolution.
        target_stats: Target's stats for %HP scaling.

    Returns:
        Tuple of (total_raw_damage, damage_type).
    """
    damage_type = classify_damage_type(ability)
    leveling_entries = _find_damage_leveling(ability)

    if not leveling_entries:
        return 0.0, damage_type

    total_damage = 0.0
    for leveling in leveling_entries:
        for modifier in leveling.get("modifiers", []):
            values = modifier.get("values", [])
            units = modifier.get("units", [])
            if not values:
                continue

            idx = min(rank - 1, len(values) - 1)
            value = float(values[idx])

            unit = units[idx] if idx < len(units) else ""

            if is_flat_unit(unit):
                total_damage += value
            else:
                total_damage += resolve_scaling(
                    unit, value, champion_stats, target_stats,
                )

    return total_damage, damage_type


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse abilities for any champion from JSON data.

    Reads the ``abilities`` section of champion JSON and extracts damage,
    cooldowns, and scaling for Q/W/E/R. Works for the majority of
    champions with standard ability patterns.

    Args:
        champion_data: Full champion data dict from JSON.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional rank overrides per ability key.
        champion_stats: Champion's calculated stats (for AD/HP scaling).
        target_stats: Target stats (for %HP abilities).

    Returns:
        Ability damage dictionary keyed by Q/W/E/R.
    """
    champion_name = champion_data.get("name", "")
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    # Build stats context for scaling resolution
    stats_context = _build_stats_context(
        champion_stats, total_ability_power,
    )

    for slot in ("Q", "W", "E", "R"):
        ability_list = abilities_data.get(slot, [])
        if not ability_list:
            continue

        # Use the first ability in the slot (index 0).
        # Transform champions store alternate forms at index 1+.
        ability = ability_list[0]

        # If this ability is a passive (e.g. Vayne W Silver Bolts),
        # handle it as an on-hit effect instead of a castable ability.
        targeting = (ability.get("targeting") or "").lower()
        if targeting == "passive":
            _parse_slot_passive_on_hit(
                slot, ability, level, champion_name, ability_ranks,
                stats_context, target_stats, results,
            )
            continue

        # Determine rank
        if ability_ranks and slot in ability_ranks:
            rank = ability_ranks[slot]
        else:
            rank = get_ability_rank(slot, level, champion_name)

        if rank < 1:
            continue

        # Extract cooldown
        cooldown = extract_cooldown(ability, rank)

        # Extract damage
        total_damage, damage_type = extract_damage(
            ability, rank, stats_context, target_stats,
        )

        if total_damage <= 0 and not ability.get("damageType"):
            # Non-damaging ability (shields, buffs, etc.)
            continue

        # Build the output dict matching the fight engine format
        entry: dict[str, Any] = {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": rank,
            "cooldown": cooldown,
            "damage_type": damage_type,
            "total_raw": total_damage,
        }

        # Set type-specific damage keys for the fight engine
        if damage_type == "magic":
            entry["magic_damage"] = total_damage
        elif damage_type == "physical":
            entry["physical_damage"] = total_damage
        elif damage_type == "true":
            entry["true_damage"] = total_damage
        elif damage_type == "mixed":
            # Split evenly between magic and true (like Ahri Q)
            entry["magic_damage"] = total_damage / 2.0
            entry["true_damage"] = total_damage / 2.0

        results[slot] = entry

    # Check for on-hit passive (P slot)
    _parse_passive_on_hit(
        abilities_data, level, stats_context, target_stats, results,
    )

    return results


def _build_stats_context(
    champion_stats: dict[str, float] | None,
    total_ability_power: float,
) -> dict[str, float]:
    """Build a stats context dict for scaling resolution.

    Merges champion_stats with the AP value, providing defaults
    for any missing keys.

    Args:
        champion_stats: Champion's calculated stats dict.
        total_ability_power: Total AP (may be more up-to-date than stats).

    Returns:
        Stats context dict usable by ``resolve_scaling()``.
    """
    if champion_stats is None:
        return {"ability_power": total_ability_power}

    ctx = dict(champion_stats)
    # Ensure AP is current (stats might have been computed before AP items)
    ctx["ability_power"] = total_ability_power
    return ctx


def _parse_slot_passive_on_hit(
    slot: str,
    ability: dict[str, Any],
    level: int,
    champion_name: str,
    ability_ranks: dict[str, int] | None,
    stats_context: dict[str, float],
    target_stats: dict[str, float] | None,
    results: dict[str, dict[str, Any]],
) -> None:
    """Handle a Q/W/E/R ability that has ``targeting: "Passive"``.

    These are on-hit passives placed in a regular ability slot (e.g.
    Vayne W Silver Bolts). They are added to results as on-hit entries
    that the fight engine processes per auto attack.

    Args:
        slot: Ability slot key (Q/W/E/R).
        ability: The ability dict from JSON.
        level: Champion level.
        champion_name: Champion name for skill order.
        ability_ranks: Optional rank overrides.
        stats_context: Champion stats for scaling.
        target_stats: Target stats for %HP scaling.
        results: Results dict to mutate.
    """
    if ability_ranks and slot in ability_ranks:
        rank = ability_ranks[slot]
    else:
        rank = get_ability_rank(slot, level, champion_name)

    if rank < 1:
        return

    total_damage, damage_type = extract_damage(
        ability, rank, stats_context, target_stats,
    )

    if total_damage <= 0:
        return

    ability_name = ability.get("name", f"Ability {slot}")
    results[slot] = {
        "name": ability_name,
        "on_hit": {
            "name": f"{ability_name} (on-hit)",
            "damage_per_hit": total_damage,
            "damage_type": damage_type,
        },
    }


def _parse_passive_on_hit(
    abilities_data: dict[str, Any],
    level: int,
    stats_context: dict[str, float],
    target_stats: dict[str, float] | None,
    results: dict[str, dict[str, Any]],
) -> None:
    """Check for damaging on-hit passives and add them to results.

    On-hit passives (e.g. Vayne W, Viego passive) are detected by
    checking the P slot for damage-type abilities with specific keywords
    in their description.

    Args:
        abilities_data: The ``abilities`` section of champion JSON.
        level: Champion level.
        stats_context: Stats for scaling resolution.
        target_stats: Target stats for %HP scaling.
        results: Results dict to add on-hit entries to (mutated).
    """
    passive_list = abilities_data.get("P", [])
    if not passive_list:
        return

    passive = passive_list[0]

    # Check if the passive has damage and on-hit characteristics
    damage_type_field = passive.get("damageType")
    if not damage_type_field:
        return

    # Check description for on-hit keywords
    desc = ""
    for effect in passive.get("effects", []):
        desc += effect.get("description", "").lower()

    on_hit_keywords = ["on-hit", "on hit", "basic attack", "auto-attack"]
    is_on_hit = any(kw in desc for kw in on_hit_keywords)

    if not is_on_hit:
        return

    # Try to extract damage from the passive
    # Passives may have per-level scaling (18 values) or flat values
    total_damage, damage_type = extract_damage(
        passive, level, stats_context, target_stats,
    )

    if total_damage <= 0:
        return

    passive_name = passive.get("name", "Passive")
    results["passive"] = {
        "name": passive_name,
        "on_hit": {
            "name": f"{passive_name} (on-hit)",
            "damage_per_hit": total_damage,
            "damage_type": damage_type,
        },
    }
