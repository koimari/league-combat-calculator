"""Mel — CP10.4 full-entry-reviewed packet module.

E5-2 fixes:

- W (Rebuttal): the reviewed spec read "Replicated Projectile Magic
  Damage Modifier" (40-60% + 5% per 100 AP) as FLAT magic damage.  That
  attribute is a percentage of the ORIGINAL enemy projectile's damage;
  the calculator models no enemy projectile source, so the slot prices
  no damage (shield + conditional reflection are state, documented).

- R (Golden Eclipse): the reviewed spec read only the flat "Magic
  Damage" row (125/200/275 + 30% AP) and dropped the per-Overwhelm-
  stack term.  The wiki row's third modifier is "(4/7/10 + 4% AP) per
  Overwhelm stack on the target" (data/champions.json R "Magic
  Damage"), and P's Overwhelm prose says Mel applies a stack for each
  damage instance.  R now prices the flat row PLUS the per-stack term
  times an explicit ``r_overwhelm_stacks`` option (default 3 — the
  Overwhelm stacks accumulated before the blast in a one-rotation
  combo).  The P stored-damage execute (first stack stores
  50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack,
  consumed when the stored total exceeds the target's current health)
  is a kill-boundary execute and is documented, not priced as damage.
"""

from ..ability_spec import DamagePart
from .reviewed_batch_04 import build_batch_module
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Mel")

# Default Overwhelm stacks the blast detonates in a one-rotation combo.
# P prose: "Mel's basic attacks and abilities apply a stack of Overwhelm
# for each instance of damage they deal"; Q alone fires 10 bolts, so a
# modest 3-stack default is conservative and user-tunable.
_R_DEFAULT_OVERWHELM_STACKS = 3
# The per-stack term's fixed AP ratio: " (+ 4% AP) per Overwhelm stack".
_R_PER_STACK_AP_RATIO = 0.04


def _rebuttal(ctx: SlotCtx):
    """W: shield + conditional projectile reflection — no modeled damage.

    Rebuttal reflects enemy projectiles at 40-60% (+ 5% per 100 AP) of
    their ORIGINAL damage; with no enemy projectile source in the
    calculator, pricing the modifier as flat damage would invent damage.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return {
        "name": ability.get("name", "Rebuttal"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Rebuttal shields Mel and reflects enemy projectiles at "
            "40-60% (+ 5% per 100 AP) of their original damage; no enemy "
            "projectile source is modeled, so the slot prices no damage."
        ),
    }


def _golden_eclipse(ctx: SlotCtx):
    """R: flat Magic Damage row + (4/7/10 + 4% AP) per Overwhelm stack."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    # The wiki's "Magic Damage" row: flat + 30% AP + per-stack term.  The
    # per-stack unit (" (+ 4% AP) per Overwhelm stack on the target") is
    # not a generic scaling unit, so the flat+AP share comes from the row
    # and the per-stack share is priced explicitly below.
    flat_share = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    per_stack += _R_PER_STACK_AP_RATIO * float(
        ctx.stats.get("ability_power", 0.0) or 0.0
    )
    stacks = int(ctx.options.get("r_overwhelm_stacks", _R_DEFAULT_OVERWHELM_STACKS))
    stacks = max(0, min(stacks, 50))
    total = flat_share + per_stack * stacks
    entry = damage_entry(
        ability.get("name", "Golden Eclipse"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["detail"] = (
        f"{flat_share:g} flat + {per_stack:g} per Overwhelm stack x "
        f"{stacks} stack(s)"
    )
    return entry


def _radiant_volley(ctx: SlotCtx):
    """Q: the full 6-10 bolt volley — Initial Explosion + subsequent bolts.

    The reviewed packet priced only the "Initial Explosion Magic Damage"
    row.  The wiki's "Total Magic Damage" row equals the initial
    explosion plus (Number of Bolts - 1) subsequent explosions (160 + 9 x
    13 == 277 at rank 5, and the AP shares 55 + 9 x 5 == 100), so one
    cast against the primary target prices every bolt that lands in the
    target area.  The volley launches over the sourced 0.5 seconds, with
    the bolts distributing evenly.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    initial = extract_named(
        ability, "Initial Explosion Magic Damage", rank, ctx.stats, ctx.target
    )
    subsequent = extract_named(
        ability, "Magic Damage per Subsequent Explosion", rank, ctx.stats, ctx.target
    )
    bolts = max(1, int(extract_value(ability, "Number of Bolts", rank)))
    total = initial + subsequent * (bolts - 1)
    entry = damage_entry(
        ability.get("name", "Radiant Volley"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    interval = 0.5 / bolts
    entry["parts"] = (
        DamagePart("magic", amount=initial, time_offset=0.0),
        DamagePart(
            "magic",
            amount=subsequent,
            count=bolts - 1,
            time_offset=interval,
            hit_interval=interval,
        ),
    )
    entry["detail"] = (
        f"{bolts} bolts: initial explosion {initial:g} + {bolts - 1} x "
        f"subsequent {subsequent:g} over the 0.5s volley"
    )
    return entry


def _solar_snare(ctx: SlotCtx):
    """E: orb hit + the solar-field DoT (game-file-sourced 0.5s window).

    The reviewed packet priced only the orb.  The orb also emanates a
    field that deals "Field Magic Damage per Tick" every 0.125 seconds;
    the game files (mel.bin.json MelE DataValues) source the field's
    DoTDuration as 0.5s at AreaTicksPerSecond 8, so a target inside the
    field takes 4 ticks (2 / 3.5 / 5 / 6.5 / 8 + 1% AP each), matching
    the wiki's per-second row (8 x per-tick == Field Magic Damage per
    Second) over the 0.5s window.  The field expands after the sourced
    0.5-second delay, so the first tick lands at 0.5s.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    orb = extract_named(ability, "Orb Magic Damage", rank, ctx.stats, ctx.target)
    per_tick = extract_named(
        ability, "Field Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    total = orb + per_tick * 4
    entry = damage_entry(
        ability.get("name", "Solar Snare"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", amount=orb, time_offset=0.0),
        DamagePart(
            "magic",
            amount=per_tick,
            count=4,
            time_offset=0.5,
            hit_interval=0.125,
        ),
    )
    entry["dot_duration"] = 0.5
    entry["detail"] = (
        f"orb {orb:g} + 4 field ticks of {per_tick:g} (0.5s DoT at "
        "8 ticks/s, game-file MelE DoTDuration)"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _rebuttal
SLOTS["Q"] = _radiant_volley
SLOTS["E"] = _solar_snare
SLOTS["R"] = _golden_eclipse
parse_abilities = build_parser(SLOTS, "Mel")

OPTIONS = list(OPTIONS) + [
    {
        "key": "r_overwhelm_stacks",
        "type": "int",
        "default": _R_DEFAULT_OVERWHELM_STACKS,
        "label": "Overwhelm stacks on the target when Golden Eclipse detonates",
        "min": 0,
        "max": 50,
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Rebuttal) prices no damage: the 'Replicated Projectile Magic "
    "Damage Modifier' (40-60% + 5% per 100 AP) is a percentage of the "
    "original enemy projectile's damage, and the calculator models no "
    "enemy projectile source (data/champions.json W).",
    "Q (Radiant Volley) prices the full volley: 'Initial Explosion "
    "Magic Damage' + (Number of Bolts - 1) x 'Magic Damage per "
    "Subsequent Explosion' == the wiki's 'Total Magic Damage' row "
    "(data/champions.json Q), all bolts landing on the primary target "
    "over the sourced 0.5s volley.",
    "E (Solar Snare) prices the orb hit plus the field DoT: 4 ticks of "
    "'Field Magic Damage per Tick' (data/champions.json E) at 0.125s "
    "intervals — the game-file MelE DataValues source DoTDuration 0.5s "
    "at AreaTicksPerSecond 8 (raw.communitydragon.org mel.bin.json), "
    "starting after the 0.5s field-expansion delay.",
    "R (Golden Eclipse) prices the wiki's 'Magic Damage' row "
    "(125/200/275 + 30% AP) plus (4/7/10 + 4% AP) per Overwhelm stack "
    "on the target (data/champions.json R), with the stack count from "
    "the r_overwhelm_stacks option (default 3).",
    "The Overwhelm stored-damage execute (P: first stack stores "
    "50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack, "
    "consumed when stored damage exceeds the target's current health "
    "and shields) is a kill boundary and is documented, not priced as "
    "damage.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
