"""Akali ability parsing and damage calculation.

Custom module needed because:
- P (Assassin's Mark): Empowered auto with non-linear per-level scaling
  only in description text, not structured leveling data. User-configurable
  proc count via champion options.
- E (Shuriken Flip): Two-part ability (throw + dash). Uses "Total Magic
  Damage" attribute to capture both hits.
- R (Perfect Execution): Two-cast ultimate (R1 dash + R2 execute). R2
  scales 0-200% based on target missing HP. R1 and R2 are returned
  separately so the fight engine can apply missing-HP scaling to R2
  based on damage dealt earlier in the rotation.

All numeric values are read from the champion JSON data where available.
Passive per-level base values use the wiki growth formula because the
JSON description only stores min:max, not the actual non-linear curve.
"""

import re
from typing import Any

from .generic_parser import extract_cooldown, extract_damage
from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


# ---------------------------------------------------------------------------
# Leveling extraction helper
# ---------------------------------------------------------------------------


def _extract_leveling_damage(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract damage for a specific attribute from ability JSON.

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
# Passive parsing
# ---------------------------------------------------------------------------

# Per-level base damage values from the LoL Wiki (levels 1-20).
# The JSON description only stores "35 : 212 (based on level)" which
# loses the non-linear growth curve (+3/lvl until 7, +9 until 13, +15
# after). These values are NOT in the JSON in any structured form.
# Source: https://wiki.leagueoflegends.com/en-us/Akali
_PASSIVE_BASE_BY_LEVEL: list[float] = [
    35, 38, 41, 44, 47, 50, 53,       # +3 per level (1-7)
    62, 71, 80, 89, 98, 107,           # +9 per level (8-13)
    122, 137, 152, 167, 182, 197, 212, # +15 per level (14-20)
]


def _parse_passive_damage(
    passive: dict[str, Any],
    level: int,
    champion_stats: dict[str, float] | None = None,
    total_ability_power: float = 0.0,
) -> float:
    """Parse Akali passive damage per proc.

    Uses the wiki per-level base values (non-linear growth) plus
    scaling ratios parsed from the JSON description text.

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        champion_stats: Champion stats for bonus AD.
        total_ability_power: Total AP.

    Returns:
        Damage per passive proc before resistances.
    """
    clamped_level = max(1, min(level, 20))
    base_damage = _PASSIVE_BASE_BY_LEVEL[clamped_level - 1]

    # Extract scaling ratios from description: "(+ Z% bonus AD)" etc.
    description = ""
    for effect in passive.get("effects", []):
        description += effect.get("description", "")

    scaling_matches = re.findall(
        r"\(\+\s*(\d+(?:\.\d+)?)%\s+(bonus AD|AP|AD)\)",
        description,
    )

    bonus_damage = 0.0
    for ratio_str, stat_name in scaling_matches:
        ratio = float(ratio_str) / 100.0
        if stat_name == "bonus AD":
            stat_val = (champion_stats or {}).get(
                "bonus_attack_damage", 0.0,
            )
        elif stat_name == "AD":
            stat_val = (champion_stats or {}).get("attack_damage", 0.0)
        elif stat_name == "AP":
            stat_val = total_ability_power
        else:
            stat_val = 0.0
        bonus_damage += ratio * stat_val

    return base_damage + bonus_damage


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
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Akali's abilities and calculate damage.

    Args:
        champion_data: Akali's champion data dictionary from JSON.
        level: Champion level (1-20).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"passive_procs": int}`` — number of passive procs in the
            fight (default 4).
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (unused for Akali).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    passive_procs = 4
    if champion_options and "passive_procs" in champion_options:
        passive_procs = int(champion_options["passive_procs"])

    # Build stats context for scaling
    stats_context: dict[str, float] = {}
    if champion_stats:
        stats_context = dict(champion_stats)
    stats_context["ability_power"] = total_ability_power

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Akali")

    # ── Q: Five Point Strike (standard magic damage) ──────────────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]
            q_damage, q_damage_type = extract_damage(
                q_ability, q_rank, stats_context, target_stats,
            )
            q_cooldown = extract_cooldown(q_ability, q_rank)

            if q_damage > 0:
                results["Q"] = {
                    "name": q_ability.get("name", "Five Point Strike"),
                    "rank": q_rank,
                    "cooldown": q_cooldown,
                    "damage_type": q_damage_type,
                    "magic_damage": q_damage,
                    "total_raw": q_damage,
                }

    # W: Twilight Shroud — no damage, skipped

    # ── E: Shuriken Flip (both hits) ──────────────────────────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]
            e_damage = _extract_leveling_damage(
                e_ability, "Total Magic Damage", e_rank, stats_context,
            )
            e_cooldown = extract_cooldown(e_ability, e_rank)

            if e_damage > 0:
                results["E"] = {
                    "name": e_ability.get("name", "Shuriken Flip"),
                    "rank": e_rank,
                    "cooldown": e_cooldown,
                    "damage_type": "magic",
                    "magic_damage": e_damage,
                    "total_raw": e_damage,
                }

    # ── R: Perfect Execution (R1 + R2 with missing HP scaling) ────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]
            r1_damage = _extract_leveling_damage(
                r_ability, "Magic Damage", r_rank, stats_context,
            )
            r2_min = _extract_leveling_damage(
                r_ability, "Minimum Magic Damage", r_rank, stats_context,
            )
            r2_max = _extract_leveling_damage(
                r_ability, "Maximum Magic Damage", r_rank, stats_context,
            )
            r_cooldown = extract_cooldown(r_ability, r_rank)

            # R1 is standard magic damage. R2 scales with target missing
            # HP (0%-200% increase). We store both R1 and R2 data so
            # damage.py can compute R2 based on actual HP after prior
            # abilities in the rotation.
            results["R"] = {
                "name": r_ability.get("name", "Perfect Execution"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "magic",
                "magic_damage": r1_damage,
                "total_raw": r1_damage + r2_max,
                "r2_min": r2_min,
                "r2_max": r2_max,
                "missing_hp_scaling": True,
            }

    # ── P: Assassin's Mark (empowered auto procs) ─────────────────────
    if passive_procs > 0:
        passive_list = abilities_data.get("P", [])
        if passive_list:
            per_proc = _parse_passive_damage(
                passive_list[0], level, champion_stats, total_ability_power,
            )
            if per_proc > 0:
                results["passive"] = {
                    "name": passive_list[0].get(
                        "name", "Assassin's Mark",
                    ),
                    "damage_type": "magic",
                    "magic_damage": per_proc,
                    "total_raw": per_proc * passive_procs,
                    "proc_count": passive_procs,
                }

    return results
