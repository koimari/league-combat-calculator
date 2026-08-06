"""Sion — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- Q (Decimating Smash) is a charged strike: the wiki lists a "Minimum
  Physical Damage" row (30 / 45 / 60 / 75 / 90 + 40 / 50 / 60 / 70 /
  80% AD) and a "Maximum Physical Damage" row (90 / 155 / 220 / 285 /
  350 + 120 / 150 / 180 / 210 / 240% AD), with the charge increasing
  damage every 0.25 seconds up to 2 seconds.  The previous packet read
  the "Maximum Base Damage Increase" percentage row (200% : 288.89%) as
  a flat damage number, dropping both physical-damage rows and the AD
  scaling.  The corrected parser interpolates between the minimum and
  maximum physical-damage rows by the ``q_charge_fraction`` option
  (default 1.0 = fully charged, matching the burst model's Kled R
  convention).
- W (Soul Furnace) is a plain "Magic Damage" read (40 / 65 / 90 / 115 /
  140 + 40% AP + 14% of target's maximum health) for the shield recast.
- E (Roar of the Slayer) is a plain "Magic Damage" read (65 / 100 / 135
  / 170 / 205 + 55% AP).
- R (Unstoppable Onslaught) prices the charge's maximum physical damage
  (400 / 800 / 1200 + 120% bonus AD), the same max-charge boundary the
  packet priced.
- P (Glory in Death) deals no enemy damage and is an explicit no-damage
  slot.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .reviewed_batch_07 import _full_entry_sources
from .slotlib import extract_cooldown, extract_named, simple_damage
from ..ability_spec import DamagePart


def _no_damage(slot: str, reason: str):
    """Emit an explicit zero-damage entry for a non-damaging slot."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def _decimating_smash(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: minimum/maximum physical damage interpolated by charge time."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    fraction = max(0.0, min(1.0, float(ctx.options.get("q_charge_fraction", 1.0))))
    low = extract_named(ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target)
    high = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    value = low + (high - low) * fraction
    return {
        "name": ability.get("name", "Decimating Smash"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value),),
        "detail": (
            f"Minimum/Maximum Physical Damage rows interpolated by charge "
            f"fraction {fraction:.2f}"
        ),
    }


def _roar_of_the_slayer(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: magic damage + the sourced 25% armor reduction for 4 seconds.

    The cached E description pins the debuff ("inflicts them with 25%
    armor reduction for 4 seconds"); damage.py applies a target_debuff
    AFTER this ability's own damage, so every later physical hit (autos,
    Q, R) benefits but the E hit itself does not.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = {
        "name": ability.get("name", "Roar of the Slayer"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": value,
        "parts": (DamagePart("magic", value),),
        "target_debuff": {
            "armor_reduction_percent": 25.0,
            "duration": 4.0,
        },
        "detail": (
            "Magic Damage row plus the cached 25% armor reduction for 4 "
            "seconds (wiki prose on E); the shred applies after E's own "
            "hit."
        ),
    }
    return entry


ASSUMPTIONS = [
    "Q (Decimating Smash) interpolates the Minimum/Maximum Physical "
    "Damage rows by charge time; the default is fully charged "
    "(q_charge_fraction 1.0).",
    "R (Unstoppable Onslaught) prices the maximum-charge slam (Maximum "
    "Physical Damage row).",
    "P deals no enemy damage and is an explicit no-damage slot.",
    "E (Roar of the Slayer) inflicts the cached 25% armor reduction for "
    "4 seconds (wiki prose on E); the target_debuff applies after E's "
    "own damage, so all later physical damage (autos, Q, R) benefits.",
]

SOURCES = list(_full_entry_sources("Sion"))

SLOTS = {
    "P": _no_damage(
        "P",
        "Glory in Death is a post-death reanimation state; no enemy damage.",
    ),
    "Q": _decimating_smash,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _roar_of_the_slayer,
    "R": simple_damage(attr="Maximum Physical Damage", dmg_type="physical"),
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}

OPTIONS = [
    {
        "key": "q_charge_fraction",
        "type": "float",
        "default": 1.0,
        "label": "Q charge fraction",
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
    },
]

parse_abilities = build_parser(SLOTS, "Sion")
REVIEW_STATUS = "reviewed_module"
