"""Maokai — Sapling Toss brush empowerment burn (E4 summon damage).

Why E is non-generic:
- E (Sapling Toss) throws a Sapling that explodes on the first nearby
  enemy (the reviewed CP10.4 packet prices this single "Magic Damage"
  explosion).  A Sapling thrown into brush is EMPOWERED: its explosion
  deals 66.7% damage to non-minion targets AND attaches two Saplings to
  the target that explode every 0.75 seconds over 1.5 seconds.  The
  empowered total is the cache's "Total Magic Damage" leveling row and
  the burn is its "Total Attached Sapling Damage" row (2 ticks of the
  "Magic Damage per Instance" row) — the E2 DoT tick-count convention.
  The ``sapling_empowered`` option (default on — brush saplings are the
  standard usage) swaps the plain explosion for the empowered
  explosion + burn.
- P/Q/W/R keep the reviewed CP10.4 packet pricing (P is the periodic
  Sap Magic empowered-auto state).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "f3732d39aae761199c06bfc606515aee50fa1cc74ea65f28a15b0ef78d02f366"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module(
        "Maokai",
        PACKET_SHA256,
        # The shockwave, the dash's arrival hit and each bramble deal
        # their packet once, at the cast (none of the three carries a
        # sourced travel time) — the boundary claim that carries
        # MODULE_CC's reviewed kinds into the event ledger.  Q is a
        # wiki_attribute slot, which this compiler does not certify, so
        # it says the same thing through ``_bramble_smash`` below.
        single_hit_slots=frozenset({"W", "R"}),
    )
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec

# HARDCODED cadence: the attached-sapling burn ticks every 0.75 seconds
# over 1.5 seconds (2 ticks) — wiki description of the brush-empowered
# Sapling Toss, cross-checked against the cache's leveling rows
# (Total Attached Sapling Damage == 2 x Magic Damage per Instance).
_ATTACHED_TICKS = 2
_ATTACHED_TICK_INTERVAL = 0.75


def _sapling_toss(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Sapling Toss — plain explosion or brush-empowered burst+burn."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    cooldown = extract_cooldown(ability, rank)
    if not bool(ctx.options.get("sapling_empowered", True)):
        explosion = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability.get("name", "Sapling Toss"),
            rank,
            cooldown,
            explosion,
            "magic",
        )
        # One explosion, at the cast: the boundary claim that carries
        # MODULE_CC's reviewed slow for E into the event ledger on this
        # branch (the empowered branch's parts author their own timing).
        entry["event_order_certified"] = "single_hit"
        entry["detail"] = (
            "Un-empowered Sapling: single explosion of the sourced Magic Damage "
            "row; set sapling_empowered to price the brush-empowered burn."
        )
        return entry

    per_instance = extract_named(
        ability, "Magic Damage per Instance", rank, ctx.stats, ctx.target
    )
    # Empowered total == 3 x per-instance (explosion 1 instance at 66.7%
    # of the base + 2 burn ticks) == the cache's Total Magic Damage row.
    entry = damage_entry(
        ability.get("name", "Sapling Toss (Empowered)"),
        rank,
        cooldown,
        per_instance * (1 + _ATTACHED_TICKS),
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_instance, time_offset=0.25),
        DamagePart(
            "magic",
            per_instance,
            count=_ATTACHED_TICKS,
            time_offset=0.5,
            hit_interval=_ATTACHED_TICK_INTERVAL,
        ),
    )
    entry["detail"] = (
        f"Brush-empowered Sapling: explosion at 66.7% (1 x {per_instance:.2f}) "
        f"plus {_ATTACHED_TICKS} attached-Sapling ticks of {per_instance:.2f} "
        "magic every 0.75s — the sourced Total Magic Damage row; the 45% slow "
        "and reveal are state"
    )
    return entry


def _bramble_smash(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the packet's shockwave, certified as the one hit it is."""
    entry = _BATCH_SLOTS["Q"](ctx)
    if entry is not None:
        entry["event_order_certified"] = "single_hit"
    return entry


OPTIONS = [
    {
        "key": "sapling_empowered",
        "type": "bool",
        "default": True,
        "label": "Sapling thrown into brush (empowered burn)",
    },
]

ASSUMPTIONS = [
    "Every slot is an explicit packet or sourced no-damage entry from the "
    "pinned local Wiki cache; no runtime archetype inference is used.",
    "Numeric packets preserve rank/level arrays, typed scaling, target-health "
    "terms, and explicit variant selectors where the source lists them.",
    "The complete parent Wiki entry was read before certifying this module.",
    "Passive plus Q/W/E/R entries are represented by explicit packet or "
    "no-damage slot declarations.",
    "Rank arrays, cooldowns, typed target-health terms, and packet variants "
    "remain sourced from the local reviewed-packet asset.",
    "Non-damaging shields, buffs, movement, and utility branches remain "
    "explicit state/out-of-scope rows rather than invented damage.",
    "Sapling Toss defaults to the brush-empowered branch: the explosion deals "
    "66.7% damage to non-minion targets and attaches two Saplings that burn "
    "every 0.75s over 1.5s (2 ticks) — the sourced Total Magic Damage / Total "
    "Attached Sapling Damage rows (E2 DoT tick-count convention)",
    "The sapling's 30-second sit duration, 2.5-second chase, 45% slow, "
    "reveal, and the 300 cap against non-champions are state, not modeled",
]

SLOTS = {
    "P": _BATCH_SLOTS["P"],
    "Q": _bramble_smash,
    "W": _BATCH_SLOTS["W"],
    "E": _sapling_toss,
    "R": _BATCH_SLOTS["R"],
}


# Cached kit review: Q's shockwave "slows them by 99% for 0.25 seconds"
# (the additional stun and knock-back land only on enemies "near
# Maokai", a position this pair fight does not model), W's arrival
# "roots them for a duration", E's sapling explosion slows "by 45% for 2
# seconds", and each R bramble "roots them for 0.75 : 2.25 (based on
# distance travelled) seconds".  P is a self-heal on-hit.
MODULE_CC = {"Q": "slow", "W": "root", "E": "slow", "R": "root"}

parse_abilities = build_parser(SLOTS, "Maokai", cc_kinds=MODULE_CC)
SOURCES = _BATCH_SOURCES
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
