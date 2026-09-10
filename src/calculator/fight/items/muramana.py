"""Muramana's per-cast packet identity and shock lockout."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...ability_atoms import ability_field
from ...state_lifecycle import InstanceCadence
from ..ledger.event_rows import (
    _CAST_TIME_RESOLUTION,
    _finite_numeric_receipt,
    _item_proc_precision,
)
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState, _damage_inputs


@dataclass(frozen=True, slots=True)
class _MuramanaCastReceipt:
    """Validated inputs for one Muramana cast-ledger row."""

    slot: str
    event_time: float
    cast_id: str | None
    target_id: str | None
    raw_instances: int
    authored_events: list[dict[str, Any]] | None
    proc_precision: str


def _muramana_cast_receipt(
    state: FightState,
    cast_event: Any,
    breakdown: Mapping[str, Any],
    *,
    require_identity: bool,
) -> _MuramanaCastReceipt | None:
    """Validate one cast row and collect its proc-event inputs."""
    if not isinstance(cast_event, Mapping):
        return None
    slot = cast_event.get("slot")
    ability = state.ability_damages.get(slot) if isinstance(slot, str) else None
    if not isinstance(slot, str) or not isinstance(ability, Mapping):
        return None
    parts = ability_field(ability, "parts")
    if not isinstance(parts, (tuple, list)):
        return None
    # Shock is gated on "Dealing ability damage to champions".  The authored
    # parts answer that for an ordinary cast, but NOT for one whose damage is
    # a re-attributed rider: Kayle E authors only zero-amount parts once its
    # rider moves onto the swing it forced, while the rotation still counts
    # it into ``total_muramana_procs`` off the cast's PRICED total.  Asking
    # the parts alone desynchronised this walk from the very count it is
    # checked against below, which withheld the whole row.  Either fact
    # showing damage is a damaging cast; only both showing none is not.
    row = breakdown.get(slot)
    priced = (
        float(row.get("total_damage", 0.0) or 0.0) if isinstance(row, Mapping) else 0.0
    )
    if priced <= 0.0 and not any(
        part.amount > 0.0 or part.hp_scaled_damage is not None for part in parts
    ):
        return _MuramanaCastReceipt(slot, 0.0, None, None, 0, None, "")
    event_time = _finite_numeric_receipt(cast_event.get("time"))
    cast_id = cast_event.get("cast_id")
    target_id = cast_event.get("target_id")
    raw_instances = ability_field(ability, "cast_instances")
    if (
        event_time is None
        or event_time < 0.0
        or (
            require_identity
            and (
                not isinstance(cast_id, str)
                or not cast_id.strip()
                or not isinstance(target_id, str)
                or not target_id.strip()
            )
        )
        or isinstance(raw_instances, bool)
        or not isinstance(raw_instances, int)
        or raw_instances <= 0
    ):
        return None
    authored_events = row.get("damage_events") if isinstance(row, Mapping) else None
    return _MuramanaCastReceipt(
        slot=slot,
        event_time=event_time,
        cast_id=cast_id if isinstance(cast_id, str) else None,
        target_id=target_id if isinstance(target_id, str) else None,
        raw_instances=raw_instances,
        authored_events=(
            authored_events
            if isinstance(authored_events, list)
            and any(
                isinstance(candidate, Mapping)
                and (_finite_numeric_receipt(candidate.get("damage")) or 0.0) > 0.0
                for candidate in authored_events
            )
            else None
        ),
        proc_precision=_item_proc_precision(state, slot),
    )


def _muramana_identity_fields(
    receipt: _MuramanaCastReceipt,
    instance_index: int,
    *,
    enabled: bool,
) -> dict[str, str]:
    """Return the validated target and per-instance cast identity fields."""
    if not enabled:
        return {}
    cast_id = receipt.cast_id
    if receipt.raw_instances > 1:
        cast_id = f"{cast_id}:{instance_index + 1}"
    return {"cast_id": str(cast_id), "target_id": str(receipt.target_id)}


def _muramana_authored_events(
    receipt: _MuramanaCastReceipt,
    cursor: int,
    *,
    include_identity: bool,
) -> tuple[list[dict[str, Any]], int] | None:
    """Consume one positive authored packet for each cast instance."""
    authored_events = receipt.authored_events
    if authored_events is None:
        return None
    events: list[dict[str, Any]] = []
    for instance_index in range(receipt.raw_instances):
        while cursor < len(authored_events):
            candidate = authored_events[cursor]
            cursor += 1
            if not isinstance(candidate, Mapping):
                return None
            candidate_time = _finite_numeric_receipt(candidate.get("time"))
            candidate_damage = _finite_numeric_receipt(candidate.get("damage"))
            if candidate_time is None or candidate_damage is None:
                return None
            # ``cast_events`` publishes times rounded to milliseconds while
            # rows author raw plan times, so an up-rounded cast boundary
            # would disown its own hit without half the rounding step.
            if candidate_time + _CAST_TIME_RESOLUTION + 1e-9 < receipt.event_time:
                continue
            if candidate_damage <= 0.0:
                continue
            precision = candidate.get("event_precision")
            if not isinstance(precision, str) or not precision.strip():
                return None
            events.append(
                {
                    "time": candidate_time,
                    "damage": 0.0,
                    "event_precision": precision,
                    **_muramana_identity_fields(
                        receipt, instance_index, enabled=include_identity
                    ),
                }
            )
            break
        else:
            return None
    return events, cursor


def _muramana_boundary_events(
    receipt: _MuramanaCastReceipt, *, include_identity: bool
) -> list[dict[str, Any]]:
    """Build one cast-boundary event for each validated cast instance."""
    return [
        {
            "time": receipt.event_time,
            "damage": 0.0,
            "event_precision": receipt.proc_precision,
            **_muramana_identity_fields(
                receipt, instance_index, enabled=include_identity
            ),
        }
        for instance_index in range(receipt.raw_instances)
    ]


def _apply_muramana_lockout(
    events: list[dict[str, Any]], lockout_seconds: float | None
) -> list[dict[str, Any]]:
    """Filter exact event identities through the shared cadence primitive."""
    if lockout_seconds is None:
        return events
    cadence = InstanceCadence(interval_seconds=lockout_seconds)
    return [
        event
        for event in events
        if cadence.allow(
            float(event["time"]),
            f"{event['target_id']}|cast:{event['cast_id']}",
        )
    ]


def _muramana_proc_events(
    state: FightState,
    rotation: RotationResult,
    *,
    lockout_seconds: float | None = None,
) -> list[dict[str, Any]] | None:
    """Build lockout-filtered events for authored Muramana proc instances.

    Cast ID, target ID, exact hit time, and the parser-owned lockout are
    required. A malformed receipt withholds the event list. The caller can
    then use the existing named aggregate fallback.
    """
    if rotation.total_muramana_procs <= 0:
        return []
    gate_enabled = lockout_seconds is not None
    if gate_enabled and (not math.isfinite(lockout_seconds) or lockout_seconds <= 0.0):
        return None
    events: list[dict[str, Any]] = []
    event_cursors: dict[str, int] = {}
    breakdown = state.breakdown
    if not isinstance(breakdown, Mapping):
        breakdown = {}
    for cast_event in rotation.cast_events:
        receipt = _muramana_cast_receipt(
            state, cast_event, breakdown, require_identity=gate_enabled
        )
        if receipt is None:
            return None
        if receipt.raw_instances == 0:
            continue
        if receipt.authored_events is not None:
            authored = _muramana_authored_events(
                receipt,
                event_cursors.get(receipt.slot, 0),
                include_identity=gate_enabled,
            )
            if authored is None:
                return None
            event_cursors[receipt.slot] = authored[1]
            events.extend(authored[0])
            continue
        events.extend(_muramana_boundary_events(receipt, include_identity=gate_enabled))
    if len(events) != rotation.total_muramana_procs:
        return None
    return _apply_muramana_lockout(events, lockout_seconds)


def _add_per_ability_hit_damage(state: FightState, rotation: RotationResult) -> None:
    """Price Shock once per damaging ability hit its cast ledger accepted."""
    resists = state.resists
    breakdown = state.breakdown
    for source in state.damage_effects.per_ability_hits:
        if rotation.total_muramana_procs <= 0:
            # No damaging ability cast consumed Shock: the passive never
            # fired, and no row is authored (P3 package 3E; the
            # Shaped-Charge precedent — no aggregate substitute).
            continue
        raw = source.raw_damage(_damage_inputs(state))
        per_proc = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        total_damage = per_proc * rotation.total_muramana_procs
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        proc_events = _muramana_proc_events(
            state,
            rotation,
            lockout_seconds=source.same_target_cast_lockout_seconds,
        )
        if proc_events is None:
            # A malformed or count-mismatched cast ledger withholds the
            # event list: the aggregate price is preserved (the proc count
            # is the trusted cast receipt) but the row is stamped with a
            # NAMED reason (P3 package 3E), and the coverage classifier
            # keeps it coarse.
            breakdown[source.breakdown_key]["event_phase"] = "coarse"
            breakdown[source.breakdown_key][
                "withheld_reason"
            ] = "malformed_proc_receipt"
        else:
            total_damage = per_proc * len(proc_events)
            breakdown[source.breakdown_key]["total_damage"] = total_damage
            breakdown[source.breakdown_key]["lockout_receipt"] = {
                "interval_seconds": source.same_target_cast_lockout_seconds,
                "identity": "target_id|cast:cast_id",
                "candidate_count": rotation.total_muramana_procs,
                "accepted_count": len(proc_events),
                "suppressed_count": rotation.total_muramana_procs - len(proc_events),
            }
            for event in proc_events:
                event["damage"] = per_proc
                event["damage_type"] = source.damage_type
            if proc_events:
                breakdown[source.breakdown_key]["damage_events"] = proc_events
                breakdown[source.breakdown_key]["event_phase"] = "ability"
        state.total_damage += total_damage
