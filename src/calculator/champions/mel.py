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

Coverage:

- P (Searing Brilliance) is ``modeled``.  Its volley — one 8 : 30 (based
  on level) (+ 4% AP) magic projectile per stack, up to 9, off the next
  basic attack — is priced behind the explicit ``p_searing_brilliance``
  option.  Overwhelm, the other half of the passive, stays unpriced and
  stays a documented kill boundary rather than a coverage gap: it pays
  its stored damage only once that total already exceeds the target's
  current health and shields, and R already prices the stacks it
  detonates.
- W (Rebuttal) stays ``out_of_scope``, and the missing axis is an enemy
  projectile.  Its damage is a percentage of an incoming projectile's own
  damage, and the calculator's target is a stat block that never attacks,
  so there is nothing to reflect.
"""

import math

from ..ability_spec import DamagePart
from .packet_module import build_packet_module
from .engine import SlotCtx
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "4729cb0ee938dd410196bc3e6ea901bac4caf07fbe25859ce9532c9bf6648aea"


# Default Overwhelm stacks the blast detonates in a one-rotation combo.
# P prose: "Mel's basic attacks and abilities apply a stack of Overwhelm
# for each instance of damage they deal"; Q alone fires 10 bolts, so a
# modest 3-stack default is conservative and user-tunable.
_R_DEFAULT_OVERWHELM_STACKS = 3
# The per-stack term's fixed AP ratio: " (+ 4% AP) per Overwhelm stack".
_R_PER_STACK_AP_RATIO = 0.04

# Searing Brilliance: "Mel's ability casts each generate 3 stacks ... up to
# 9 times.  Her next basic attack consumes all stacks ... to additionally
# fire an equal number of blazing projectiles at the target.  Each
# projectile deals 8 : 30 (based on level) (+ 4% AP) magic damage, for a
# total possible damage of 72 : 270 (based on level) (+ 36% AP) at maximum
# stacks."  The cache carries both per-level rows under one repeated
# "Per-Level Scaling" attribute (index 0 per projectile, index 1 at nine
# stacks) and the parser drops both AP ratios, so the ratio below is
# HARDCODED: verify on patch updates against
# https://wiki.leagueoflegends.com/en-us/Mel .  The two rows cross-check
# each other at parse time (9 x index 0 == index 1).
_P_PROJECTILE_AP_RATIO = 0.04
_P_MAX_STACKS = 9


def _searing_brilliance(packet_passive):
    """P: the packet's state row, plus the Searing Brilliance volley.

    The volley is the half of Mel's passive that is ordinary damage: N
    stacks means N magic projectiles off the next basic attack, each the
    cached per-level row plus the prose AP ratio.  ``p_searing_brilliance``
    is the explicit pre-stack state (default 0, as Samira's Style and
    Yasuo's Gathering Storm are), because how many casts precede the auto
    is the player's, not something to infer.

    Overwhelm — the other half — stays unpriced and stays documented: it
    stores damage and pays it only once the stored total already exceeds
    the target's current health and shields, so it is a kill boundary like
    an execute threshold, not damage a full-health rotation deals.
    """

    def parse(ctx: SlotCtx):
        entry = packet_passive(ctx)
        if entry is None:
            return entry
        stacks = min(max(int(ctx.option("p_searing_brilliance")), 0), _P_MAX_STACKS)
        if stacks < 1:
            return entry
        ability = ctx.ability("P", 0)
        if ability is None:
            return entry
        flat = sum_modifiers(
            find_named_leveling(ability, "Per-Level Scaling", 0), ctx.level
        )
        at_max = sum_modifiers(
            find_named_leveling(ability, "Per-Level Scaling", 1), ctx.level
        )
        if not math.isclose(flat * _P_MAX_STACKS, at_max, rel_tol=1e-3):
            raise ValueError(
                "Mel P: the cached per-projectile row x 9 no longer equals "
                "the maximum-stacks row — the 9-stack cap pinned here has "
                "changed upstream"
            )
        per_projectile = flat + _P_PROJECTILE_AP_RATIO * float(
            ctx.stat("ability_power") or 0.0
        )
        entry["damage_type"] = "magic"
        entry["total_raw"] = per_projectile * stacks
        # One volley, fired by one basic attack: the projectiles leave
        # together, so they share an instant, and the whole row is a single
        # proc that cannot happen in a fight with no swing to carry it.
        entry["parts"] = (
            DamagePart(
                "magic",
                per_projectile,
                count=stacks,
                time_offset=0.0,
                hit_interval=0.0,
            ),
        )
        entry["proc_count"] = 1
        entry["requires_auto_timeline_coupling"] = True
        entry["detail"] = (
            f"{stacks}/{_P_MAX_STACKS} Searing Brilliance stacks: the next "
            f"basic attack fires {stacks} projectile(s) of "
            f"{per_projectile:g} magic each (8 : 30 by level + 4% AP).  "
            "Overwhelm's stored damage is a kill boundary and is not priced."
        )
        return entry

    return parse


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
    per_stack += _R_PER_STACK_AP_RATIO * float(ctx.stat("ability_power") or 0.0)
    stacks = int(ctx.options.get("r_overwhelm_stacks", _R_DEFAULT_OVERWHELM_STACKS))
    stacks = max(0, min(stacks, 50))
    total = flat_share + per_stack * stacks
    entry = damage_entry(
        ability.get("name", "Golden Eclipse"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        # One radiant blast on the marked target, so one part and one hit —
        # the certification that carries R's reviewed "no control" into the
        # event ledger.
        event_order_certified="single_hit",
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
    # The two halves of Solar Snare do not control alike — "enemies hit by
    # the orb are dealt magic damage and rooted for 1.5 seconds", while
    # "enemies within the field are dealt magic damage and slowed by 30%
    # every 0.125 seconds" — so the reviewed kind is authored per part
    # rather than declared once for the slot.
    entry["parts"] = (
        DamagePart("magic", amount=orb, time_offset=0.0, cc_kind="root"),
        DamagePart(
            "magic",
            amount=per_tick,
            count=4,
            time_offset=0.5,
            hit_interval=0.125,
            cc_kind="slow",
        ),
    )
    entry["dot_duration"] = 0.5
    entry["detail"] = (
        f"orb {orb:g} + 4 field ticks of {per_tick:g} (0.5s DoT at "
        "8 ticks/s, game-file MelE DoTDuration)"
    )
    return entry


# Reviewed crowd control, read from the cached kit.  Q (Radiant Volley)
# is bolts that "explode[] upon landing to deal magic damage to nearby
# enemies" with no control clause, and R (Golden Eclipse) "deal[s] magic
# damage to each of them" and reveals, which is not control.  E's orb and
# field answer differently and are authored per part (see
# ``_solar_snare``).  P's Searing Brilliance projectiles "fire ... at the
# target" and do nothing else, so the slot answers "none" once its volley
# authors parts; W authors no damage part of its own.
MODULE_CC = {"P": "none", "Q": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mel",
    PACKET_SHA256,
    slot_parsers={
        "W": _rebuttal,
        "Q": _radiant_volley,
        "E": _solar_snare,
        "R": _golden_eclipse,
    },
    slot_wrappers={"P": _searing_brilliance},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_searing_brilliance",
        "type": "int",
        "default": 0,
        "label": "Searing Brilliance stacks (3 per ability cast, cap 9)",
        "min": 0,
        "max": _P_MAX_STACKS,
        "rotation": {"role": "self_state", "slot": "P"},
    },
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
    "P (Searing Brilliance) prices the volley behind the explicit "
    "p_searing_brilliance option (default 0, so a default request is "
    "unchanged): each stack is one projectile of the cached per-level "
    "row (8 : 30 by level) plus the prose 4% AP, and the module "
    "cross-checks 9 x that row against the cached maximum-stacks row "
    "(72 : 270).  The 3-stacks-per-cast generation, the 5s window and "
    "the next-basic-attack trigger are state, not cadence this module "
    "infers.",
]
MODULE_COVERAGE = {
    slot: ("out_of_scope" if slot == "W" else "modeled") for slot in "PQWER"
}
