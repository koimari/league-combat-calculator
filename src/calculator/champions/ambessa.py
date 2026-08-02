"""Ambessa — slot map for the archetype engine.

Why each slot is non-generic:
- Q is TWO JSON entries under one slot: Q1 (Cunning Sweep, index 0)
  and Q2 (Sundering Slam, index 1). Both are ``by_option(sweetspot)``
  attr picks (default True = "Increased Physical Damage"); Q2 reads
  ``source=("Q", 1)`` with ``cooldown_from=("Q", 0)`` — the engine's
  slot keys map to themselves, so the synthetic "Q2" results key needs
  no engine support — and a thin wrapper stamps the ``recast_of: "Q"``
  marker damage.py uses to chain the recast after Q1.
- R (Public Execution) is a ``stat_buff`` (% armor penetration the
  fight engine applies — not a parse-time scaling stat, so no
  apply_to) that also carries its active "Physical Damage".
- W (Repudiation) always models the empowered hit — the "Increased
  Physical Damage" attribute the classifier would not pick.
- E (Lacerate) hits twice — the "Total Physical Damage" attribute.
- P (Drakehound's Step) is a custom fn: per-proc damage is a per-LEVEL
  base plus a bonus-AD ratio that lives only in the description text
  (regex-extracted, see ``_parse_passive_damage``), multiplied by the
  ``passive_procs`` option (default 4) — the shape proc_damage emits,
  but the extraction is not attribute-driven.

All numeric values are read from the champion JSON data (the passive's
AD ratio from its description text); nothing is hardcoded.
"""

import re
from typing import Any

from .engine import SlotCtx, SlotParser, build_parser
from .slotlib import (
    by_option,
    find_named_leveling,
    proc_damage,
    simple_damage,
    stat_buff,
    sum_modifiers,
)


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
    always present as a leveling modifier) — regex-extracted from
    ``"(+ N% bonus AD)"``. (Test seam: tests/test_ambessa.py validates
    the JSON values here.)

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

    leveling = find_named_leveling(passive, "Per-Level Scaling")
    if leveling is None:
        return 0.0

    damage = sum_modifiers(leveling, level, stats_context)
    modifiers = leveling.get("modifiers", [])
    if len(modifiers) > 1:
        return damage

    # The bonus AD scaling is in prose when structured scaling is absent.
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        ad_match = re.search(r"\(\+\s*(\d+(?:\.\d+)?)%\s+bonus\s+AD\)", desc)
        if ad_match:
            ratio = float(ad_match.group(1)) / 100.0
            return damage + ratio * stats_context.get("bonus_attack_damage", 0.0)

    return damage


def _drakehounds_step_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """Resolve one Drakehound's Step proc from structured data/prose."""
    return _parse_passive_damage(
        ability, ctx.level, ctx.stats, ctx.stats.get("ability_power", 0.0)
    )


def _drakehounds_step(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: damage plus the energy restored by each selected empowered attack."""
    entry = proc_damage(_drakehounds_step_damage, "physical")(ctx)
    if entry is None:
        return None
    # Wiki revision 4038211 supplies the 1/7/13 thresholds. The locally
    # ingested champion JSON carries the three values in the passive prose.
    description = " ".join(
        effect.get("description", "")
        for effect in (ctx.ability() or {}).get("effects", [])
    )
    match = re.search(
        r"restore\s+(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*/\s*"
        r"(\d+(?:\.\d+)?)\s*\(based on level\)\s*energy",
        description,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError("Ambessa passive energy restoration is unavailable")
    values = tuple(float(value) for value in match.groups())
    index = 0 if ctx.level < 7 else 1 if ctx.level < 13 else 2
    entry["resource_restore_per_proc"] = values[index]
    return entry


def _q_cast(index: int) -> SlotParser:
    """Sweetspot-dispatched Q entry at *index* (0 = Q1, 1 = Q2)."""
    return by_option(
        "sweetspot",
        {
            True: simple_damage(
                attr="Increased Physical Damage",
                dmg_type="physical",
                source=("Q", index),
                cooldown_from=("Q", 0),
            ),
            False: simple_damage(
                attr="Physical Damage",
                dmg_type="physical",
                source=("Q", index),
                cooldown_from=("Q", 0),
            ),
        },
        default=True,
    )


_q2_damage = _q_cast(1)


def _sundering_slam(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q2: the Q recast entry, marked recast_of for the fight engine."""
    entry = _q2_damage(ctx)
    if entry is not None:
        entry["recast_of"] = "Q"
    return entry


OPTIONS = [
    {
        "key": "sweetspot",
        "type": "bool",
        "default": True,
        "label": "Q/Q2 Sweetspot (doubled damage)",
    },
    {
        "key": "passive_procs",
        "type": "int",
        "default": 4,
        "label": "Passive procs",
        "min": 0,
        "max": 20,
    },
]

ASSUMPTIONS = [
    "R passive (armor penetration) is always active when R is skilled",
    "W always uses increased (empowered) damage",
    "E always hits twice (both passes)",
    "Q2 (Sundering Slam) shown separately from Q1 (Cunning Sweep)",
]

SLOTS = {
    "R": stat_buff(
        "Armor Penetration",
        "armor_penetration_percent",
        damage_attr="Physical Damage",
    ),
    "Q": _q_cast(0),
    "Q2": _sundering_slam,
    "W": simple_damage(attr="Increased Physical Damage", dmg_type="physical"),
    "E": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "P": _drakehounds_step,
}

parse_abilities = build_parser(SLOTS, "Ambessa")
