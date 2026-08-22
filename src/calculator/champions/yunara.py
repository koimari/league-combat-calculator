"""Yunara — CP10.10 full-entry-reviewed packet module.

P1-2 fixes:
- W (Arc of Judgment) prices the initial impact AND the lingering-bead
  DoT: the bead lingers for 1 second, ticking 4 times at 0.25-second
  intervals (the sourced "Linger Magic Damage per Tick" row x 4 == the
  "Total Expanded Damage" row; per-tick is 15% of the initial impact).
- R (Transcend One's Self) is modeled as the buff it is, not as direct
  damage: the zero-damage R entry documents the Transcendent State, and
  the ``r_transcendent`` option (default False — the base form is the
  deterministic default, the Shyvana dragon-form convention) switches W
  to the empowered Arc of Ruin (base 160/320/480 by R rank + 120% bonus
  AD + 75% AP, the base from R's "Arc of Ruin Base Damage" leveling row
  and the ratios from the cached W[1] Arc of Ruin description prose).
"""

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    with_item_on_hits,
)

# HARDCODED: verify on patch updates — the linger cadence (4 ticks at
# 0.25s over the 1-second linger) is wiki W prose, reconciled by
# Total Expanded Damage / Linger Magic Damage per Tick == 4 at every
# rank.  Arc of Ruin's 120% bonus AD and 75% AP ratios live only in the
# cached W[1] description prose.
_W_LINGER_TICKS = 4
_W_LINGER_TICK_INTERVAL = 0.25
_R_ARC_OF_RUIN_BONUS_AD_RATIO = 1.20
_R_ARC_OF_RUIN_AP_RATIO = 0.75

PACKET_SHA256 = "5ad671471e6280db293bcad126fc07d1f6a41c6f5916861a4a3b59278ea133be"


def _arc_of_judgment(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: initial impact plus the 4 lingering-bead ticks (or Arc of Ruin)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    transcendent = bool(ctx.option("r_transcendent"))
    if transcendent:
        r_rank = ctx.rank_for("R")
        base = extract_named(
            ctx.ability("R", 0),
            "Arc of Ruin Base Damage",
            r_rank,
            ctx.stats,
            ctx.target,
        )
        bonus_ad = float(ctx.stat("bonus_attack_damage"))
        ap = float(ctx.stat("ability_power"))
        initial = (
            base
            + _R_ARC_OF_RUIN_BONUS_AD_RATIO * bonus_ad
            + _R_ARC_OF_RUIN_AP_RATIO * ap
        )
        name = "Arc of Ruin"
        linger_per_tick = 0.0  # Arc of Ruin is a beam; no linger beads
        linger_total = 0.0
        detail = (
            f"Transcendent State: Arc of Ruin base {base:g} (R rank {r_rank}) "
            f"+ 120% bonus AD + 75% AP"
        )
    else:
        initial = extract_named(
            ability, "Initial Magic Damage", rank, ctx.stats, ctx.target
        )
        linger_per_tick = extract_named(
            ability, "Linger Magic Damage per Tick", rank, ctx.stats, ctx.target
        )
        linger_total = extract_named(
            ability, "Total Expanded Damage", rank, ctx.stats, ctx.target
        )
        name = ability_name(ability)
        detail = (
            f"initial impact {initial:g} + {_W_LINGER_TICKS} linger ticks at "
            f"{_W_LINGER_TICK_INTERVAL:g}s intervals (total {linger_total:g})"
        )
    entry = damage_entry(
        name,
        rank,
        extract_cooldown(ability, rank),
        initial + linger_total,
        "magic",
    )
    parts: list[DamagePart] = [DamagePart("magic", initial, time_offset=0.0)]
    for index in range(1, _W_LINGER_TICKS + 1):
        parts.append(
            DamagePart(
                "magic",
                linger_per_tick,
                time_offset=index * _W_LINGER_TICK_INTERVAL,
            )
        )
    entry["parts"] = tuple(parts)
    entry["detail"] = detail
    return entry


def _transcend_one_self(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the Transcendent State buff shell (zero direct damage)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    entry["parts"] = ()
    entry["detail"] = (
        "Transcendent State (15s): a buff that empowers W into Arc of Ruin; "
        "with r_transcendent=True the W row prices the empowered base "
        "160/320/480 by R rank + 120% bonus AD + 75% AP"
    )
    return entry


# Arc of Judgment's initial hit "deals magic damage and slows them by 99%
# decaying over 1.5 seconds", and the Transcendent upgrade Arc of Ruin
# likewise "slows them by 99% decaying over 1 second" — one answer for both
# branches of ``r_transcendent``.  Cultivation of Spirit only adds bonus
# magic damage on-hit.  E is a dash, R is the Transcendent State buff shell
# and P is the crit bonus; none of the three authors a damage part.
MODULE_CC = {"Q": "none", "W": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Yunara",
    PACKET_SHA256,
    # Q's row is one empowered swing's bonus magic damage — no travel or
    # tick phase to place.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "W": _arc_of_judgment,
        "R": _transcend_one_self,
    },
    slot_wrappers={
        "Q": partial(
            with_item_on_hits, effectiveness=0.3, hits=1, triggers=("on_hit",)
        ),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Arc of Judgment) prices the initial impact plus 4 lingering-bead "
    "ticks at 0.25s intervals over the 1-second linger (Linger Magic "
    "Damage per Tick x 4 == Total Expanded Damage; per-tick is 15% of "
    "the initial impact).",
    "R (Transcend One's Self) is a buff, not direct damage: the zero-"
    "damage R entry documents the Transcendent State; r_transcendent "
    "(default False) switches W to the empowered Arc of Ruin (base "
    "160/320/480 by R rank + 120% bonus AD + 75% AP).",
]
OPTIONS.append(
    {
        "key": "r_transcendent",
        "type": "bool",
        "default": False,
        "label": "R Transcendent State (W becomes Arc of Ruin)",
    }
)
