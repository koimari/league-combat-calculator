"""Aery and Aftershock: one proc per accepted cast of a declared shape."""

from collections.abc import Mapping
from typing import Any

from ... import rune_effects
from ...state_lifecycle import TriggerGate
from ...trigger_stream import event_triggers, is_immobilizing_event
from ..autos.swing_schedule import _auto_attack_timestamps
from ..cast_slots import _damaging_cast_times
from ..ledger.breakdown import _is_auto_stream_key
from ..ledger.event_ledger import _ordered_damage_events
from ..ledger.event_rows import _CONTROL_TRIGGER_ONLY
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState
from .streams import _record_rune_proc_row


def _aery_trigger_times(state: FightState, rotation: RotationResult) -> list[float]:
    """Return one timestamp per accepted damaging Aery signal source.

    Ability casts and basic attacks use their certified streams.  Remaining
    timed damage rows are item effects.  Keystone and amplifier rows cannot
    signal Aery themselves, so they stay outside this trigger stream.
    """
    times = _damaging_cast_times(state, rotation)
    times.extend(_auto_attack_timestamps(state))
    for event in _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    ):
        if float(event["damage"]) <= 0.0:
            continue
        if event.get("is_ability") or event.get("basic_attack"):
            continue
        source_key = str(event["source_key"])
        if _is_auto_stream_key(source_key) or source_key.startswith(
            ("keystone_", "damage_amp_")
        ):
            continue
        times.append(float(event["time"]))
    return sorted(times)


def _add_keystone_aery_damage(state: FightState, rotation: RotationResult) -> None:
    """Add Summon Aery damage with its sourced flight and linger gate."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneAeryEffect):
        return
    proc_times: list[float] = []
    gate = TriggerGate(inclusive=False)
    for trigger_time in _aery_trigger_times(state, rotation):
        if not gate.accepts(trigger_time):
            continue
        impact = trigger_time + effect.damage_flight_seconds
        proc_times.append(impact)
        # The wiki gives a target linger but gives no fixed return travel
        # duration.  The sourced linger boundary is the deterministic lower
        # bound for the next signal and is disclosed in the fight notes: the
        # bolt flies, lands, and lingers there.
        gate.arm(impact, cooldown=effect.linger_seconds)
    if not proc_times:
        state.notes.append(
            f"{effect.rune_name} never procced: the simulated fight "
            "had no accepted damaging signal."
        )
        return
    _record_rune_proc_row(state, effect, proc_times)
    state.notes.append(
        f"{effect.rune_name} uses sourced {effect.damage_flight_seconds:g}-second "
        f"damage flight and {effect.linger_seconds:g}-second linger; return travel "
        "is movement-dependent, so the next signal uses the sourced linger boundary."
    )


def _aftershock_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Return one event per accepted immobilizing cast for Aftershock.

    Reviewed control events are preferred. Damage packets carry the same
    control metadata for modules whose hit part owns the immobilize, so those
    packets fill the gaps. A control event and its damage packet share one
    source/time identity and must not trigger twice.
    """
    triggers: list[dict[str, Any]] = []
    gate = TriggerGate(inclusive=False)

    def add(event: Mapping[str, Any]) -> None:
        # Classification is the bus's: comparing the token against a set here
        # is the divergence ``trigger_stream`` exists to prevent, and the
        # sourced trigger is an immobilize.  The Trigger then carries the
        # normalized token, so this walk never parses ``cc_kind`` itself.
        if not is_immobilizing_event(event):
            return
        duration = float(event.get("cc_duration", 0.0) or 0.0)
        if duration <= 0.0:
            return
        controls = event_triggers(event, kinds=_CONTROL_TRIGGER_ONLY)
        kind = controls[0].cc_kind if controls else ""
        if not kind:
            # An immobilize flag with no authored kind names no control
            # this row could republish.
            return
        try:
            time = float(event["time"])
        except (TypeError, ValueError):
            return
        # A control event and its damage packet share one identity.
        if not gate.accepts(time, (str(event["source_key"]), round(time, 9), kind)):
            return
        triggers.append(
            {
                "time": time,
                "source_key": str(event["source_key"]),
                "source": str(event.get("source", event["source_key"])),
                # The immobilize that CAUSED this shockwave, not one the
                # shockwave applies: a bare ``cc_kind`` on the damage packet
                # would certify the proc itself as a reviewed control event.
                "trigger_cc_kind": kind,
                "cc_duration": duration,
                "sequence": int(event["sequence"]),
            }
        )

    for event in rotation.control_events:
        if isinstance(event, Mapping):
            add(event)
    for event in _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    ):
        add(event)
    return sorted(triggers, key=lambda event: (event["time"], event["sequence"]))


def _add_keystone_aftershock_damage(
    state: FightState, rotation: RotationResult
) -> None:
    """Add Aftershock's delayed magic shockwave from immobilizing casts."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneAftershockEffect):
        return
    triggers = _aftershock_trigger_events(state, rotation)
    if not triggers:
        state.notes.append(
            f"{effect.rune_name} never procced: the simulated fight had no "
            "accepted immobilizing control event."
        )
        return
    raw_damage = effect.shockwave_raw_damage(state.level, state.champion_stats)
    mitigated_damage = _mitigate(raw_damage, "magic", state.resists, state.magic_amp)
    gate = TriggerGate(effect.cooldown_seconds, inclusive=True)
    proc_events: list[dict[str, Any]] = []
    for trigger in triggers:
        trigger_time = float(trigger["time"])
        if not gate.accepts(trigger_time):
            continue
        proc_events.append(
            {
                "time": trigger_time + effect.duration_seconds,
                "damage": mitigated_damage,
                "raw_damage": raw_damage,
                "damage_type": "magic",
                "trigger_time": trigger_time,
                "trigger_source": trigger["source"],
                "trigger_cc_kind": trigger["trigger_cc_kind"],
                "shockwave_radius": effect.shockwave_radius,
            }
        )
        gate.arm(trigger_time)
    if not proc_events:
        state.notes.append(
            f"{effect.rune_name} never procced: every immobilizing event "
            f"landed during its {effect.cooldown_seconds:g}-second cooldown."
        )
        return
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": mitigated_damage * len(proc_events),
        "damage_type": "magic",
        "count": len(proc_events),
        "event_phase": "effect",
        "damage_events": proc_events,
    }
    state.total_damage += mitigated_damage * len(proc_events)
    state.notes.append(
        f"{effect.rune_name} uses a sourced {effect.duration_seconds:g}-second "
        f"resistance window, {effect.cooldown_seconds:g}-second cooldown, and "
        f"{effect.shockwave_radius:g}-unit shockwave radius."
    )
