"""Rengar — Ferocity (4-stack) empowered-ability system.

Stack mechanics modeled (E3):
- P (Unseen Predator): casting a basic ability generates a Ferocity
  stack (cap 4). At maximum stacks the next basic ability consumes them
  to become EMPOWERED: the empowered Q/W/E replaces the base ability's
  damage with the wiki "Ferocity Bonus" sourced values (per-level
  arrays). ``p_ferocity`` is the explicit pre-stack state; at 4 the
  Q/W/E rows price the empowered values.
- Q (Savagery) base: "Additional Physical Damage" (20 : 160 by rank
  + 5% AD); empowered: "Bonus Physical Damage" (35 : 260 by level
  + 20% AD).  The reviewed CP10.6 packet misread the per-level
  Ferocity-Bonus array as per-rank base damage; this module prices the
  rank array for base and the level array for the empower.
- W (Battle Roar) base: "Magic Damage" (50 : 170 + 80% AP); empowered:
  "Bonus Magic Damage" (50 : 240 by level + 80% AP).
- E (Bola Strike) base: "Physical Damage" (55 : 235 + 80% bonus AD);
  empowered: "Bonus Physical Damage" (50 : 335 by level + 80% bonus AD).

R (Thrill of the Hunt) keeps the reviewed CP10.6 packet pricing
(armor reduction and leap bonus are state). All numeric values are read
from the champion JSON data.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "bc9f962c63c4eaabd3333b892d9f7d876578e1d3ae0f9fe1fb0256afb3232d50"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module("Rengar", PACKET_SHA256)
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec
_FEROCITY_MAX = 4


def _ferocity_bonus(
    ctx: SlotCtx, ability: dict[str, Any], attribute: str
) -> float | None:
    """Extract the Ferocity-Bonus leveling value for one ability.

    The W ability stores two "Bonus Magic Damage" arrays (the monster
    bonus and the Ferocity bonus); the Ferocity one is the effect whose
    description carries "Ferocity Bonus".  Returns None when absent.
    """
    for effect in ability.get("effects", []):
        if "Ferocity Bonus" not in effect.get("description", ""):
            continue
        leveling = find_named_leveling({"effects": [effect]}, attribute)
        if leveling is None:
            return None
        return sum_modifiers(leveling, ctx.level, ctx.stats, ctx.target)
    return None


def _ferocity(ctx: SlotCtx) -> int:
    return min(max(int(ctx.option("p_ferocity")), 0), _FEROCITY_MAX)


def _unseen_predator(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Ferocity stack state row (no enemy damage)."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = _ferocity(ctx)
    state = (
        "next basic ability is EMPOWERED (consumes all 4 stacks)"
        if stacks >= _FEROCITY_MAX
        else f"{stacks}/4 Ferocity stacks; at 4 the next basic ability is empowered"
    )
    return no_damage(
        ctx,
        name=ability.get("name", "Unseen Predator"),
        reason=(
            f"Ferocity: {state}.  Bonetooth Necklace trophies (up to 5, "
            "1-36% bonus AD) are state; brush leap is mobility state."
        ),
    )


def _savagery(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Savagery — base or Ferocity-empowered (level array) bonus damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    if _ferocity(ctx) >= _FEROCITY_MAX:
        bonus = _ferocity_bonus(ctx, ability, "Bonus Physical Damage") or 0.0
        entry = damage_entry(
            ability.get("name", "Savagery"),
            rank,
            extract_cooldown(ability, rank),
            bonus,
            "physical",
        )
        entry["detail"] = (
            "Ferocity-empowered: 35 : 260 by level + 20% AD (the wiki "
            "Ferocity Bonus), consuming all 4 stacks."
        )
    else:
        bonus = extract_named(
            ability, "Additional Physical Damage", rank, ctx.stats, ctx.target
        )
        entry = damage_entry(
            ability.get("name", "Savagery"),
            rank,
            extract_cooldown(ability, rank),
            bonus,
            "physical",
        )
        entry["detail"] = (
            "Base Savagery: 20 : 160 by rank + 5% AD on the first "
            "empowered basic attack; the attack can crit at "
            "(100% + 30%) AD effectiveness."
        )
    entry["parts"] = (DamagePart("physical", entry["total_raw"]),)
    return entry


def _battle_roar(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Battle Roar — base or Ferocity-empowered (level array) magic damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    if _ferocity(ctx) >= _FEROCITY_MAX:
        damage = _ferocity_bonus(ctx, ability, "Bonus Magic Damage") or 0.0
        entry = damage_entry(
            ability.get("name", "Battle Roar"),
            rank,
            extract_cooldown(ability, rank),
            damage,
            "magic",
        )
        entry["detail"] = (
            "Ferocity-empowered: 50 : 240 by level + 80% AP (the wiki "
            "Ferocity Bonus), consuming all 4 stacks."
        )
    else:
        damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability.get("name", "Battle Roar"),
            rank,
            extract_cooldown(ability, rank),
            damage,
            "magic",
        )
        entry["detail"] = (
            "Base Battle Roar: 50 : 170 by rank + 80% AP; the grey-health "
            "heal is state."
        )
    entry["parts"] = (DamagePart("magic", entry["total_raw"]),)
    return entry


def _bola_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Bola Strike — base or Ferocity-empowered (level array) physical damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    if _ferocity(ctx) >= _FEROCITY_MAX:
        damage = _ferocity_bonus(ctx, ability, "Bonus Physical Damage") or 0.0
        entry = damage_entry(
            ability.get("name", "Bola Strike"),
            rank,
            extract_cooldown(ability, rank),
            damage,
            "physical",
        )
        entry["detail"] = (
            "Ferocity-empowered: 50 : 335 by level + 80% bonus AD (the "
            "wiki Ferocity Bonus), consuming all 4 stacks; the root is "
            "crowd-control state."
        )
    else:
        damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability.get("name", "Bola Strike"),
            rank,
            extract_cooldown(ability, rank),
            damage,
            "physical",
        )
        entry["detail"] = (
            "Base Bola Strike: 55 : 235 by rank + 80% bonus AD; the slow "
            "and reveal are state."
        )
    entry["parts"] = (DamagePart("physical", entry["total_raw"]),)
    return entry


SLOTS = {
    "P": _unseen_predator,
    "Q": _savagery,
    "W": _battle_roar,
    "E": _bola_strike,
    "R": _BATCH_SLOTS["R"],
}
parse_abilities = build_parser(SLOTS, "Rengar")

OPTIONS = [
    {
        "key": "p_ferocity",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "label": "Ferocity stacks (4 = empowered next)",
    },
]

ASSUMPTIONS = [
    "W (Battle Roar) stores 50% of post-mitigation damage taken in the "
    "last 1.5 seconds as grey health and the active heals the stored "
    "pool (the E8a grey-health primitive authors the heal from the "
    "incoming ledger at each W cast)",
    "Ferocity caps at 4 stacks (1-second expiry not modeled); at 4 stacks "
    "the next Q/W/E cast is empowered and prices the wiki Ferocity Bonus "
    "values, consuming all stacks",
    "p_ferocity is the explicit pre-stack state; 0 prices base Q/W/E",
    "The reviewed CP10.6 packet misread Q's per-level Ferocity Bonus array "
    "as per-rank base damage; this module prices base Q from the rank "
    "array (20 : 160 + 5% AD) and the empower from the level array "
    "(35 : 260 + 20% AD)",
    "R (Thrill of the Hunt) keeps the reviewed packet pricing; its armor "
    "reduction and leap bonus are target/state effects",
]

SOURCES = load_champion_sources("Rengar")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
