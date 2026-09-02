"""Nautilus — CP10.5 full-entry-reviewed packet module.

E5-2 fix — Staggering Blow (P): the reviewed packet read the passive's
root-duration row ("Bonus Damage" 0.75-1.5 seconds) as a flat physical
damage amount and dropped the actual damage term.  The wiki text is:
"Nautilus' basic attacks are empowered to deal 14 : 128 (based on level)
bonus physical damage" (data/champions.json P "Per-Level Scaling" row),
so the passive is an on-hit entry priced at the per-level value.  The
0.75-1.5 "Bonus Damage" row is the root duration (a CC state, not
damage) and is deliberately not priced.

P1-2 fixes:
- W (Titan's Wrath) prices the Total Magic Damage of Pain of Wrath
  (30 : 70 by rank + 40% AP) split across its two sourced instances
  (half immediately, half after 1.25 seconds) instead of one Magic
  Damage per Instance row.
- R (Depth Charge) prices the primary-target Increased Damage
  (150 : 400 by rank + 80% AP) instead of the chase-eruption Magic
  Damage row: the wake eruptions hit enemies around the charge's path,
  not the primary target of the single-target fight.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import innate_on_hit, ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

# HARDCODED: verify on patch updates — Pain of Wrath's second instance
# lands 1.25 seconds after the first (wiki W effect prose; the JSON
# carries no timing).
_W_SECOND_INSTANCE_DELAY = 1.25

PACKET_SHA256 = "66ae84d11488386be94ff6ac41a99478d1d5d6394c98003813b547dbda249172"


# P: empowered basic attacks deal 14 : 128 (based on level) bonus
# physical damage — the "Per-Level Scaling" leveling row.
_staggering_blow = innate_on_hit("Per-Level Scaling", "physical")


@ranked_slot
def _titans_wrath(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: Pain of Wrath's Total Magic Damage across both instances."""
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    half = total / 2.0
    entry["parts"] = (
        DamagePart("magic", amount=half, time_offset=0.0),
        DamagePart("magic", amount=half, time_offset=_W_SECOND_INSTANCE_DELAY),
    )
    entry["detail"] = (
        f"Pain of Wrath Total Magic Damage ({total:g}) split across the two "
        f"sourced instances: half immediately, half after "
        f"{_W_SECOND_INSTANCE_DELAY:g}s"
    )
    return entry


@ranked_slot
def _depth_charge(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: the primary-target eruption's Increased Damage."""
    increased = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
    # The primary target "is stunned for the same duration, and knocked up
    # for a modified duration": the cached "Stun Duration" and "Knock Up
    # Duration" rows are the same 1 / 1.5 / 2 seconds, so one un-narrowed
    # immobilize of that length states both without inventing a number.
    immobilize_duration = extract_value(ability, "Knock Up Duration", rank)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        increased,
        "magic",
        # The priced row is the single final eruption on the primary
        # target; the charge's chase has no sourced duration, so the hit is
        # certified at the cast boundary rather than given a made-up delay.
        event_order_certified="single_hit",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            amount=increased,
            cc_duration=immobilize_duration,
        ),
    )
    entry["detail"] = (
        "Primary-target final eruption (Increased Damage); the chase "
        "eruptions along the charge's path hit other enemies and are not "
        "priced in the single-target fight"
    )
    return entry


# Cached kit review.  Q's anchor "deals magic damage, reveals them ...,
# stuns them for 1 second, and drags them toward Nautilus": one cast, two
# immobilize kinds at once, which is what the un-narrowed "immobilize"
# states.  R is the same shape — the primary target "is stunned for the
# same duration, and knocked up for a modified duration".  E's waves "deal
# magic damage to enemies hit ... and slow them".  W only damages: Pain of
# Wrath "takes magic damage over time" and the shield is on Nautilus.  P is
# absent because Staggering Blow is an on-hit rider on the auto stream, not
# an ability event of its own — its root is real but rides no ability row.
MODULE_CC = {"Q": "immobilize", "W": "none", "E": "slow", "R": "immobilize"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nautilus",
    PACKET_SHA256,
    # Dredge Line's anchor hits the first enemy once, and the packet for
    # Riptide is the first wave's Magic Damage (55 : 195 + 50% AP) — one
    # hit each, at the cast boundary, which is the claim that carries
    # MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _staggering_blow,
        "W": _titans_wrath,
        "R": _depth_charge,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Staggering Blow) deals 14 : 128 (based on level) bonus physical "
    "damage on empowered basic attacks — the wiki's 'Per-Level Scaling' "
    "row (data/champions.json). The packet's old 0.75-1.5 'Bonus Damage' "
    "values are the root duration, a crowd-control state, not damage.",
    "W (Titan's Wrath) prices the Total Magic Damage of Pain of Wrath "
    "(30 : 70 by rank + 40% AP) across its two sourced instances: half "
    "immediately, half after 1.25 seconds (module constant; wiki prose).",
    "R (Depth Charge) prices the primary-target final eruption "
    "(Increased Damage 150 : 400 by rank + 80% AP); the chase eruptions "
    "in the charge's wake hit enemies around the path, not the single "
    "target, and are not priced.",
]
