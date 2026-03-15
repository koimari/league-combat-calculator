"""Ambessa ability parsing and damage calculation.

Custom module needed because:
- P (Drakehound's Step): Empowered auto with per-level scaling and
  user-configurable proc count via champion options.
- Q (Cunning Sweep / Sundering Slam): Two separate casts with different
  scalings. Each has a sweetspot mechanic that doubles damage (champion
  option toggle). Q2 is a separate ability entry in the JSON.
- W (Repudiation): Has normal and increased (empowered) damage. We always
  use the increased damage values.
- E (Lacerate): Hits twice. We use the "Total Physical Damage" attribute
  to capture both hits.
- R (Public Execution): Passive grants armor penetration per rank (stat
  buff that should always be active). Active portion deals physical damage.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

import re
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
    target_stats: dict[str, float] | None = None,
) -> float:
    """Extract damage for a specific attribute name from ability JSON.

    Searches all effects/leveling entries for a matching attribute and
    sums the flat base + scaling contributions at the given rank.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for.
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


def _extract_leveling_value(
    ability: dict[str, Any],
    attribute_name: str,
    rank: int,
) -> float:
    """Extract a simple numeric value from ability JSON leveling data.

    Unlike ``_extract_leveling_damage``, this returns only the first
    modifier's flat value without resolving scaling. Used for values
    like armor penetration percentages.

    Args:
        ability: Single ability dict from champion JSON.
        attribute_name: Exact attribute name to look for.
        rank: Ability rank (1-indexed).

    Returns:
        The flat numeric value at the given rank, or 0.0 if not found.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != attribute_name:
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            idx = min(rank - 1, len(values) - 1)
            return float(values[idx])

    return 0.0


def _parse_passive_damage(
    passive: dict[str, Any],
    level: int,
    champion_stats: dict[str, float] | None = None,
    total_ability_power: float = 0.0,
) -> float:
    """Parse Ambessa passive damage per proc from JSON leveling data.

    The passive has per-level base values (20 values for levels 1-20)
    extracted from the wiki's ``data-bot-values`` attribute, plus a
    bonus AD scaling ratio embedded in the effect description (not
    always present as a leveling modifier).

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        champion_stats: Champion stats for bonus AD scaling.
        total_ability_power: Total AP.

    Returns:
        Damage per passive proc before resistances.
    """
    stats_context = dict(champion_stats) if champion_stats else {}
    stats_context["ability_power"] = total_ability_power

    for effect in passive.get("effects", []):
        for leveling in effect.get("leveling", []):
            attribute = leveling.get("attribute", "")
            if attribute != "Per-Level Scaling":
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            base_values = modifiers[0].get("values", [])
            if not base_values:
                continue

            clamped_level = max(1, min(level, len(base_values)))
            base_damage = float(base_values[clamped_level - 1])

            # Remaining modifiers: scaling ratios (if present)
            bonus_damage = 0.0
            for modifier in modifiers[1:]:
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values or not units:
                    continue
                value = float(values[0])
                unit = units[0] if units else ""
                if is_flat_unit(unit):
                    bonus_damage += value
                else:
                    bonus_damage += resolve_scaling(
                        unit, value, stats_context, None,
                    )

            # The bonus AD scaling is in the description but not
            # always in leveling modifiers — extract from text.
            if not modifiers[1:]:
                desc = effect.get("description", "")
                ad_match = re.search(
                    r"\(\+\s*(\d+(?:\.\d+)?)%\s+bonus\s+AD\)", desc,
                )
                if ad_match:
                    ratio = float(ad_match.group(1)) / 100.0
                    bonus_ad = stats_context.get(
                        "bonus_attack_damage", 0.0,
                    )
                    bonus_damage += ratio * bonus_ad

            return base_damage + bonus_damage

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
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Ambessa's abilities and calculate damage.

    Args:
        champion_data: Ambessa's champion data dictionary from JSON.
        level: Champion level (1-20).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"sweetspot": bool}`` — if True (default), Q uses sweetspot
            (increased) damage values instead of normal cast damage.
            ``{"passive_procs": int}`` — number of passive procs in the
            fight (default 4).
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (for %HP abilities).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    sweetspot = True
    if champion_options and "sweetspot" in champion_options:
        sweetspot = bool(champion_options["sweetspot"])

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
        return get_ability_rank(key, level, "Ambessa")

    # ── R: Public Execution (stat buff + damage) ─────────────────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]

            # Passive: armor penetration per rank
            armor_pen = _extract_leveling_value(
                r_ability, "Armor Penetration", r_rank,
            )

            # Active: physical damage
            r_damage = _extract_leveling_damage(
                r_ability, "Physical Damage", r_rank, stats_context,
                target_stats,
            )
            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "Public Execution"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "physical",
                "physical_damage": r_damage,
                "total_raw": r_damage,
                "stat_buff": {
                    "armor_penetration_percent": armor_pen,
                },
            }

    # ── Q1: Cunning Sweep ─────────────────────────────────────────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])

        # Q has two ability entries: Q1 (Cunning Sweep) and Q2 (Sundering Slam)
        q1_ability = q_ability_list[0] if len(q_ability_list) >= 1 else None
        q2_ability = q_ability_list[1] if len(q_ability_list) >= 2 else None

        if q1_ability:
            attr_name = (
                "Increased Physical Damage" if sweetspot
                else "Physical Damage"
            )
            q1_damage = _extract_leveling_damage(
                q1_ability, attr_name, q_rank, stats_context, target_stats,
            )
            q1_cooldown = extract_cooldown(q1_ability, q_rank)

            results["Q"] = {
                "name": q1_ability.get("name", "Cunning Sweep"),
                "rank": q_rank,
                "cooldown": q1_cooldown,
                "damage_type": "physical",
                "physical_damage": q1_damage,
                "total_raw": q1_damage,
            }

        if q2_ability:
            attr_name = (
                "Increased Physical Damage" if sweetspot
                else "Physical Damage"
            )
            q2_damage = _extract_leveling_damage(
                q2_ability, attr_name, q_rank, stats_context, target_stats,
            )
            # Q2 shares Q1's cooldown (recast follows every Q1)
            q2_cooldown = q1_cooldown if q1_ability else 0.0

            results["Q2"] = {
                "name": q2_ability.get("name", "Sundering Slam"),
                "rank": q_rank,
                "cooldown": q2_cooldown,
                "recast_of": "Q",
                "damage_type": "physical",
                "physical_damage": q2_damage,
                "total_raw": q2_damage,
            }

    # ── W: Repudiation (always increased damage) ─────────────────────
    w_rank = rank_for("W")
    if w_rank > 0:
        w_ability_list = abilities_data.get("W", [])
        if w_ability_list:
            w_ability = w_ability_list[0]
            w_damage = _extract_leveling_damage(
                w_ability, "Increased Physical Damage", w_rank,
                stats_context, target_stats,
            )
            w_cooldown = extract_cooldown(w_ability, w_rank)

            if w_damage > 0:
                results["W"] = {
                    "name": w_ability.get("name", "Repudiation"),
                    "rank": w_rank,
                    "cooldown": w_cooldown,
                    "damage_type": "physical",
                    "physical_damage": w_damage,
                    "total_raw": w_damage,
                }

    # ── E: Lacerate (both hits) ──────────────────────────────────────
    e_rank = rank_for("E")
    if e_rank > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]
            e_damage = _extract_leveling_damage(
                e_ability, "Total Physical Damage", e_rank,
                stats_context, target_stats,
            )
            e_cooldown = extract_cooldown(e_ability, e_rank)

            if e_damage > 0:
                results["E"] = {
                    "name": e_ability.get("name", "Lacerate"),
                    "rank": e_rank,
                    "cooldown": e_cooldown,
                    "damage_type": "physical",
                    "physical_damage": e_damage,
                    "total_raw": e_damage,
                }

    # ── P: Drakehound's Step (empowered auto procs) ──────────────────
    if passive_procs > 0:
        passive_list = abilities_data.get("P", [])
        if passive_list:
            per_proc = _parse_passive_damage(
                passive_list[0], level, champion_stats, total_ability_power,
            )
            if per_proc > 0:
                results["passive"] = {
                    "name": passive_list[0].get(
                        "name", "Drakehound's Step",
                    ),
                    "damage_type": "physical",
                    "physical_damage": per_proc,
                    "total_raw": per_proc * passive_procs,
                    "proc_count": passive_procs,
                }

    return results
