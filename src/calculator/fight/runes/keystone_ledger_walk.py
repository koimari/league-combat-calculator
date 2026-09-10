"""Dark Harvest and Deathfire: keystones replayed over the ordered event ledger."""

import math
from collections.abc import Mapping
from typing import Any

from ... import rune_effects
from ...ability_atoms import ability_field, ability_payload
from ...state_lifecycle import TriggerGate
from ..ledger.event_ledger import _ordered_damage_events
from ..ledger.event_rows import _row_time
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState, _damage_inputs


def _dark_harvest_trigger_event(event: Mapping[str, Any]) -> bool:
    """Whether one ordered event is a certified non-proc hit.  Ability casts
    and basic attacks carry the runtime's direct-damage receipts; other rows
    stay outside this threshold scan until they carry a classification."""
    if event.get("pet_damage") or event.get("dark_harvest_eligible"):
        return True
    return str(event.get("phase", "")) in {"ability", "auto"}


def _add_keystone_dark_harvest(state: FightState, rotation: RotationResult) -> None:
    """Add Dark Harvest procs from the ordered live-health event walk."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneDarkHarvestEffect):
        return

    base_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    )
    if not base_events:
        state.notes.append(
            f"{effect.rune_name} never procced: the simulated fight "
            "had no timestamped damage events."
        )
        return

    damage_type = effect.damage_type(state.champion_stats)
    target_health = max(0.0, float(state.target_health))
    threshold = target_health * effect.health_threshold_ratio
    gate = TriggerGate(effect.cooldown_seconds, inclusive=True)
    souls = 0
    source_index = 0
    pending: list[dict[str, Any]] = []
    proc_events: list[dict[str, Any]] = []
    skipped_after_death = 0

    def queue_proc(trigger_time: float) -> None:
        raw_damage = effect.raw_damage(_damage_inputs(state), souls)
        mitigated_damage = _mitigate(
            raw_damage, damage_type, state.resists, state.magic_amp
        )
        pending.append(
            {
                "time": trigger_time + effect.proc_delay_seconds,
                "trigger_time": trigger_time,
                "souls": souls,
                "raw_damage": raw_damage,
                "damage": mitigated_damage,
            }
        )
        gate.arm(trigger_time)

    while source_index < len(base_events) or pending:
        next_source = (
            base_events[source_index] if source_index < len(base_events) else None
        )
        pending.sort(key=_row_time)
        next_proc = pending[0] if pending else None
        source_time = (
            float(next_source.get("time", 0.0)) if next_source is not None else math.inf
        )
        proc_time = float(next_proc["time"]) if next_proc is not None else math.inf

        if next_source is not None and source_time <= proc_time:
            source = base_events[source_index]
            source_index += 1
            if target_health <= 0.0:
                continue
            damage = max(0.0, float(source["damage"]))
            if (
                damage > 0.0
                and _dark_harvest_trigger_event(source)
                and target_health < threshold
                and gate.accepts(source_time)
            ):
                queue_proc(source_time)
            target_health = max(0.0, target_health - damage)
            continue

        proc = pending.pop(0)
        if target_health <= 0.0:
            skipped_after_death += 1
            continue
        proc_events.append(
            {
                "time": float(proc["time"]),
                "damage": float(proc["damage"]),
                "raw_damage": float(proc["raw_damage"]),
                "damage_type": damage_type,
                "trigger_time": float(proc["trigger_time"]),
                "souls": int(proc["souls"]),
            }
        )
        target_health = max(0.0, target_health - float(proc["damage"]))
        souls += 1

    if not proc_events:
        state.notes.append(
            f"{effect.rune_name} never procced: no timestamped direct hit "
            f"landed below {effect.health_threshold_ratio:.0%} target health."
        )
        return

    total_damage = sum(float(event["damage"]) for event in proc_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(proc_events),
        "event_phase": "effect",
        "damage_events": proc_events,
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.rune_name} uses a sourced {effect.health_threshold_ratio:.0%} "
        f"maximum-health threshold, {effect.proc_delay_seconds:g}-second reap "
        f"delay, and {effect.cooldown_seconds:g}-second cooldown from each hit. "
        f"The first proc starts at 0 Souls; {souls} Soul(s) were reaped."
    )
    if skipped_after_death:
        state.notes.append(
            f"{effect.rune_name}: {skipped_after_death} delayed proc(s) "
            "were withheld after the target died."
        )
    state.notes.append(
        f"{effect.rune_name}: the sourced {effect.takedown_reset_seconds:g}-second "
        "takedown reset needs a team takedown receipt and is not applied in this "
        "single-target damage pass."
    )


def _deathfire_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Group ability damage into typed Deathfire burn applications."""
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    )
    detailed = [
        event
        for event in ordered
        if isinstance(event, Mapping)
        and event.get("is_ability")
        and float(event["damage"]) > 0.0
    ]
    cast_times: dict[str, list[float]] = {}
    for cast in rotation.cast_events:
        slot = str(cast.get("slot", ""))
        if slot in state.cast_order:
            cast_times.setdefault(slot, []).append(float(cast.get("time", 0.0)))

    triggers: list[dict[str, Any]] = []
    for slot, times in cast_times.items():
        info = ability_payload(state.ability_damages, slot)
        category = str(ability_field(info, "deathfire_category"))
        if not category:
            continue
        slot_events = [event for event in detailed if event.get("source_key") == slot]
        for index, cast_time in enumerate(times):
            next_cast = times[index + 1] if index + 1 < len(times) else math.inf
            cast_events = [
                event
                for event in slot_events
                if cast_time - 1e-9 <= float(event["time"]) < next_cast - 1e-9
            ]
            if not cast_events:
                continue
            if category.startswith("persistent_"):
                # Persistent damage applies on each authored tick. Events at
                # one timestamp share one application, so repeated DamagePart
                # instances cannot create duplicate refreshes.
                by_time: dict[float, list[Mapping[str, Any]]] = {}
                for event in cast_events:
                    event_time = round(float(event["time"]), 9)
                    by_time.setdefault(event_time, []).append(event)
                for event_time, events in by_time.items():
                    triggers.append(
                        {
                            "time": event_time,
                            "sequence": min(int(event["sequence"]) for event in events),
                            "source_key": slot,
                            "source": slot,
                            "category": category,
                            "damage": sum(float(event["damage"]) for event in events),
                            "event_precision": min(
                                (
                                    str(event.get("event_precision", "cast_boundary"))
                                    for event in events
                                ),
                                key=lambda value: (value != "exact", value),
                            ),
                        }
                    )
                continue
            triggers.append(
                {
                    "time": min(float(event["time"]) for event in cast_events),
                    "sequence": min(int(event["sequence"]) for event in cast_events),
                    "source_key": slot,
                    "source": slot,
                    "category": category,
                    "damage": sum(float(event["damage"]) for event in cast_events),
                    "event_precision": min(
                        (
                            str(event.get("event_precision", "cast_boundary"))
                            for event in cast_events
                        ),
                        key=lambda value: (value != "exact", value),
                    ),
                }
            )
    return sorted(
        triggers,
        key=lambda event: (float(event["time"]), int(event["sequence"])),
    )


def _add_keystone_deathfire(state: FightState, rotation: RotationResult) -> None:
    """Add Deathfire Touch's refreshed, delayed magic burn."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneDeathfireEffect):
        return

    triggers = _deathfire_trigger_events(state, rotation)
    damage_events: list[dict[str, Any]] = []
    trigger_events: list[dict[str, Any]] = []
    active_start: float | None = None
    active_until = float("-inf")
    next_tick: float | None = None
    active_trigger: dict[str, Any] | None = None
    total_damage = 0.0
    amplified_ticks = 0

    def emit_until(limit: float) -> None:
        """Emit all authored ticks through one active burn boundary."""
        nonlocal next_tick, total_damage, amplified_ticks
        while next_tick is not None and next_tick <= limit + 1e-9:
            amplified = (
                active_start is not None
                and next_tick - active_start >= effect.amp_delay_seconds - 1e-9
            )
            raw_damage = effect.raw_tick(
                state.level,
                state.champion_stats,
                amplified=amplified,
            )
            mitigated = _mitigate(
                raw_damage,
                "magic",
                state.resists,
                state.magic_amp,
            )
            if mitigated > 0.0:
                source = active_trigger or {}
                damage_events.append(
                    {
                        "time": next_tick,
                        "damage": mitigated,
                        "raw_damage": raw_damage,
                        "damage_type": "magic",
                        "event_precision": "exact",
                        "trigger_time": float(source.get("time", next_tick)),
                        "trigger_source": source.get("source", "ability"),
                        "deathfire_category": source.get("category", "spell_damage"),
                        "amplified": amplified,
                    }
                )
                total_damage += mitigated
                amplified_ticks += int(amplified)
            next_tick += effect.tick_interval_seconds

    for trigger in triggers:
        trigger_time = float(trigger["time"])
        duration = effect.duration_for(str(trigger["category"]))
        if active_start is None or trigger_time > active_until + 1e-9:
            if active_start is not None:
                emit_until(active_until)
            active_start = trigger_time
            active_until = trigger_time + duration
            next_tick = trigger_time + effect.tick_interval_seconds
            active_trigger = trigger
            new_chain = True
        else:
            emit_until(trigger_time)
            active_until = trigger_time + duration
            active_trigger = trigger
            new_chain = False
        trigger_events.append(
            {
                **trigger,
                "duration_seconds": duration,
                "new_chain": new_chain,
                "event_precision": trigger.get("event_precision", "cast_boundary"),
            }
        )
    if active_start is not None:
        emit_until(active_until)

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": "magic",
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "trigger_events": trigger_events,
        "duration_by_category": dict(effect.duration_by_category),
        "tick_interval_seconds": effect.tick_interval_seconds,
        "amp_delay_seconds": effect.amp_delay_seconds,
        "amp_ratio": effect.amp_ratio,
        "amplified_tick_count": amplified_ticks,
        "pet_damage_category_modeled": False,
    }
    state.total_damage += total_damage
    if not triggers:
        state.notes.append(
            f"{effect.rune_name} recorded no classified ability-damage "
            "application; pet damage remains unavailable without a typed pet "
            "packet."
        )
    else:
        state.notes.append(
            f"{effect.rune_name} recorded {len(triggers)} typed burn "
            f"application(s), {len(damage_events)} tick(s), and "
            f"{amplified_ticks} amplified tick(s). Pet damage remains "
            "unavailable without a typed pet packet."
        )
