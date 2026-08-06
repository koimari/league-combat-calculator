"""Malzahar — CP10.4 full-entry-reviewed packet module.

E (Malefic Visions) and R (Nether Grasp) override the batch packet with
full-total DoT pricing: the packets carried the PER-TICK rows, so the
fight priced one tick of each multi-tick ability.  Both totals are
sourced:

- E: "Total Magic Damage" 80/115/150/185/220 is exactly 16x the "Magic
  Damage Per Tick" row (5/7.1875/9.375/11.5625/13.75); the wiki text
  ("dealing magic damage every 0.25 seconds over 4 seconds") confirms
  the 16-tick cadence.
- R: "Total Magic Damage" 125/200/275 is exactly 10x the "Magic Damage
  Per Tick" row (12.5/20/27.5); the wiki text ("channels for up to 2.5
  seconds ... every 0.25 seconds") confirms the 10-tick cadence.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import rank
from .reviewed_batch_04 import build_batch_module
from .slotlib import damage_entry, extract_cooldown, extract_named

# E: 16 ticks over 4s (every 0.25s); R: 10 ticks over 2.5s (every 0.25s).
_E_TICKS = 16
_E_DURATION = 4.0
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.25 seconds"
_R_TICKS = 10
_R_DURATION = 2.5
_R_TICK_INTERVAL = _R_DURATION / _R_TICKS  # "every 0.25 seconds"


def _malefic_visions(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the full 4-second Total Magic Damage across 16 sourced ticks."""
    ability = ctx.ability()
    if ability is None:
        return None
    selected_rank = rank(ctx)
    if selected_rank < 1:
        return None
    total = extract_named(
        ability, "Total Magic Damage", selected_rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Malefic Visions"),
        selected_rank,
        extract_cooldown(ability, selected_rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _E_TICKS,
            count=_E_TICKS,
            time_offset=_E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole 4-second infection (the Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION
    return entry


def _nether_grasp(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the full 2.5-second Total Magic Damage across 10 sourced ticks.

    Only the flat "Total Magic Damage" row (effect 0) is read; the
    Null Zone's separate max-health row stays out of scope, as in the
    reviewed packet.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    selected_rank = rank(ctx)
    if selected_rank < 1:
        return None
    total = extract_named(
        ability, "Total Magic Damage", selected_rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Nether Grasp"),
        selected_rank,
        extract_cooldown(ability, selected_rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            total / _R_TICKS,
            count=_R_TICKS,
            time_offset=_R_TICK_INTERVAL,
            hit_interval=_R_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _R_DURATION
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Malzahar")
# Override the packet DoT rows with the full-total tick pricing above,
# and rebuild the parser so the module's parse_abilities sees them.
SLOTS = {**SLOTS, "E": _malefic_visions, "R": _nether_grasp}
parse_abilities = build_parser(SLOTS, "Malzahar")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
