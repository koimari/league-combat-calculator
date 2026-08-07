"""Warwick — CP10.9 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (Infinite Duress) was declared
no_damage although the wiki cache carries "Total Magic Damage"
175/350/525 + 167% bonus AD over the 1.5-second suppress channel (the
wiki notes the channel deals magic damage every 0.25 seconds and that
on-hit/on-attack effects apply 3 times over its duration).  This
module prices the total as the R cast, which also lets healing.py's
existing 100%-of-R-damage self-heal rule fire (it previously could
never trigger because the module emitted no R damage events).

Q damage + Q heal modeled (verified); W (Blood Hunt), E (Primal Howl)
and P (Eternal Hunger) remain documented out_of_scope.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_09 import build_batch_module
from .slotlib import with_item_on_hits, damage_entry, extract_cooldown, extract_named

# Sourced channel (wiki R): "deal magic damage every 0.25 seconds" over
# the up-to-1.5s suppress; "applies on-hit effects and triggers
# on-attack effects 3 times over its duration".
_R_CHANNEL_SECONDS = 1.5


def _infinite_duress(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Total Magic Damage over the 1.5s suppress channel."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Infinite Duress"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["dot_duration"] = _R_CHANNEL_SECONDS
    entry["detail"] = (
        "Total Magic Damage 175/350/525 + 167% bonus AD over the "
        f"{_R_CHANNEL_SECONDS:g}s suppress channel (magic damage every "
        "0.25s; the wiki's 3 on-hit applications are item on-hit/on-"
        "attack riders, not extra ability damage, and are not "
        "multiplied — the cache publishes no per-tick row)"
    )
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Warwick")
SLOTS["R"] = _infinite_duress
SLOTS["Q"] = with_item_on_hits(SLOTS["Q"], effectiveness=1.0, hits=1, triggers=('on_hit', 'on_attack'))
parse_abilities = build_parser(SLOTS, "Warwick")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Infinite Duress) prices the wiki Total Magic Damage "
    "(175/350/525 + 167% bonus AD by rank) as one cast over the "
    "1.5-second suppress channel; healing.py's existing 100%-of-R-"
    "damage self-heal rule fires on the R damage event.  The channel's "
    "0.25s magic-damage ticks and its 3 on-hit/on-attack applications "
    "are documented cadence: item on-hits are not multiplied (the "
    "cache publishes no per-tick row).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
