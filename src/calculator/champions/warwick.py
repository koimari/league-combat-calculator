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
from .packet_module import build_packet_module
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


PACKET_SHA256 = "2c91dcf27a641c6a177969744e204b672765d8fc7291214c069ecacc64511a19"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Warwick",
    PACKET_SHA256,
    assumption_overrides=(
        "Warwick Q's sourced 0.264-second bite delay is applied to the hit "
        "event without inventing a channel lockout.",
    ),
    single_hit_slots=frozenset({"Q"}),
    packet_part_timings={"Q": {"time_offset": 0.264}},
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["R"] = _infinite_duress
SLOTS["Q"] = with_item_on_hits(
    SLOTS["Q"], effectiveness=1.0, hits=1, triggers=("on_hit", "on_attack")
)
# Jaws of the Beast only bites ("dealing magic damage, healing himself...");
# the displacement immunity is Warwick's own.  Infinite Duress "knocks them
# down and channels for up to 1.5 seconds to suppress, reveal, and deal
# magic damage every 0.25 seconds" — the suppression is the control the
# damaged target is under for the whole priced channel.  W (Blood Hunt) and
# E (Primal Howl, where the fear and 90% slow live) are out_of_scope with no
# damage row, and P is an on-hit rider on basic attacks.
MODULE_CC = {"Q": "none", "R": "suppression"}

parse_abilities = build_parser(SLOTS, "Warwick", cc_kinds=MODULE_CC)

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

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Warwick")
