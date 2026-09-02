"""Maokai — Sapling Toss brush empowerment burn (E4 summon damage).

Why E is non-generic:
- E (Sapling Toss) throws a Sapling that explodes on the first nearby
  enemy (the reviewed CP10.4 packet prices this single "Magic Damage"
  explosion).  A Sapling thrown into brush is EMPOWERED: its explosion
  deals 66.7% damage to non-minion targets AND attaches two Saplings to
  the target that explode every 0.75 seconds over 1.5 seconds.  The
  empowered total is the cache's "Total Magic Damage" leveling row and
  the burn is its "Total Attached Sapling Damage" row (2 ticks of the
  "Magic Damage per Instance" row) — the E2 DoT tick-count convention.
  The ``sapling_empowered`` option (default on — brush saplings are the
  standard usage) swaps the plain explosion for the empowered
  explosion + burn.
- P/Q/W/R keep the reviewed CP10.4 packet pricing (P is the periodic
  Sap Magic empowered-auto state).
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from ..healing_helpers import (
    ability_json,
    attributed_events,
    leveling_value,
    trigger_fields,
)
from .engine import SlotCtx
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    with_control,
)

PACKET_SHA256 = "f3732d39aae761199c06bfc606515aee50fa1cc74ea65f28a15b0ef78d02f366"


# HARDCODED cadence: the attached-sapling burn ticks every 0.75 seconds
# over 1.5 seconds (2 ticks) — wiki description of the brush-empowered
# Sapling Toss, cross-checked against the cache's leveling rows
# (Total Attached Sapling Damage == 2 x Magic Damage per Instance).
_ATTACHED_TICKS = 2
_ATTACHED_TICK_INTERVAL = 0.75


def _sapling_toss(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Sapling Toss — plain explosion or brush-empowered burst+burn."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    cooldown = extract_cooldown(ability, rank)
    if not bool(ctx.option("sapling_empowered")):
        explosion = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        entry = damage_entry(
            ability_name(ability),
            rank,
            cooldown,
            explosion,
            "magic",
        )
        # One explosion, at the cast: the boundary claim that carries
        # MODULE_CC's reviewed slow for E into the event ledger on this
        # branch (the empowered branch's parts author their own timing).
        entry["event_order_certified"] = "single_hit"
        entry["detail"] = (
            "Un-empowered Sapling: single explosion of the sourced Magic Damage "
            "row; set sapling_empowered to price the brush-empowered burn."
        )
        return entry

    per_instance = extract_named(
        ability, "Magic Damage per Instance", rank, ctx.stats, ctx.target
    )
    # Empowered total == 3 x per-instance (explosion 1 instance at 66.7%
    # of the base + 2 burn ticks) == the cache's Total Magic Damage row.
    entry = damage_entry(
        ability_name(ability),
        rank,
        cooldown,
        per_instance * (1 + _ATTACHED_TICKS),
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_instance, time_offset=0.25),
        DamagePart(
            "magic",
            per_instance,
            count=_ATTACHED_TICKS,
            time_offset=0.5,
            hit_interval=_ATTACHED_TICK_INTERVAL,
        ),
    )
    entry["detail"] = (
        f"Brush-empowered Sapling: explosion at 66.7% (1 x {per_instance:.2f}) "
        f"plus {_ATTACHED_TICKS} attached-Sapling ticks of {per_instance:.2f} "
        "magic every 0.75s — the sourced Total Magic Damage row; the 45% slow "
        "and reveal are state"
    )
    return entry


# Cached kit review: Q's shockwave "slows them by 99% for 0.25 seconds"
# (the additional stun and knock-back land only on enemies "near
# Maokai", a position this pair fight does not model), W's arrival
# "roots them for a duration", E's sapling explosion slows "by 45% for 2
# seconds", and each R bramble "roots them for 0.75 : 2.25 (based on
# distance travelled) seconds".  P is a self-heal on-hit.
MODULE_CC = {"Q": "slow", "W": "root", "E": "slow", "R": "root"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Maokai",
    PACKET_SHA256,
    assumption_overrides=(
        "Sapling Toss defaults to the brush-empowered branch: the explosion deals 66.7% damage to "
        "non-minion targets and attaches two Saplings that burn every 0.75s over 1.5s (2 ticks) — "
        "the sourced Total Magic Damage / Total Attached Sapling Damage rows (E2 DoT tick-count "
        "convention)",
        "The sapling's 30-second sit duration, 2.5-second chase, 45% slow, reveal, and the 300 cap "
        "against non-champions are state, not modeled",
        "P (Sap Magic) is authored by this module's derive_self_healing rule: the periodic "
        "empowered-attack heal (4% : 12.8% of maximum health by level, the cached Max Health "
        "Damage row) fires on the first basic attack after the P cooldown (30 : 20 seconds by "
        "level, affectedByCdr false) completes; each Q/W/E/R cast counts one trigger and each E "
        "cast an additional sapling champion hit, each reducing the cooldown by 4 seconds.  "
        "Incoming enemy ability strikes are not visible to the 1v1 outgoing ledger, so the "
        "counted triggers undercount reality (the proc can only be delayed); the heal does not "
        "trigger above 95% maximum health (live gate)",
    ),
    # The shockwave, the dash's arrival hit and each bramble deal
    # their packet once, at the cast (none of the three carries a
    # sourced travel time) — the boundary claim that carries
    # MODULE_CC's reviewed kinds into the event ledger.
    single_hit_slots=frozenset({"Q", "W", "R"}),
    slot_parsers={
        "E": _sapling_toss,
    },
    # W's arrival "roots them for a duration": the sourced Root Duration row
    # carries MODULE_CC's reviewed kind and its control atom onto the packet.
    slot_wrappers={
        "W": partial(with_control, duration_attr="Root Duration"),
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    bool_option(
        "sapling_empowered", True, label="Sapling thrown into brush (empowered burn)"
    ),
]


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
# pylint: disable=too-many-branches,too-many-statements
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Sap Magic's cooldown and empowered-attack heal."""
    del ability_damages
    passive = ability_json(champion_data, "P")
    level = max(1, int(champion_stat(champion_stats, "level")))
    cooldown_values: list[float] = []
    for modifier in (passive.get("cooldown") or {}).get("modifiers", []):
        values = modifier.get("values", [])
        if values:
            cooldown_values = [float(value) for value in values]
            break
    percentage = leveling_value(passive, "Max Health Damage", level)
    if not cooldown_values or percentage <= 0.0:
        return []
    cooldown = cooldown_values[min(level - 1, len(cooldown_values) - 1)]
    if cooldown <= 0.0:
        return []

    def sap_magic_heal(current_health: float, maximum_health: float) -> float:
        if maximum_health <= 0.0:
            return 0.0
        if current_health > maximum_health * 0.95 + 1e-9:
            return 0.0
        return maximum_health * percentage / 100.0

    duration = max(0.0, float(fight_duration_seconds or 0.0))
    auto_events = attributed_events(
        damage_events, lambda source, _event: source == "auto_attacks"
    )
    trigger_by_time: dict[float, int] = {}
    for cast in cast_timeline or []:
        slot = cast.get("slot")
        if slot not in {"Q", "W", "E", "R"}:
            continue
        try:
            cast_time = float(cast.get("time", 0.0))
        except (TypeError, ValueError):
            continue
        trigger_by_time[cast_time] = trigger_by_time.get(cast_time, 0) + (
            2 if slot == "E" else 1
        )
    trigger_times = sorted(trigger_by_time)
    auto_by_time: dict[float, dict[str, Any]] = {}
    for event in auto_events:
        auto_by_time.setdefault(round(float(event.get("time", 0.0)), 6), event)
    auto_times = sorted(auto_by_time)
    trigger_index = 0
    auto_index = 0
    cycle_start = 0.0
    healing: list[dict[str, Any]] = []
    while trigger_index < len(trigger_times) or auto_index < len(auto_times):
        trigger_count = 0
        previous_trigger = cycle_start
        completed = None
        while trigger_index < len(trigger_times):
            trigger_time = trigger_times[trigger_index]
            trigger_count += trigger_by_time[trigger_time]
            candidate = cycle_start + cooldown - 4.0 * trigger_count
            if candidate <= trigger_time + 1e-9:
                earlier = (
                    cycle_start
                    + cooldown
                    - 4.0 * (trigger_count - trigger_by_time[trigger_time])
                )
                completed = (
                    max(previous_trigger, earlier)
                    if earlier <= trigger_time + 1e-9
                    else trigger_time
                )
                break
            previous_trigger = trigger_time
            trigger_index += 1
        if completed is None:
            completed = cycle_start + cooldown - 4.0 * trigger_count
        if completed > duration + 1e-9:
            break
        while (
            auto_index < len(auto_times) and auto_times[auto_index] < completed - 1e-9
        ):
            auto_index += 1
        if auto_index >= len(auto_times):
            break
        proc_auto = auto_by_time[auto_times[auto_index]]
        heal_time = float(proc_auto.get("time", 0.0)) + 0.25
        if heal_time > duration + 1e-9:
            break
        healing.append(
            {
                "time": heal_time,
                "amount": 0.0,
                "amount_formula": sap_magic_heal,
                "source": "Sap Magic",
                "kind": "champion_passive",
                "actor_wide": True,
                **trigger_fields(proc_auto),
            }
        )
        proc_time = float(proc_auto.get("time", 0.0))
        while (
            trigger_index < len(trigger_times)
            and trigger_times[trigger_index] <= proc_time + 1e-9
        ):
            trigger_index += 1
        cycle_start = proc_time
        auto_index += 1
    return healing


SELF_HEALING_RULE = self_healing_rule("Maokai")(derive_self_healing)
