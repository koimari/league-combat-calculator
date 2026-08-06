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
from .reviewed_batch_05 import build_batch_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, on_hit_entry

# HARDCODED: verify on patch updates — Pain of Wrath's second instance
# lands 1.25 seconds after the first (wiki W effect prose; the JSON
# carries no timing).
_W_SECOND_INSTANCE_DELAY = 1.25

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nautilus")


def _staggering_blow(ctx: SlotCtx):
    """P: empowered basic attacks deal 14 : 128 (based on level) bonus
    physical damage — the "Per-Level Scaling" leveling row."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry(ability.get("name", "Staggering Blow"), per_hit, "physical")


_staggering_blow.phase = ONHIT


def _titans_wrath(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Pain of Wrath's Total Magic Damage across both instances."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Titan's Wrath"),
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


def _depth_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the primary-target eruption's Increased Damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    increased = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Depth Charge"),
        rank,
        extract_cooldown(ability, rank),
        increased,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", amount=increased),)
    entry["detail"] = (
        "Primary-target final eruption (Increased Damage); the chase "
        "eruptions along the charge's path hit other enemies and are not "
        "priced in the single-target fight"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["P"] = _staggering_blow
SLOTS["W"] = _titans_wrath
SLOTS["R"] = _depth_charge
parse_abilities = build_parser(SLOTS, "Nautilus")

ASSUMPTIONS = list(ASSUMPTIONS) + [
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
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
