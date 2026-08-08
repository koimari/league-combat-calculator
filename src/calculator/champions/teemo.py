"""Teemo — CP10.8 full-entry-reviewed packet module.

E9-1 closes the last audit gap: E (Toxic Shot) now prices the on-hit
PLUS the full 4-second poison DoT.  The packet priced only the
"Magic Damage On-Hit" row; the cached JSON's "Magic Damage per Tick"
(6-30 + 2.5% bonus AD + 10% AP) and "Total Poison Damage"
(24-120 + 10% bonus AD + 40% AP) rows are now expressed as 4 ticks at
1-second intervals (this module's packet timing declaration).

E4 summon: R (Noxious Trap) is a summoned trap.  The E2-3 tick fix
already prices one shroom detonation as the full 4-second poison (4
ticks of "Magic Damage per Tick" == the wiki Total Magic Damage row at
every rank, one tick per second).  This module keeps that pricing and
adds the player-controlled trap state:

- ``r_shrooms`` (default 1) — how many shroom detonations the fight
  prices.  The wiki note is explicit that stepping on multiple shrooms
  only REFRESHES the poison duration (never stacks), so each detonation
  prices its own full 4-tick DoT; a cluster walked onto simultaneously
  would be one DoT, and ``r_shrooms`` models sequential detonations
  (pre-placed field, charges stocked every 35/30/25s by rank).
- The sourced slow (30/40/50% by rank for 4 seconds, from the cache's
  "Slow" leveling row) is crowd-control utility the fight model does
  not price; it is reported on the row detail.

Boundary: shroom/trap placement, arm time, trigger radius and the 6-HP
trap health bar are state the fight model does not price — the damage
is the detonation DoT above.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import extract_value

# Sourced cadence for one Noxious Trap detonation (cache + wiki):
# "the target takes magic damage every second over 4 seconds" — 4 ticks
# at 1s; per-tick x4 == the wiki Total Magic Damage row.
_R_TICKS = 4
_R_TICK_INTERVAL = 1.0
_R_DOT_SECONDS = 4.0


def _shroom_detonations(ctx: SlotCtx) -> int:
    """Clamped ``r_shrooms``: shrooms detonating during the fight.

    R stocks up to 3/4/5 charges by rank (the "Maximum Charges" row);
    the player controls how many pre-placed shrooms the enemy walks
    onto.  Sequential detonations each price a full poison DoT.
    """
    ability = ctx.ability()
    rank = ctx.rank_for()
    cap = 5
    if ability is not None and rank >= 1:
        cap = max(1, int(extract_value(ability, "Maximum Charges", rank) or 5))
    return min(max(int(ctx.options.get("r_shrooms", 1)), 1), cap)


def _noxious_trap(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: one full poison DoT per shroom detonation (E2-3 tick pricing)."""
    entry = _R_SLOT(ctx)
    if entry is None:
        return None
    shrooms = _shroom_detonations(ctx)
    if shrooms > 1:
        entry["parts"] = tuple(
            dataclasses.replace(part, count=part.count * shrooms)
            for part in entry["parts"]
        )
        entry["total_raw"] = entry.get("total_raw", 0.0) * shrooms
    slow = 0.0
    ability = ctx.ability()
    rank = ctx.rank_for()
    if ability is not None and rank >= 1:
        slow = extract_value(ability, "Slow", rank)
    inherited = entry.get("detail", "")
    entry["detail"] = (
        f"{shrooms} shroom detonation(s), each poisoning for "
        f"{_R_DOT_SECONDS:g}s ({_R_TICKS} ticks at {_R_TICK_INTERVAL:g}s "
        f"intervals) and slowing {slow:g}% for 4s."
        + (f" {inherited}" if inherited else "")
    )
    return entry


PACKET_SHA256 = "82f4b06f86d7d9d576a27f3e9e4e639261e0bb5f50c969cd0592a0ff8459a2f4"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Teemo",
    PACKET_SHA256,
    assumption_overrides=(
        "Noxious Trap prices the full 4-second poison: 4 ticks of Magic "
        "Damage per Tick (== Total Magic Damage) at 1-second intervals.",
    ),
    packet_tick_fixes={
        "Toxic Shot": {
            "initial_tick": 0.0,
            "extra_part": {
                "attribute": "Magic Damage per Tick",
                "count": 4,
                "damage_type": "magic",
                "first_tick": 1.0,
                "tick_interval": 1.0,
                "dot_duration": 4.0,
            },
        }
    },
    slot_parsers={
        "R": repeat_damage_parser(
            attr="Magic Damage per Tick",
            dmg_type="magic",
            count=4,
            time_offset=1.0,
            hit_interval=1.0,
            dot_duration=4.0,
        )
    },
)
PACKET_SPEC = SLOTS.packet_spec
_R_SLOT = SLOTS["R"]
SLOTS["R"] = _noxious_trap
parse_abilities = build_parser(SLOTS, "Teemo")
ASSUMPTIONS.extend(
    [
        "R (Noxious Trap) is a summoned trap: one detonation prices the "
        "full 4-second poison DoT (E2-3 ticks); r_shrooms prices "
        "sequential detonations, because multiple shrooms only refresh "
        "the poison duration and never stack.",
        "E (Toxic Shot) prices the on-hit PLUS the full 4-second poison: "
        "4 ticks of Magic Damage per Tick (== Total Poison Damage) at "
        "1-second intervals (this module's packet timing declaration); the "
        "poison refreshes rather than stacks (wiki note).",
        "The shroom slow (30/40/50% by R rank for 4 seconds) and reveal "
        "are crowd-control/vision utility the fight model does not price.",
        "Trap placement, arm time, trigger radius and the shroom's 6-HP "
        "trap health bar are state outside the damage model.",
    ]
)
OPTIONS.append(
    {
        "key": "r_shrooms",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 5,
        "label": "Shroom detonations (Noxious Trap)",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
