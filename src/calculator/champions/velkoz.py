"""Vel'Koz — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- P (Organic Deconstruction) is the stack system: Vel'Koz's abilities
  apply Deconstruction stacks (max 3, 7s, refreshing; basic attacks
  refresh but do not add). The third stack consumes all stacks to deal
  level-scaled TRUE damage ("Per-Level Scaling" 35-197.06 array) plus
  60% AP (prose ratio). The rotation's damaging abilities (Q, W x2
  hits, E, R ticks) always exceed three applications, so the proc is
  priced once per fight — the conservative floor (Brand's Blaze
  once-per-rotation precedent); R's repeated 0.7s Deconstruction
  applications could proc more in a long channel.
- Q (Plasma Fission), W (Void Rift), E (Tectonic Disruption) are plain
  attribute reads: W uses "Total Magic Damage" (both rift hits — the
  classifier would pick only the first).
- R (Life Form Disintegration Ray) (E9-3) prices the full 13-tick
  channel: 13 x "Damage Per Tick" == "Maximum Damage" (450/700/925) at
  the sourced 0.2-second cadence over the 2.6-second channel (the E2
  per-tick x count pattern). The Researched true-damage conversion is
  a documented boundary, not modeled.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the proc's 60% AP ratio exists
# only in the passive's description prose; the leveling array carries
# only the flat level values.
_PROC_AP_RATIO = 0.6  # "35 : 197.06 (based on level) (+ 60% AP)"
_PROC_STACKS = 3
_PROC_LEVELING_ATTR = "Per-Level Scaling"


def _organic_deconstruction(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: one 3-stack true-damage consume per fight, when 3+ abilities land."""
    ability = ctx.ability()
    if ability is None:
        return None

    # Deconstruction stacks come from damaging abilities (Q, W's two
    # rift hits, E, R). Any full rotation applies 3+, so a fight with
    # the rotation present prices one proc. An autos-only window casts
    # none of them, and a basic attack only refreshes a stack it cannot
    # create, so the counter never leaves zero.
    if ctx.option("auto_attacks_only"):
        return None
    applications = sum(1 for slot in ("Q", "W", "E", "R") if slot in ctx.results)
    if applications < _PROC_STACKS:
        return None

    flat = extract_named(ability, _PROC_LEVELING_ATTR, ctx.level, ctx.stats, ctx.target)
    ap = ctx.stat("ability_power")
    total = flat + _PROC_AP_RATIO * ap
    return {
        "name": ability.get("name", "Organic Deconstruction"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "true",
        "total_raw": total,
        "parts": (DamagePart("true", total),),
        "proc_count": 1,
        # One sourced event per fight: the 3-stack consume fires once the
        # rotation's abilities have landed (the applications gate above).
        # The declared event is placed at the fight-window end — the
        # engine's end-of-rotation fallback this ledger replaces — so
        # ordering-certifying the row does not move its ledger position
        # and cannot change window-order item outcomes (e.g.
        # Shadowflame's threshold).  damage.py re-prices the declared
        # event at the proc's mitigated total.
        "event_phase": "effect",
        "damage_events": [
            {
                "time": float(ctx.option("fight_duration_seconds") or 0.0),
                "damage_type": "true",
                "damage": total,
                "event_precision": "phase_order",
            }
        ],
        "detail": (
            f"3 Deconstruction stacks consumed at level {ctx.level} "
            f"({flat:.2f} + {_PROC_AP_RATIO * 100:g}% AP)"
        ),
    }


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Organic Deconstruction procs once per fight: the rotation's "
    "damaging abilities apply 3+ stacks (Q, W's two rift hits, E, and R "
    "ticks), so the conservative floor is one 3-stack consume per fight",
    "An autos-only fight never reaches the third stack (the pipeline "
    "states this with the auto_attacks_only reserved option): the cached "
    "P text sources stacking to \"Vel'Koz's abilities apply a stack of "
    "Deconstruction to enemies hit for 7 seconds, refreshing on basic "
    'attacks on-hit" — a swing refreshes a stack it cannot create',
    "Proc damage = the 'Per-Level Scaling' array value at the champion's "
    "level (35 at 1 up to 197.06 at 19+) + 60% AP (prose ratio, module "
    "constant)",
    "R prices the full 13-tick channel: 13 x 'Damage Per Tick' == the "
    "'Maximum Damage' row (450/700/925) at the sourced 0.2-second "
    "cadence over the 2.6-second channel; the Researched true-damage "
    "conversion is not modeled",
    "The Researched mark (applying 3 stacks marks the target for 7s, "
    "making R deal true damage) is not modeled — R stays magic",
    "Q slow and W sight are utility; E's sourced 0.75-second knockup and "
    "stun count as target action downtime",
]

# HARDCODED: verify on patch updates — the 13-tick channel count is the
# sourced Total/PerTick ratio (Maximum Damage 450/700/925 == 13 x Damage
# Per Tick 34.62/53.85/71.15 at every rank); the 0.2-second cadence and
# 2.6-second channel length are prose in the cached R description
# ("channels for up to 2.6 seconds" / "deals magic damage ... every 0.2
# seconds").
_R_TICKS = 13
_R_TICK_INTERVAL_SECONDS = 0.2
_R_CHANNEL_SECONDS = 2.6


def _disintegration_ray(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the full 13-tick channel (per-tick x 13 == the Maximum Damage row)."""
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    per_tick = extract_named(ability, "Damage Per Tick", rank, ctx.stats, ctx.target)
    total = per_tick * _R_TICKS
    entry = damage_entry(
        ability.get("name", "Life Form Disintegration Ray"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_R_TICKS,
            time_offset=_R_TICK_INTERVAL_SECONDS,
            hit_interval=_R_TICK_INTERVAL_SECONDS,
        ),
    )
    entry["dot_duration"] = _R_CHANNEL_SECONDS
    entry["detail"] = (
        f"full {_R_TICKS}-tick channel ({_R_TICKS} x Damage Per Tick "
        f"{per_tick:.2f} == Maximum Damage {total:.2f} at rank {rank}); "
        "the Researched true-damage conversion is not modeled"
    )
    return entry


SLOTS = {
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": simple_damage(
        attr="Total Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # E's interval is read off the cached "Knock Up Duration" row, so the
    # ledger gets the sourced 0.75s rather than a restated constant.
    "E": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        kind="knockup",
        duration_attr="Knock Up Duration",
    ),
    "R": _disintegration_ray,  # already authors its 13-tick channel timing
    "P": _organic_deconstruction,  # after the damage slots: reads their emissions
}

# Q's bolt "slows them by 70% decaying over a duration" and R's beam
# "slows them by 20%, lingering for 1 second"; E lands "knocking them up
# and stunning them for 0.75 seconds" — the airborne is the kind, and the
# stun rides the same cast.  W's rift only "deal[s] magic damage to enemies
# within", both on the cascade and on the collapse.  P is the Deconstruction
# consume: its true-damage row is not an ability event, so it carries no
# reviewable marker.
MODULE_CC = {"Q": "slow", "W": "none", "E": "knockup", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Vel'Koz", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Vel'Koz")
