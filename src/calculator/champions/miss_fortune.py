"""Miss Fortune — CP10.4 packet module with the E9-1 R gap fix.

E9-1 closes the remaining audit gap: R (Bullet Time) priced ONE wave of
the channel.  The wiki cache carries the explicit "Total Waves"
14/16/18 row and the "Wave Interval Time" cadence
(0.2036/0.1781/0.1583s by rank), so this module prices per-wave damage
x the sourced wave count at the sourced cadence — the full channel.
The wiki's "Maximum Total Physical Damage" row equals per-wave x waves
at ranks 1 and 3; the rank-2 display (500) is a rounding artifact of
16 x 30 == 480.

E2 already fixed E (Make It Rain) to its 8 sourced ticks; Q double-up
is modeled; P (Love Tap) and W (Strut) remain documented out_of_scope.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value


def _bullet_time(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: per-wave damage x sourced Total Waves (14/16/18 by rank)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_wave = extract_named(
        ability, "Physical Damage per Wave", rank, ctx.stats, ctx.target
    )
    waves = max(1, int(extract_value(ability, "Total Waves", rank)))
    interval = extract_value(ability, "Wave Interval Time", rank)
    total = per_wave * waves
    entry = damage_entry(
        ability.get("name", "Bullet Time"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            per_wave,
            count=waves,
            time_offset=0.0,
            hit_interval=interval,
        ),
    )
    entry["dot_duration"] = waves * interval
    entry["detail"] = (
        f"{waves} sourced waves of {per_wave:.6g} physical damage "
        f"(per-wave x{waves} == the wiki Maximum Total Physical Damage "
        "row at ranks 1 and 3; the rank-2 display 500 vs 480 is a wiki "
        "rounding artifact)"
    )
    return entry


PACKET_SHA256 = "3c5d28681b774a275e1c2b8bfd6150c08bad192051ac56c0a49c6a96462ad2f7"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Miss Fortune",
    PACKET_SHA256,
    packet_tick_fixes={
        "Make It Rain": {
            "count": 8,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 2.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["R"] = _bullet_time
parse_abilities = build_parser(SLOTS, "Miss Fortune")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Bullet Time) prices the full channel: per-wave damage x the "
    "sourced Total Waves row (14/16/18 by rank) at the sourced Wave "
    "Interval Time cadence.  The wiki's Maximum Total Physical Damage "
    "row matches per-wave x waves at every rank except its rank-2 "
    "display (500 vs 480) — a rounding artifact.",
    "Each wave is a 6-projectile spread that can critically strike for "
    "130% + 9% per 10% critical strike chance (wiki R effect[1]); the "
    "fight model prices the whole wave as one event without rolling "
    "per-projectile crits.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
