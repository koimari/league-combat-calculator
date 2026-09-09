"""Eclipse's two-stacks-in-a-window schedule and its withheld candidates."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ... import item_effects
from ...trigger_stream import applies_control
from ..autos.swing_schedule import _auto_attack_timestamps
from ..empower_declaration import _empower_hits
from ..ledger.event_rows import _finite_numeric_receipt, _item_proc_precision
from ..results import RotationResult
from ..rotation.shaped_charge import _next_authored_event
from ..state import FightState


@dataclass(frozen=True, slots=True)
class _EclipseStackTrigger:
    """One validated Eclipse stack candidate."""

    time: float
    phase: int
    sequence: int
    precision: str
    target_id: str
    application_id: str


def _stacked_champion_proc_times(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.CooldownProcEffect,
) -> (
    tuple[
        list[dict[str, Any]],
        item_effects.WindowStackGate,
        list[dict[str, Any]],
    ]
    | None
):
    """Schedule a stack-gated champion proc from authored hit boundaries.

    Eclipse's passive counts separate damaging ability casts and basic
    attacks, not every part of a multi-hit spell — *"up to one per cast
    instance per champion"*, paired *"within a 2 second period"* on the
    item's 6 s cooldown (Ever Rising Moon, ``data/items.json``).  Cast
    events and the shared auto schedule are the only timestamps this engine
    certifies, so each accepted cast contributes one stack at its authored
    hit time when available, otherwise at its explicit cast boundary; each
    authored swing contributes one stack at its swing time.  A pair must
    land inside ``stack_window`` and later pairs wait for the item's
    per-target cooldown.  A malformed receipt withholds event precision.

    Positive direct-damage casts, typed control-only casts, forced attacks
    and ambient attacks share one application-identity dedupe, so damage and
    control from the same ordinary cast feed the gate once.  The reviewed
    source also names DoT applications, but the generic ability packet does
    not identify that application boundary separately from its ticks: those
    candidates stay withheld with a named receipt rather than becoming
    guessed stack events, and a champion-specific exception that splits one
    player cast into several Eclipse cast instances stays outside this
    generic collector too.

    The returned length is the proc count: this schedule prices the row,
    and it is sparser than the caller's ``1 + duration / cooldown``
    fallback wherever the trigger stream does not offer a second stack
    inside the window each time the cooldown expires.
    """
    required = effect.stack_required
    window = effect.stack_window
    if required <= 1 or window <= 0.0:
        return None
    triggers: list[_EclipseStackTrigger] = []
    denials: list[dict[str, Any]] = []
    accepted_applications: set[tuple[str, str]] = set()
    event_cursors: dict[str, int] = {}
    forced_attack_events: list[tuple[float, str, str, str]] = []
    forced_event_slots: set[str] = set()

    def deny(
        reason: str,
        *,
        source_key: str,
        time: float,
        cast_id: object = None,
        target_id: object = None,
    ) -> None:
        source = item_effects.eclipse_trigger_source_receipt()
        receipt: dict[str, Any] = {
            "source": "Eclipse (Ever Rising Moon)",
            "reason": reason,
            "source_key": source_key,
            "time": time,
            "source_url": source.url,
            "source_revision_id": source.revision_id,
        }
        if isinstance(cast_id, str) and cast_id:
            receipt["cast_id"] = cast_id
        if isinstance(target_id, str) and target_id:
            receipt["target_id"] = target_id
        denials.append(receipt)

    def add_trigger(trigger: _EclipseStackTrigger) -> None:
        identity = (trigger.target_id, trigger.application_id)
        if identity in accepted_applications:
            return
        accepted_applications.add(identity)
        denials[:] = [
            denial
            for denial in denials
            if not (
                denial.get("cast_id") == trigger.application_id
                and denial.get("target_id") == trigger.target_id
            )
        ]
        triggers.append(trigger)

    for sequence, cast_event in enumerate(rotation.cast_events):
        if not isinstance(cast_event, Mapping):
            return None
        slot = cast_event.get("slot")
        event_time = _finite_numeric_receipt(cast_event.get("time"))
        if not isinstance(slot, str) or event_time is None or event_time < 0.0:
            return None
        cast_id = cast_event.get("cast_id")
        target_id = cast_event.get("target_id")
        if not isinstance(cast_id, str) or not cast_id.strip():
            deny(
                "application_identity_unavailable",
                source_key=slot,
                time=event_time,
                target_id=target_id,
            )
            continue
        if not isinstance(target_id, str) or not target_id.strip():
            deny(
                "target_identity_unavailable",
                source_key=slot,
                time=event_time,
                cast_id=cast_id,
            )
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, Mapping):
            continue
        raw_damage = row.get("total_damage", 0.0)
        if isinstance(raw_damage, bool) or not isinstance(raw_damage, (int, float)):
            return None
        if math.isfinite(float(raw_damage)) and float(raw_damage) > 0.0:
            ability_info = state.ability_damages.get(slot)
            if isinstance(ability_info, Mapping) and (
                ability_info.get("dot_duration") is not None
                or ability_info.get("dot_tick_interval") is not None
            ):
                deny(
                    "dot_application_timing_unavailable",
                    source_key=slot,
                    time=event_time,
                    cast_id=cast_id,
                    target_id=target_id,
                )
                continue
            trigger_time = event_time
            precision = _item_proc_precision(state, slot)
            authored_events = row.get("damage_events")
            if isinstance(authored_events, list):
                if row.get("basic_attack") and slot not in forced_event_slots:
                    forced_event_slots.add(slot)
                    for candidate in authored_events:
                        if not isinstance(candidate, Mapping):
                            return None
                        if not candidate.get("basic_attack"):
                            continue
                        candidate_time = _finite_numeric_receipt(candidate.get("time"))
                        candidate_damage = _finite_numeric_receipt(
                            candidate.get("damage")
                        )
                        if candidate_time is None or candidate_damage is None:
                            return None
                        if candidate_damage > 0.0:
                            forced_attack_events.append(
                                (
                                    candidate_time,
                                    str(candidate.get("event_precision", "exact")),
                                    target_id,
                                    f"{cast_id}:forced:{len(forced_attack_events) + 1}",
                                )
                            )
                found = _next_authored_event(
                    authored_events, event_cursors.get(slot, 0), event_time
                )
                if found is None:
                    return None
                cursor, authored_time, authored_precision = found
                if authored_time is None:
                    return None
                event_cursors[slot] = cursor
                trigger_time, precision = authored_time, authored_precision
            # Ability phase precedes autos at the same timestamp.
            add_trigger(
                _EclipseStackTrigger(
                    time=trigger_time,
                    phase=0,
                    sequence=sequence,
                    precision=precision,
                    target_id=target_id,
                    application_id=cast_id,
                )
            )

    for control_sequence, control_event in enumerate(rotation.control_events):
        if not isinstance(control_event, Mapping):
            return None
        source_key = control_event.get("source_key")
        event_time = _finite_numeric_receipt(control_event.get("time"))
        cast_id = control_event.get("application_id") or control_event.get("cast_id")
        target_id = control_event.get("target_id")
        if not isinstance(source_key, str) or event_time is None or event_time < 0.0:
            return None
        if not isinstance(cast_id, str) or not cast_id.strip():
            deny(
                "application_identity_unavailable",
                source_key=source_key,
                time=event_time,
                target_id=target_id,
            )
            continue
        if not isinstance(target_id, str) or not target_id.strip():
            deny(
                "target_identity_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
            )
            continue
        if (target_id, cast_id) in accepted_applications:
            continue
        ability_info = state.ability_damages.get(source_key)
        # Whether the row really applies control is the bus's answer, not a
        # comparison against the token: ``"none"`` is the reviewed-no-control
        # marker and a non-empty string, so reading the token here accepted
        # exactly the rows that certify NO control.
        if (
            not isinstance(ability_info, Mapping)
            or ability_info.get("cc_reviewed") is not True
            or control_event.get("cc_reviewed") is not True
            or not applies_control(control_event)
        ):
            deny(
                "cc_review_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
                target_id=target_id,
            )
            continue
        precision = control_event.get("event_precision")
        if not isinstance(precision, str) or not precision.strip():
            deny(
                "cc_application_timing_unavailable",
                source_key=source_key,
                time=event_time,
                cast_id=cast_id,
                target_id=target_id,
            )
            continue
        add_trigger(
            _EclipseStackTrigger(
                time=event_time,
                phase=0,
                sequence=len(rotation.cast_events) + control_sequence,
                precision=precision,
                target_id=target_id,
                application_id=cast_id,
            )
        )

    # A forced attack without a positive authored packet normally has no
    # certified landing boundary; retain the explicit coarse fallback
    # rather than counting an invented cast-time stack.  Exception: a
    # CERTIFIED forced-attack cast (single_hit / auto_stack_proc) has no
    # sub-cast offsets — its explicit cast boundary IS the swing, so it
    # contributes one trigger at the certified precision (E9-BIS).
    if (
        len(forced_attack_events) != rotation.forced_basic_attacks
        and rotation.forced_basic_attacks > 0
    ):
        missing = rotation.forced_basic_attacks - len(forced_attack_events)
        for _sequence, cast_event in enumerate(rotation.cast_events):
            if missing <= 0:
                break
            if not isinstance(cast_event, Mapping):
                return None
            slot = cast_event.get("slot")
            if not isinstance(slot, str):
                return None
            row = state.breakdown.get(slot)
            if not isinstance(row, Mapping) or float(row.get("total_damage", 0.0)) <= 0:
                continue
            # A forced-attack row whose own ``basic_attack`` flag IS the
            # swing receipt (Jayce Hyper Charge, Blitzcrank Power Fist)
            # certifies its cast boundary as the hit.  Regular certified
            # ability casts already contributed one stack in the main
            # loop; only basic_attack rows satisfy the forced-swing count.
            # An empowered-auto cast rides ``hits`` swings (Hyper Charge
            # forces 3), each a distinct Eclipse stack at the cast time.
            if row.get("basic_attack") is not True:
                continue
            ability_info = state.ability_damages.get(slot)
            empower = (
                ability_info.get("empowers_next_auto")
                if isinstance(ability_info, Mapping)
                else None
            )
            hits = _empower_hits(empower) if empower is not None else 1
            cast_time = _finite_numeric_receipt(cast_event.get("time")) or 0.0
            cast_id = cast_event.get("cast_id")
            target_id = cast_event.get("target_id")
            if (
                not isinstance(cast_id, str)
                or not cast_id.strip()
                or not isinstance(target_id, str)
                or not target_id.strip()
            ):
                return None
            forced_attack_events.extend(
                (
                    cast_time,
                    "exact",
                    target_id,
                    f"{cast_id}:forced:{hit_index + 1}",
                )
                for hit_index in range(hits)
            )
            missing -= hits
        if missing > 0:
            return None
    for index, (time, precision, target_id, application_id) in enumerate(
        forced_attack_events
    ):
        add_trigger(
            _EclipseStackTrigger(
                time=time,
                phase=1,
                sequence=len(triggers) + index,
                precision=precision,
                target_id=target_id,
                application_id=application_id,
            )
        )

    swing_times = _auto_attack_timestamps(state) if state.num_auto_attacks > 0 else []
    if state.num_auto_attacks > 0 and len(swing_times) != state.num_auto_attacks:
        return None
    auto_row = state.breakdown.get("auto_attacks")
    auto_damage = (
        auto_row.get("total_damage", 0.0) if isinstance(auto_row, Mapping) else 0.0
    )
    if state.num_auto_attacks > 0:
        if isinstance(auto_damage, bool) or not isinstance(auto_damage, (int, float)):
            return None
        if math.isfinite(float(auto_damage)) and float(auto_damage) > 0.0:
            offset = len(triggers)
            target_id = f"target:{state.roster_target_index}"
            for index, time in enumerate(swing_times):
                add_trigger(
                    _EclipseStackTrigger(
                        time=time,
                        phase=1,
                        sequence=offset + index,
                        precision="exact",
                        target_id=target_id,
                        application_id=f"auto:{index + 1}",
                    )
                )

    triggers.sort(key=lambda row: (row.time, row.phase, row.sequence))
    # The stack/trigger timing is kernel-owned (state_lifecycle): the gate
    # records every gain/window-expiry/proc/per-target-cooldown-start
    # transition in the same (time, phase, sequence) total order the walk
    # feeds, and returns the completed pairs.  The damage formula stays
    # here with the engine.
    gate = item_effects.eclipse_trigger_gate(effect)
    proc_events: list[dict[str, Any]] = []
    for trigger in triggers:
        proc_events.extend(
            {
                "time": proc.time,
                "damage": 0.0,
                "damage_type": effect.source.damage_type,
                "event_precision": proc.precision,
                "target_id": proc.target,
            }
            for proc in gate.feed(
                trigger.time,
                sequence=trigger.sequence,
                precision=trigger.precision,
                target=trigger.target_id,
            )
        )
    return proc_events, gate, denials
