"""When a cooldown proc is allowed to fire."""

from typing import Any

from ... import item_effects
from ..autos.swing_schedule import _auto_attack_timestamps
from ..ledger.event_ledger import _ordered_damage_events
from ..results import RotationResult
from ..state import FightState


def _unique_ledger_hits(
    state: FightState,
    rotation: RotationResult,
    source_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Distinct positive damage instances from the ordered ledger, in order.

    ``source_keys`` narrows the walk to specific rows (ability casts for
    ability-triggered procs); ``None`` keeps every damage source.
    """
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
    )
    unique_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int, float]] = set()
    for event in ordered:
        if event["damage"] <= 0:
            continue
        if source_keys is not None and event["source_key"] not in source_keys:
            continue
        identity = (
            event["source_key"],
            int(event["ordinal"]),
            float(event["time"]),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_hits.append(event)
    return unique_hits


def _ability_damage_proc_triggers(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> list[dict[str, Any]]:
    """Schedule an ability-triggered proc onto legal damaging casts."""
    unique_hits = _unique_ledger_hits(state, rotation, set(state.cast_order))

    proc_triggers: list[dict[str, Any]] = []
    ready_at = float("-inf")
    for event in unique_hits:
        event_time = float(event["time"])
        if event_time + 1e-9 < ready_at:
            continue
        proc_triggers.append(event)
        if not effect.repeat_on_cooldown:
            break
        ready_at = event_time + effect.cooldown
    return proc_triggers


def _champion_damage_proc_triggers(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> list[dict[str, Any]]:
    """Schedule a damaging-a-champion proc onto the ordered ledger.

    Any positive damage event arms the proc (Hextech Alternator's Revved
    triggers on abilities, attacks, and item effects alike). Repeat procs
    wait out the cooldown; each completed attack windup between procs
    refunds ``on_attack_cooldown_refund`` seconds of it (Scout's
    Slingshot's Bullseye).
    """
    unique_hits = _unique_ledger_hits(state, rotation)
    swing_times = sorted(_auto_attack_timestamps(state))
    refund = effect.on_attack_cooldown_refund

    def cooldown_ready(last_proc_time: float, event_time: float) -> bool:
        elapsed = event_time - last_proc_time
        if refund > 0:
            attacks_between = sum(
                1 for swing in swing_times if last_proc_time < swing <= event_time
            )
            elapsed += refund * attacks_between
        return elapsed + 1e-9 >= effect.cooldown

    proc_triggers: list[dict[str, Any]] = []
    last_proc_time: float | None = None
    for event in unique_hits:
        event_time = float(event["time"])
        if last_proc_time is not None and not cooldown_ready(
            last_proc_time, event_time
        ):
            continue
        proc_triggers.append(event)
        if not effect.repeat_on_cooldown:
            break
        last_proc_time = event_time
    return proc_triggers


def _damage_threshold_trigger_time(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> float | None:
    """Time the rolling damage window first crosses the item's threshold.

    Walks the certified ledger built so far (abilities at cast times,
    autos at swing times, earlier authored item events) and returns the
    moment a ``damage_threshold`` trigger (Stormsurge's Squall) first
    held ``damage_threshold_ratio`` of the target's max health within
    ``damage_threshold_window`` seconds. Returns ``None`` when the model
    never crosses the threshold — the row then stays coarse (the engine
    still prices the proc, but cannot certify when it fires).
    """
    ratio = effect.damage_threshold_ratio
    window = effect.damage_threshold_window
    if ratio <= 0 or window <= 0:
        return None
    threshold = ratio * state.target_health
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
        light=True,
    )
    window_sum = 0.0
    window_start = 0
    for row in events:
        event_time = row[0][0]
        window_sum += row[1]
        while events[window_start][0][0] < event_time - window - 1e-9:
            window_sum -= events[window_start][1]
            window_start += 1
        if window_sum + 1e-6 >= threshold:
            return event_time
    return None
