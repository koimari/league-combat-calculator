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
- E (Charm) is a single, event-certified magic hit whose Wiki-authored
  charm/knockdown marker feeds conditional item triggers such as Fimbulwinter.
- P (Essence Theft) deals no enemy damage: the module emits a zero-damage
  receipt for the 9-fragment heal (35 : 95 by level + 20% AP, cached P
  "Heal" row) so the E1 self-heal rule can author one heal per fight when
  the user's fragment count has reached 9.  The champion-takedown heal
  (75 : 165 by level + 30% AP) is a kill boundary the fight model does not
  produce.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import extract_auto, extract_cooldown, extract_named, simple_damage


def _essence_theft(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt for the 9-fragment self-heal.

    Emitted only when the user's fragment count has reached 9 (the sourced
    stack cap in the cached P description); the E1 heal rule in healing.py
    gates its one-per-fight heal on this receipt.  The fragment count itself
    is player state (fragments come from minion/monster kills, which the
    champion duel does not simulate), so it is exposed as an option.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    fragments = max(0, int(ctx.options.get("p_essence_fragments", 9)))
    if fragments < 9:
        return None
    return {
        "name": ability.get("name", "Essence Theft"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"{fragments} Essence Fragment(s): at 9 stacks the passive heals "
            "35 : 95 (based on level) (+ 20% AP); the champion-takedown heal "
            "(75 : 165 by level + 30% AP) is a kill boundary, not a fight "
            "receipt."
        ),
    }


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


def _charm(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: one magic hit with the authored charm/knockdown control marker."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    damage = extract_auto(ability, rank, ctx.stats, ctx.target)[0]
    return {
        "name": ability.get("name", "Charm"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "parts": (DamagePart("magic", damage, cc_kind="immobilize"),),
        "total_raw": damage,
        "damage_type": "magic",
        "event_order_certified": "single_hit",
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "p_essence_fragments",
        "type": "int",
        "default": 9,
        "min": 0,
        "max": 18,
        "label": (
            "Essence Fragment stacks (9 = the passive heal is ready and "
            "consumes them)"
        ),
    },
]

ASSUMPTIONS = [
    "P (Essence Theft) consumes 9 Essence Fragments to heal 35 : 95 "
    "(based on level) (+ 20% AP) — the cached P 'Heal' leveling row; "
    "fragment generation comes from minion/monster kills the 1v1 model "
    "does not simulate, so the user supplies the stack count "
    "(p_essence_fragments, default 9) and the heal fires once per fight "
    "on the first ability that hits the enemy champion",
    "The champion-takedown heal (75 : 165 by level + 30% AP) is a kill "
    "boundary — a takedown ends the fight before a heal receipt can apply",
]

SLOTS = {
    "P": _essence_theft,
    "Q": simple_damage(attr="Damage Per Pass", dmg_type="mixed", casts=2),
    "W": _fox_fire,
    "E": _charm,
    "R": _spirit_rush,
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"

parse_abilities = build_parser(SLOTS, "Ahri")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Ahri",
        "revision_id": 4047800,
        "revision_timestamp": "2026-07-31T01:16:52Z",
    }
]
