"""Xayah — reviewed packet slots plus the E3 Clean Cuts stack mechanic.

E3 additions over the CP10.9 packet module:
- P (Clean Cuts) becomes an explicit stack state: each ability cast
  generates 3 stacks (up to 5) and each basic attack consumes one stack
  to shoot a Feather. The feather deals the triggering attack's damage
  to the PRIMARY target — no single-target damage delta — and 35% /
  45% / 55% (based on level) AD to OTHER enemies (not modeled,
  single-target calc). What the stacks materially change is the planted
  feather count that detonates through E.
- E (Bladecaller) prices the detonation: per-feather damage
  ("Physical Damage Per Feather", flat + 40% bonus AD) times the
  recalled feather count. The count is a user option
  (``bladecaller_feathers``, default 7 = the expected contribution: 5
  Clean Cuts-empowered autos + 2 Q daggers; the sourced maximum of 12
  adds R's 5 feathers). The fight model cannot simulate how many
  empowered autos land before E, so the count is priced explicitly —
  the module convention for auto-rate stack systems.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "1aaff9137640dc9212a82420983ce8b4c7734417696e4529f59d8302d5fbc8e6"

# Featherstorm's feathers fly after the leap: "Xayah leaps into the air ...
# After 1 second, she shoots 5 Feathers" (cached R prose).
_R_LEAP_SECONDS = 1.0


# HARDCODED: verify on patch updates — Clean Cuts' stack bookkeeping
# (3 stacks per cast, 5 cap, 8-second window) and the 35/45/55% AD
# secondary-feather damage are wiki prose; the JSON carries no leveling
# for the passive.
_CLEAN_CUTS_MAX_STACKS = 5
_DEFAULT_FEATHERS = 7  # 5 empowered autos + 2 Q daggers (expected)
_MAX_FEATHERS = 12  # + 5 R feathers (sourced maximum)


def _clean_cuts(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: explicit Clean Cuts stack state (no single-target damage)."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = int(ctx.options.get("clean_cuts_stacks", _CLEAN_CUTS_MAX_STACKS))
    stacks = min(max(stacks, 0), _CLEAN_CUTS_MAX_STACKS)
    return {
        "name": ability.get("name", "Clean Cuts"),
        "rank": ctx.level,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"{stacks}/{_CLEAN_CUTS_MAX_STACKS} stack(s); each empowered "
            "auto plants one Feather (primary target takes the triggering "
            "attack's damage — no single-target delta); E detonates "
            "planted Feathers"
        ),
    }


def _bladecaller(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: per-Feather damage x recalled Feather count (stack detonation)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_feather = extract_named(
        ability, "Physical Damage Per Feather", rank, ctx.stats, ctx.target
    )
    feathers = int(ctx.options.get("bladecaller_feathers", _DEFAULT_FEATHERS))
    feathers = min(max(feathers, 0), _MAX_FEATHERS)

    entry = damage_entry(
        ability.get("name", "Bladecaller"),
        rank,
        extract_cooldown(ability, rank),
        per_feather * feathers,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", per_feather, count=feathers),)
    entry["detail"] = (
        f"{feathers} recalled Feather(s) x {per_feather:g} per-Feather damage"
    )
    return entry


# Double Daggers' feathers "each deal physical damage to enemies hit",
# Deadly Plumage's extra feather only damages, and Featherstorm's cone
# "deal[s] physical damage to enemies hit".  P is the stack bookkeeping
# row and authors no damage part.
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Bladecaller does control — "a target hit by at least three Feathers is
# rooted for 1.25 seconds" — and the root is a property of the recalled
# feather count, which is this module's option, not of the slot.  Authoring
# it per part (the Fiddlesticks branch pattern) is the right shape, but the
# row cannot carry it either way: the recall is one aggregated part of
# ``bladecaller_feathers`` hits with no sourced cadence between them, so no
# event ever reaches the ledger.
MODULE_CC = {"Q": "none", "W": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xayah",
    PACKET_SHA256,
    assumption_overrides=(
        "Double Daggers prices both daggers (Physical Damage Per Hit x 2 "
        "== Total Physical Damage).",
    ),
    # W's row is the one extra feather the frenzy fires per attack.
    single_hit_slots=frozenset({"W"}),
    # "After 1 second, she shoots 5 Feathers" — R's hit is not at the
    # cast, so it authors the sourced delay instead of certifying.
    packet_part_timings={"R": {"time_offset": _R_LEAP_SECONDS}},
    slot_parsers={
        "Q": repeat_damage_parser(
            attr="Physical Damage Per Hit",
            dmg_type="physical",
            count=2,
            time_offset=0.0,
            hit_interval=0.1,
        ),
        "P": _clean_cuts,
        "E": _bladecaller,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "clean_cuts_stacks",
        "type": "int",
        "default": _CLEAN_CUTS_MAX_STACKS,
        "min": 0,
        "max": _CLEAN_CUTS_MAX_STACKS,
        "label": "Clean Cuts stacks",
    },
    {
        "key": "bladecaller_feathers",
        "type": "int",
        "default": _DEFAULT_FEATHERS,
        "min": 0,
        "max": _MAX_FEATHERS,
        "label": "Feathers recalled by Bladecaller",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Clean Cuts stack count is user-set (default 5); the 8-second stack "
    "window and which casts generate stacks are not simulated",
    "Each empowered auto deals the triggering attack's damage to the "
    "primary target (no single-target delta); the 35/45/55% AD "
    "secondary-target damage is not modeled (single-target calc)",
    "Bladecaller prices per-Feather damage x the recalled Feather count "
    "(user-set, default 7 = 5 empowered autos + 2 Q daggers; maximum 12 "
    "adds R's 5 Feathers) — the fight model cannot simulate how many "
    "empowered autos land before the recall",
    "Bladecaller's crit-chance damage increase (0-50% + 0-15%) and the "
    "root are not modeled (no leveling values in the cache; utility)",
    "W's bonus attack speed is the packet read; its extra 25%-damage "
    "feather to the primary target is not double-counted with Clean Cuts",
]
