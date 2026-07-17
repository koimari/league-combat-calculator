"""Akshan — slot map for the archetype engine.

The design's honest ceiling: most of Akshan's numbers live in
description TEXT rather than leveling data, so this module is mostly
custom fns over regex extraction — deliberately NOT archetypes, since
no other champion shares these mechanics.

Why each slot is non-generic:
- Q (Avengerang) hits on both passes — the "Total Physical Damage"
  attribute (the classifier would pick the single-pass value).
- E (Heroic Swing) fires ``e_shots`` shots (option, default 5); the
  per-shot leveling data uses unusual unit strings ("×" for the flat
  base, a prose per-100%-bonus-AS ratio) handled by the
  ``_extract_e_per_shot`` seam.
- R (Comeuppance) is min-damage-per-bullet × stored bullets, plus two
  fight-engine scaling constants from wiki prose (see below): crits
  amplify at 30% effectiveness and missing HP scales the barrage up to
  +200%.
- P (Dirty Fighting) is TWO results entries from one JSON passive:
  ``passive_double_shot`` (every auto fires a second shot at a %AD
  ratio regex-read from the description) and ``passive`` (the 3-stack
  magic proc whose level breakpoints and AP ratio are also
  description text, × the ``passive_procs`` option, default 3).
- W (Going Rogue) is stealth/revive utility — not modeled, absent
  from the slot map.

All numeric values are read from the champion JSON data (several from
description text) except the two R scaling constants below, which are
wiki prose with no JSON home.
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    proc_damage,
    simple_damage,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# https://wiki.leagueoflegends.com/en-us/Akshan
# R bullets can crit at 30% effectiveness (3% damage per 10% crit
# chance) and scale up to +200% based on the target's missing health.
_R_CRIT_EFFECTIVENESS = 0.3
_R_MISSING_HP_MAX_BONUS = 2.0


def _extract_e_per_shot(
    ability: dict[str, Any],
    rank: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Extract Heroic Swing per-shot damage from JSON.

    The JSON has modifiers with unusual unit strings (``"  ×"`` for flat
    damage) and a prose AS ratio ("+N per 100% bonus attack speed").
    (Test seam: tests/test_akshan.py validates the JSON values here.)

    Args:
        ability: E ability dict from champion JSON.
        rank: E rank (1-indexed).
        stats_context: Champion stats for AD/AS scaling.

    Returns:
        Physical damage per shot before resistances.
    """
    leveling = find_named_leveling(ability, "Physical Damage per Shot")
    if leveling is None:
        return 0.0

    def unusual_unit(unit: str, value: float) -> float | None:
        unit_stripped = unit.strip()
        if not unit_stripped or unit_stripped in ("×", "x"):
            return value
        if "per 100% bonus attack speed" not in unit:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)\s*per\s*100%", unit)
        if not match:
            return 0.0
        as_ratio = float(match.group(1))
        bonus_as_pct = (
            stats_context.get("bonus_attack_speed_percent", 0.0)
            if stats_context
            else 0.0
        )
        return as_ratio * (bonus_as_pct / 100.0) * value

    return sum_modifiers(
        leveling,
        rank,
        stats_context,
        modifier_override=unusual_unit,
    )


def _parse_passive_proc_damage(
    passive: dict[str, Any],
    level: int,
    stats_context: dict[str, float] | None = None,
) -> float:
    """Parse Dirty Fighting 3-stack proc magic damage from the JSON.

    The structured leveling data contains shield values (labelled
    "Bonus Damage"), not the proc damage. The proc breakpoints
    (15/40/80/150 based on level) and 60% AP ratio are description
    text, so they are regex-extracted. (Test seam: tests/test_akshan.py
    validates the JSON values here.)

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        stats_context: Champion stats (for AP).

    Returns:
        Magic damage per proc before resistances.
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        # Match "deal them N / N / N / N (based on level) (+ N% AP)".
        dmg_match = re.search(
            r"deal them (\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*"
            r"\(based on level\)",
            desc,
        )
        if not dmg_match:
            continue

        breakpoints = [int(dmg_match.group(i)) for i in range(1, 5)]
        # Standard 4-breakpoint levels: 1, 6, 11, 16.
        if level >= 16:
            base = float(breakpoints[3])
        elif level >= 11:
            base = float(breakpoints[2])
        elif level >= 6:
            base = float(breakpoints[1])
        else:
            base = float(breakpoints[0])

        ap_match = re.search(r"\+\s*(\d+)%\s*AP", desc)
        ap_ratio = float(ap_match.group(1)) / 100.0 if ap_match else 0.0

        ap = stats_context.get("ability_power", 0.0) if stats_context else 0.0
        return base + ap_ratio * ap

    return 0.0


def _extract_double_shot_ratio(passive: dict[str, Any]) -> float:
    """Extract the double shot AD ratio from the passive description.

    The description says the additional shot deals ``50% AD`` physical
    damage. (Test seam: tests/test_akshan.py validates it here.)
    """
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        match = re.search(r"deals?\s+(\d+)%\s*AD\s+physical damage", desc)
        if match:
            return float(match.group(1)) / 100.0
    return 0.5  # Fallback


def _heroic_swing(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: per-shot damage x ``e_shots`` option (default 5)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    shots = int(ctx.options.get("e_shots", 5))
    if rank < 1 or shots <= 0:
        return None

    per_shot = _extract_e_per_shot(ability, rank, ctx.stats)
    if per_shot <= 0:
        return None

    name = ability.get("name", "Heroic Swing")
    cooldown = extract_cooldown(ability, rank)
    return damage_entry(name, rank, cooldown, per_shot * shots, "physical")


def _comeuppance(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: min damage per bullet x stored bullets + crit/missing-HP flags.

    Uses "Minimum Physical Damage per Bullet" — the JSON's "Maximum"
    variant already has the 3x missing-HP multiplier baked in; the
    fight engine applies that scaling itself from the flags.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_bullet = extract_named(
        ability, "Minimum Physical Damage per Bullet", rank, ctx.stats, ctx.target
    )
    bullets = int(extract_value(ability, "Maximum Bullets Stored", rank))

    name = ability.get("name", "Comeuppance")
    total = per_bullet * bullets
    entry = damage_entry(name, rank, extract_cooldown(ability, rank), total, "physical")
    # Barrage scales up to +200% with target missing HP; crits amplify
    # at 30% effectiveness (both wiki-prose constants, see module doc).
    entry["parts"] = (
        DamagePart(
            "physical",
            hp_scaled_damage=lambda missing: total
            * (1.0 + _R_MISSING_HP_MAX_BONUS * missing),
            crit_effectiveness=_R_CRIT_EFFECTIVENESS,
        ),
    )
    return entry


def _double_shot(ctx: SlotCtx) -> dict[str, Any] | None:
    """passive_double_shot: every auto fires a second %AD shot."""
    passive = ctx.ability("P")
    if passive is None:
        return None
    return {
        "name": "Dirty Fighting (Double Shot)",
        "double_shot": {
            "name": "Dirty Fighting (Double Shot)",
            "ad_ratio": _extract_double_shot_ratio(passive),
        },
    }


def _dirty_fighting_damage(ctx: SlotCtx, passive: dict[str, Any]) -> float:
    """Resolve one Dirty Fighting three-stack proc from description text."""
    return _parse_passive_proc_damage(passive, ctx.level, ctx.stats)


OPTIONS = [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 3,
        "label": "Passive procs (3-stack)",
        "min": 0,
        "max": 20,
    },
    {
        "key": "e_shots",
        "type": "int",
        "default": 5,
        "label": "E shots fired",
        "min": 0,
        "max": 20,
    },
]

ASSUMPTIONS = [
    "Q always hits both passes (outgoing and return)",
    "R assumes full channel (max bullets at max damage)",
    "R crit scaling at 30% effectiveness applied",
    "Double shot applies on-hit effects and can crit",
    "W is utility only (no damage)",
]

SLOTS = {
    "Q": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "E": _heroic_swing,
    "R": _comeuppance,
    "passive_double_shot": _double_shot,
    "P": proc_damage(
        _dirty_fighting_damage,
        "magic",
        default_count=3,
        name="Dirty Fighting (3-Stack Proc)",
    ),
}

parse_abilities = build_parser(SLOTS, "Akshan")
