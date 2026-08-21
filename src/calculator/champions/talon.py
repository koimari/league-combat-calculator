"""Talon — CP10.8 packet module with the E9-1 gap fixes.

E9-1 closes the two remaining audit gaps over the CP10.8 packet:
- P (Blade's End) prices the 3-stack consume bleed.  Talon's abilities
  apply Wound stacks (max 3, 6s, refreshing); the next basic attack
  consumes them to bleed the target for the wiki's per-level total
  (80 : 303.53 based on level + 210% bonus AD), delivered as 16 ticks
  of the sourced per-tick array ("5 : 18.97 (based on level) (+
  13.125% bonus AD) physical damage every 0.125 seconds").  The bleed
  is priced once per fight from the ``passive_procs`` option (default
  1 = one 3-stack consume).
- Q's on-kill self-heal (9 : 60.41 based on level) is authored by the
  HEALING_RULE_CHAMPIONS rule in healing.py (the kill condition is a
  documented boundary there).

W two-hit and R are modeled; E (Assassin's Path) parkour is a
non-damaging repositioning dash.

Roadmap session 4 batch H (2026-08-21): E (Assassin's Path) has no
enemy-damage formula: the pinned reviewed packet (static/reviewed-
packets.json) independently declares E ``kind: "no_damage"`` with a
sourced reason (the parkour dash grants no damage, only terrain-crossing
movement), and E is not one of the slots this module reassigns away from
``build_packet_module``'s cast slots (only P/Q/W/R are overridden below),
so it already emits the packet's sourced zero-damage row today —
MODULE_COVERAGE was simply stale, still reading "out_of_scope" for an
already-covered slot (the Malzahar/Nasus precedent, roadmap session 4
batch D; the Ryze/Senna/Swain/Tahm Kench precedent, batch G).
Reclassified to "no_damage"; zero fight-computation change.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import find_named_leveling, sum_modifiers

# Sourced bleed cadence (wiki P): "5 : 18.97 (based on level)
# (+ 13.125% bonus AD) physical damage every 0.125 seconds" — 16 ticks
# of the per-tick array == the total array at every level (80/16 == 5,
# 303.53/16 == 18.97).  The total bleed's +210% bonus AD ratio is wiki
# prose (the JSON carries only the flat per-level arrays), pinned here
# with the source cited.
_P_BLEED_TICKS = 16
_P_BLEED_BONUS_AD_RATIO = 2.10
_P_BLEED_DURATION = 2.0  # 16 x 0.125s
_P_BLEED_TICK_INTERVAL = 0.125


def _certified_single_hit(parser):
    """Wrap a simple one-instance parser with the event-order certification."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is not None and int(entry.get("rank", 0) or 0) >= 1:
            entry["event_order_certified"] = "single_hit"
        return entry

    return parse


def _blades_end(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: one 3-stack consume bleed per fight (``passive_procs`` option)."""
    ability = ctx.ability()
    if ability is None:
        return None
    count = max(0, int(ctx.options.get("passive_procs", 1)))
    if count <= 0:
        return None

    total_leveling = find_named_leveling(ability, "Per-Level Scaling", 0)
    tick_leveling = find_named_leveling(ability, "Per-Level Scaling", 1)
    if total_leveling is None or tick_leveling is None:
        return None

    per_tick = sum_modifiers(tick_leveling, ctx.level, ctx.stats, ctx.target)
    per_tick += (
        _P_BLEED_BONUS_AD_RATIO
        / _P_BLEED_TICKS
        * ctx.stats.get("bonus_attack_damage", 0.0)
    )
    total = per_tick * _P_BLEED_TICKS
    return {
        "name": ability.get("name", "Blade's End"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": total * count,
        "parts": (DamagePart("physical", per_tick, count=_P_BLEED_TICKS),),
        "proc_count": count,
        "dot_duration": _P_BLEED_DURATION,
        "dot_tick_interval": _P_BLEED_TICK_INTERVAL,
        # One sourced event per 3-stack consume: the consuming basic
        # attack lands the full per-level bleed (16 ticks at the sourced
        # 0.125s cadence are priced as the per-proc total; the tick
        # cadence metadata above keeps item burns refreshing through the
        # tail).  damage.py re-prices each event at the proc's own
        # mitigated total, so the ledger sums exactly to the row.  The
        # event is declared at the fight-window end (the engine's
        # end-of-rotation fallback this replaces) so ordering-certifying
        # the row does not move its ledger position and cannot change
        # window-order item outcomes (e.g. Shadowflame's threshold).
        "event_phase": "effect",
        "damage_events": [
            {
                "time": float(ctx.options.get("fight_duration_seconds", 0.0) or 0.0),
                "damage_type": "physical",
                "damage": total,
                "event_precision": "phase_order",
            }
            for _ in range(count)
        ],
        "detail": (
            f"{count} 3-stack consume(s): per-tick x{_P_BLEED_TICKS} == "
            f"the wiki total bleed ({sum_modifiers(total_leveling, ctx.level):g} "
            f"+ 210% bonus AD at level {ctx.level}) over "
            f"{_P_BLEED_DURATION:g}s"
        ),
    }


PACKET_SHA256 = "7a3d30a61866ada61c6491cf4aecec11630184dd05c83eba0b177309e54647fb"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Talon", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec
SLOTS["P"] = _blades_end
SLOTS["Q"] = _certified_single_hit(SLOTS["Q"])
SLOTS["W"] = _certified_single_hit(SLOTS["W"])
SLOTS["R"] = _certified_single_hit(SLOTS["R"])
parse_abilities = build_parser(SLOTS, "Talon")

OPTIONS = list(OPTIONS) + [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 10,
        "label": "Blade's End 3-stack consumes",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Blade's End) prices one 3-stack consume per fight (the "
    "passive_procs option): abilities apply Wound stacks (max 3, 6s, "
    "refreshing); the next basic attack consumes them to bleed the "
    "target for the per-level total (80 : 303.53 based on level + 210% "
    "bonus AD — the ratio is wiki prose, module constant), as 16 ticks "
    "of the sourced per-tick array every 0.125 seconds.  The "
    "consuming basic attack's own swing is not a separate damage "
    "event.",
    "Q's on-kill self-heal (9 : 60.41 based on level) is authored by "
    "the HEALING_RULE_CHAMPIONS rule in healing.py; the fight model "
    "prices it once per Q cast because the outgoing ledger cannot "
    "identify the killing blow (boundary documented in healing.py).",
    "E (Assassin's Path) has no enemy-damage formula: the parkour dash "
    "is a terrain-crossing repositioning tool only (confirmed by the "
    "pinned reviewed packet's kind='no_damage' declaration for E). E is "
    "a cast slot in this module (never reassigned away from "
    "build_packet_module's no_damage branch), so MODULE_COVERAGE "
    "reflects a sourced no-damage classification rather than an "
    "unmodeled gap (no_damage, not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Talon self-healing events from its authored packet."""
    healing = []
    level = max(1, int(champion_stats.get("level", 18) or 18))
    heal = _healing._leveling_value(
        _healing._ability(champion_data, "Q"), "Heal", level
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "Q"
    ):
        _healing._heal_from_damage(healing, event, heal, "Noxian Diplomacy")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Talon", derive_self_healing)
