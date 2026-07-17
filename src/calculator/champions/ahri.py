"""Ahri — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Orb of Deception) deals its "Damage Per Pass" twice — magic
  outgoing, true returning: ``casts=2`` with the mixed split (half
  magic / half true) reproduces exactly one pass of each type.
- W (Fox-Fire) is three flames at two damage tiers: two DamageParts
  (initial + subsequent ``count=2``) so each flame mitigates separately.
- R (Spirit Rush) is three dashes per activation: one ``count=3`` part
  plus ``cast_instances=3`` (per-dash item procs), with no cooldown key
  so damage.py spaces the dashes itself.
- E (Charm) is generic besides pinning the damage type.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import extract_auto, extract_cooldown, extract_named, simple_damage


def _fox_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: initial flame + 2 subsequent flames at reduced damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    initial = extract_named(ability, "Primary Magic Damage", rank, ctx.stats)
    subsequent = extract_named(ability, "Subsequent Magic Damage", rank, ctx.stats)

    return {
        "name": ability.get("name", "Fox-Fire"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "parts": (
            DamagePart("magic", initial),
            DamagePart("magic", subsequent, count=2),
        ),
        "total_raw": initial + (subsequent * 2),
        "damage_type": "magic",
    }


def _spirit_rush(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: three dashes emitted as one activation without a cooldown field."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    per_cast, damage_type = extract_auto(ability, rank, ctx.stats, ctx.target)
    casts = 3
    return {
        "name": ability.get("name", "Spirit Rush"),
        "rank": rank,
        "parts": (DamagePart(damage_type, per_cast, count=casts),),
        "cast_instances": casts,
        "total_raw": per_cast * casts,
        "damage_type": damage_type,
    }


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS: list[str] = []

SLOTS = {
    "Q": simple_damage(attr="Damage Per Pass", dmg_type="mixed", casts=2),
    "W": _fox_fire,
    "E": simple_damage(dmg_type="magic"),
    "R": _spirit_rush,
}

parse_abilities = build_parser(SLOTS, "Ahri")
