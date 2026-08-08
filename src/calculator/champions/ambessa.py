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
from .scaling import is_flat_unit, resolve_scaling
from .slotlib import (
    attach_self_shield,
    by_option,
    find_named_leveling,
    proc_damage,
    simple_damage,
    stat_buff,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — Repudiation's shield duration (1.5s)
# is prose in the cached ability description ("shields herself ... for 1.5
# seconds"); the shield base and 150% bonus-AD ratio are cached leveling
# rows read live below.
_REPUDIATION_SHIELD_DURATION_SECONDS = 1.5


def _repudiation_shield_amount(ctx: SlotCtx) -> float:
    """W's shield: a per-LEVEL base (40 cached values, 50 at level 1 and
    320 at level 18) plus 150% bonus AD.

    ``sum_modifiers`` indexes every modifier by RANK, so the 40-value
    level row would read values[4] = 113.53 at W rank 5; the shield's
    base is level-indexed, matching the wiki's "50 : 320 (based on
    level)" prose.  Long arrays (>= 18 values) are level-indexed here,
    short arrays rank-indexed.
    """
    ability = ctx.ability()
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, "Shield")
    if leveling is None:
        raise ValueError("Ambessa W Shield leveling row is unavailable")
    total = 0.0
    rank = ctx.rank_for()
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        if len(values) >= 18:
            index = min(max(ctx.level - 1, 0), len(values) - 1)
        else:
            index = min(max(rank - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        total += (
            value
            if is_flat_unit(unit)
            else resolve_scaling(unit, value, ctx.stats, ctx.target)
        )
    return total


def _repudiation(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the empowered hit plus the sourced self-shield payload.

    The shield is granted at the cast (the damage event timestamp); the
    shared ledger converts the ``self_shield_events`` payload into a
    timed 1.5-second self-shield.  The generic ally-support scanner
    defers this slot (``support_effects._MODULE_AUTHORED_SHIELD_SLOTS``)
    because its rank-based derivation cannot read the level-indexed
    base.
    """
    entry = _packet_w(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = _repudiation_shield_amount(ctx)
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_REPUDIATION_SHIELD_DURATION_SECONDS,
        source=entry.get("name", "Repudiation"),
        detail=(
            f"W also shields Ambessa for {shield:g} for "
            f"{_REPUDIATION_SHIELD_DURATION_SECONDS:g}s (self)"
        ),
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
    # Medarda Maxim is consumed by empowered basic attacks; its proc count
    # must be coupled to the authored auto timeline rather than treated as a
    # free fixed-count damage package.
    entry["requires_auto_timeline_coupling"] = True
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

SLOTS = dict(SLOTS)
_packet_w = SLOTS["W"]
SLOTS["W"] = _repudiation
parse_abilities = build_parser(SLOTS, "Ambessa")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Repudiation) also shields Ambessa at the cast for the level-indexed "
    "base (50 : 320 by level) + 150% bonus AD for 1.5s; the shield absorbs "
    "incoming damage in the participant ledger.",
]


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Ambessa",
        "revision_id": 4043663,
        "revision_timestamp": "2026-07-15T17:40:27Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Ambessa")
