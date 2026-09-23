"""Maokai: Sapling Toss brush empowerment burn.

E (Sapling Toss) throws a Sapling that explodes on the first nearby enemy.  A
Sapling thrown into brush is EMPOWERED: its explosion deals 66.7% damage to
non-minion targets AND attaches two Saplings that explode every 0.75 seconds
over 1.5 seconds.  The empowered total is the cache's "Total Magic Damage" row
and the burn is its "Total Attached Sapling Damage" row, two ticks of the
per-instance row.  ``sapling_empowered``, default on because brush saplings are
the standard usage, swaps the plain explosion for the empowered one plus burn.
P, Q, W and R keep their packet pricing, P being the periodic Sap Magic
empowered-auto state.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from ..cast_event_row import cast_time as _row_cast_time
from ..damage_event_row import event_time as _row_time
from ..healing_helpers import (
    ability_json,
    attributed_events,
    leveling_value,
    trigger_fields,
)
from .contract_vocabulary import REQUIRED_CHAMPION_SLOTS
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option, champion_stat
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named

PACKET_SHA256 = "13ed879eea3657a5f23e4b9905fb5df614fb6d4fe52fcababf018a51f6aed830"


# HARDCODED cadence: the attached-sapling burn ticks every 0.75 seconds
# over 1.5 seconds (2 ticks) — wiki description of the brush-empowered
# Sapling Toss, cross-checked against the cache's leveling rows
# (Total Attached Sapling Damage == 2 x Magic Damage per Instance).
_ATTACHED_TICKS = 2
_ATTACHED_TICK_INTERVAL = 0.75


@ranked_slot
def _sapling_toss(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: Sapling Toss — plain explosion or brush-empowered burst+burn."""
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
MODULE_CC = {"Q": "slow", "W": "root", "E": "slow", "R": "root", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Maokai",
    PACKET_SHA256,
    assumption_overrides=(
        "Sapling Toss defaults to the brush-empowered branch, its explosion 66.7% on "
        "a non-minion target.",
        "It attaches two Saplings burning every 0.75s over 1.5s (2 ticks), the "
        "sourced Total Attached Sapling row.",
        "The sapling's 30s sit, 2.5s chase, 45% slow, reveal and 300 non-champion cap "
        "are state, not modeled.",
        "P (Sap Magic) heals 4% to 12.8% of maximum health by level on the first "
        "basic attack after its cooldown.",
        "That cooldown is 30 to 20 seconds by level, affectedByCdr false, from the "
        "cached row.",
        "Each Q, W, E or R cast counts one trigger, and each E cast a sapling "
        "champion hit, cutting it 4s.",
        "Incoming enemy strikes are invisible here, so triggers undercount; the heal "
        "stops above 95% health.",
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
    slot_order=REQUIRED_CHAMPION_SLOTS,
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    bool_option(
        "sapling_empowered",
        True,
        label="Sapling thrown into brush (empowered burn)",
        rotation={"role": "irrelevant", "slot": "E"},
    ),
]


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Sap Magic's cooldown and empowered-attack heal."""
    passive = ability_json(ctx.champion_data, "P")
    level = max(1, int(champion_stat(ctx.champion_stats, "level")))
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

    duration = max(0.0, float(ctx.fight_duration_seconds or 0.0))
    auto_events = attributed_events(
        ctx.damage_events, lambda source, _event: source == "auto_attacks"
    )
    trigger_by_time: dict[float, int] = {}
    for cast in ctx.cast_timeline or []:
        slot = cast.get("slot")
        if slot not in {"Q", "W", "E", "R"}:
            continue
        try:
            cast_time = _row_cast_time(cast)
        except (TypeError, ValueError):
            continue
        trigger_by_time[cast_time] = trigger_by_time.get(cast_time, 0) + (
            2 if slot == "E" else 1
        )
    trigger_times = sorted(trigger_by_time)
    auto_by_time: dict[float, dict[str, Any]] = {}
    for event in auto_events:
        auto_by_time.setdefault(round(_row_time(event), 6), event)
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
        heal_time = _row_time(proc_auto) + 0.25
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
        proc_time = _row_time(proc_auto)
        while (
            trigger_index < len(trigger_times)
            and trigger_times[trigger_index] <= proc_time + 1e-9
        ):
            trigger_index += 1
        cycle_start = proc_time
        auto_index += 1
    return healing


SELF_HEALING_RULE = self_healing_rule("Maokai")(derive_self_healing)
