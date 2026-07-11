"""Akshan ability parsing and damage calculation.

Custom module needed because:
- P (Dirty Fighting): Two-part passive. Part 1: double shot on every auto
  (50% AD, applies on-hits and crits). Part 2: 3-stack magic damage proc
  with user-configurable count.
- Q (Avengerang): Boomerang that hits twice — use Total Physical Damage.
- W (Going Rogue): Utility only, skipped.
- E (Heroic Swing): Fires multiple shots during swing — user-configurable
  shot count with unusual per-shot scaling (flat + % AD + AS scaling).
- R (Comeuppance): Fully-channeled bullet barrage with crit chance and
  crit damage scaling at 30% effectiveness.

All numeric values are read from the champion JSON data.
"""

import re
from typing import Any

from .common import (
    build_stats_context,
    extract_leveling_damage,
    extract_leveling_value,
    make_rank_fn,
)
from .generic_parser import extract_cooldown
from .scaling import is_flat_unit, resolve_scaling


def _extract_e_per_shot(
    ability: dict[str, Any],
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract Heroic Swing per-shot damage from JSON.

    The JSON has modifiers with unusual unit strings (``"  ×"`` for flat
    damage).  This function manually handles them.

    Args:
        ability: E ability dict from champion JSON.
        rank: E rank (1-indexed).
        stats_context: Champion stats for AD scaling.

    Returns:
        Physical damage per shot before resistances.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Physical Damage per Shot":
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

                # The flat base uses "  ×" (multiplication sign) as its unit
                unit_stripped = unit.strip()
                if not unit_stripped or unit_stripped in ("×", "x"):
                    total += value
                elif is_flat_unit(unit):
                    total += value
                elif "per 100% bonus attack speed" in unit:
                    # E has a small AS scaling: +0.3 per 100% bonus AS.
                    # Parse the ratio from the unit string.
                    match = re.search(r"(\d+(?:\.\d+)?)\s*per\s*100%", unit)
                    if match:
                        as_ratio = float(match.group(1))
                        bonus_as_pct = stats_context.get(
                            "bonus_attack_speed_percent", 0.0,
                        ) if stats_context else 0.0
                        total += as_ratio * (bonus_as_pct / 100.0) * value
                else:
                    total += resolve_scaling(
                        unit, value, stats_context, None,
                    )
            return total

    return 0.0


def _parse_passive_proc_damage(
    passive: dict[str, Any],
    level: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Parse Dirty Fighting 3-stack proc magic damage from the JSON.

    The structured leveling data in the JSON contains shield values
    (labelled ``"Bonus Damage"``), not the actual proc damage.  The proc
    damage breakpoints (``15 / 40 / 80 / 150`` based on level) and
    ``60% AP`` scaling are embedded in the effect description text, so
    we parse them from there.

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        stats_context: Champion stats (for AP).

    Returns:
        Magic damage per proc before resistances.
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        # Match "deal them N / N / N / N (based on level) (+ N% AP)"
        dmg_match = re.search(
            r"deal them (\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*"
            r"\(based on level\)",
            desc,
        )
        if not dmg_match:
            continue

        breakpoints = [int(dmg_match.group(i)) for i in range(1, 5)]
        # Standard 4-breakpoint levels: 1, 6, 11, 16
        if level >= 16:
            base = float(breakpoints[3])
        elif level >= 11:
            base = float(breakpoints[2])
        elif level >= 6:
            base = float(breakpoints[1])
        else:
            base = float(breakpoints[0])

        # Extract AP ratio from "(+ N% AP)"
        ap_match = re.search(r"\+\s*(\d+)%\s*AP", desc)
        ap_ratio = float(ap_match.group(1)) / 100.0 if ap_match else 0.0

        ap = stats_context.get("ability_power", 0.0) if stats_context else 0.0
        return base + ap_ratio * ap

    return 0.0


def _extract_double_shot_ratio(passive: dict[str, Any]) -> float:
    """Extract the double shot AD ratio from the passive description.

    The description says the additional shot deals ``50% AD`` physical
    damage.

    Args:
        passive: Passive ability dict from champion JSON.

    Returns:
        AD ratio as a decimal (e.g. 0.5 for 50%).
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        match = re.search(r"deals?\s+(\d+)%\s*AD\s+physical damage", desc)
        if match:
            return float(match.group(1)) / 100.0
    return 0.5  # Fallback


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
    """Parse Akshan's abilities and calculate damage.

    Args:
        champion_data: Akshan's champion data dictionary from JSON.
        level: Champion level (1-20).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional dict of ability key -> rank override.
        champion_options: Champion-specific options. Supports:
            ``{"passive_procs": int, "e_shots": int}``.
        champion_stats: Champion's calculated stats (for AD scaling).
        target_stats: Target stats (unused for Akshan).

    Returns:
        Dictionary with ability key -> damage information.
    """
    abilities_data = champion_data.get("abilities", {})
    results: dict[str, dict[str, Any]] = {}

    # Default champion options
    passive_procs = 3
    e_shots = 5
    if champion_options:
        if "passive_procs" in champion_options:
            passive_procs = int(champion_options["passive_procs"])
        if "e_shots" in champion_options:
            e_shots = int(champion_options["e_shots"])

    stats_context = build_stats_context(champion_stats, total_ability_power)
    rank_for = make_rank_fn("Akshan", ability_ranks, level)

    # ── Q: Avengerang (both passes — Total Physical Damage) ──────────
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_ability_list = abilities_data.get("Q", [])
        if q_ability_list:
            q_ability = q_ability_list[0]
            q_damage = extract_leveling_damage(
                q_ability, "Total Physical Damage", q_rank, stats_context,
            )
            q_cooldown = extract_cooldown(q_ability, q_rank)

            if q_damage > 0:
                results["Q"] = {
                    "name": q_ability.get("name", "Avengerang"),
                    "rank": q_rank,
                    "cooldown": q_cooldown,
                    "damage_type": "physical",
                    "physical_damage": q_damage,
                    "total_raw": q_damage,
                }

    # W: Going Rogue — no damage, skipped

    # ── E: Heroic Swing (configurable shots) ─────────────────────────
    e_rank = rank_for("E")
    if e_rank > 0 and e_shots > 0:
        e_ability_list = abilities_data.get("E", [])
        if e_ability_list:
            e_ability = e_ability_list[0]
            per_shot = _extract_e_per_shot(
                e_ability, e_rank, stats_context,
            )
            e_cooldown = extract_cooldown(e_ability, e_rank)
            e_total = per_shot * e_shots

            if per_shot > 0:
                results["E"] = {
                    "name": e_ability.get("name", "Heroic Swing"),
                    "rank": e_rank,
                    "cooldown": e_cooldown,
                    "damage_type": "physical",
                    "physical_damage": e_total,
                    "total_raw": e_total,
                }

    # ── R: Comeuppance (fully charged, crit scaling) ─────────────────
    r_rank = rank_for("R")
    if r_rank > 0:
        r_ability_list = abilities_data.get("R", [])
        if r_ability_list:
            r_ability = r_ability_list[0]

            # Use "Minimum Physical Damage per Bullet" — this is the
            # actual base per bullet (no missing HP scaling).  The JSON's
            # "Maximum Physical Damage per Bullet" already has the 3×
            # missing-HP multiplier baked in.
            min_per_bullet = extract_leveling_damage(
                r_ability, "Minimum Physical Damage per Bullet",
                r_rank, stats_context,
            )
            num_bullets = int(extract_leveling_value(
                r_ability, "Maximum Bullets Stored", r_rank,
            ))
            r_base = min_per_bullet * num_bullets
            r_cooldown = extract_cooldown(r_ability, r_rank)

            results["R"] = {
                "name": r_ability.get("name", "Comeuppance"),
                "rank": r_rank,
                "cooldown": r_cooldown,
                "damage_type": "physical",
                "physical_damage": r_base,
                "total_raw": r_base,
                # Crit scaling at 30% effectiveness — applied by damage.py
                "crit_effectiveness": 0.3,
                # Missing HP scaling: 0-200% bonus (3× at 0 HP)
                "missing_hp_max_bonus": 2.0,
            }

    # ── P: Dirty Fighting — Double Shot (on-hit per auto) ────────────
    passive_list = abilities_data.get("P", [])
    if passive_list:
        ad_ratio = _extract_double_shot_ratio(passive_list[0])
        ad = stats_context.get("attack_damage", 0.0)

        results["passive_double_shot"] = {
            "name": "Dirty Fighting (Double Shot)",
            "double_shot": {
                "name": "Dirty Fighting (Double Shot)",
                "ad_ratio": ad_ratio,
            },
        }

    # ── P: Dirty Fighting — 3-Stack Proc (magic damage) ──────────────
    if passive_procs > 0 and passive_list:
        per_proc = _parse_passive_proc_damage(
            passive_list[0], level, stats_context,
        )
        if per_proc > 0:
            results["passive"] = {
                "name": "Dirty Fighting (3-Stack Proc)",
                "damage_type": "magic",
                "magic_damage": per_proc,
                "total_raw": per_proc * passive_procs,
                "proc_count": passive_procs,
            }

    return results
