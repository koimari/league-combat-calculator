"""Champion-owned stored damage resolved off the post-mitigation ledger."""

from collections.abc import Mapping
from typing import Any

from ...ability_atoms import ability_field
from ..ledger.event_ledger import _ordered_damage_events
from ..results import RotationResult
from ..rotation.cast_schedule import _CAST_SCHEDULE_EPS
from ..state import FightState


def _add_stored_damage(state: FightState, rotation: RotationResult) -> None:
    """Resolve champion-owned stored damage from the post-mitigation ledger.

    A stored-damage entry declares its ratio, window, source slots, and
    whether the ambient auto stream contributes. The source ledger is built
    before the stored proc is added, so the proc cannot store itself.
    """
    source_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
    )
    cast_positions = {slot: index for index, slot in enumerate(state.cast_order)}
    cast_times_by_slot: dict[str, list[float]] = {}
    for cast_event in rotation.cast_events:
        slot = str(cast_event.get("slot", ""))
        cast_times_by_slot.setdefault(slot, []).append(
            float(cast_event.get("time", 0.0))
        )

    for slot, ability_info in state.ability_damages.items():
        storage = ability_info.get("stored_damage")
        if not isinstance(storage, Mapping):
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, dict):
            continue
        cast_times = cast_times_by_slot.get(slot, [])
        if not cast_times:
            continue

        ratio = float(ability_field(storage, "ratio", form="stored_damage"))
        duration = float(ability_field(storage, "duration", form="stored_damage"))
        source_slots = {
            str(source_slot)
            for source_slot in ability_field(
                storage, "source_slots", form="stored_damage"
            )
        }
        include_auto_attacks = bool(
            ability_field(storage, "include_auto_attacks", form="stored_damage")
        )
        if ratio <= 0.0 or duration <= 0.0 or not source_slots:
            continue

        stored_events: list[dict[str, Any]] = []
        for start_time in cast_times[: max(0, int(row.get("casts", 0)))]:
            end_time = start_time + duration
            source_damage = 0.0
            for event in source_events:
                if not isinstance(event, Mapping):
                    continue
                damage_type = str(event["damage_type"])
                if damage_type not in {"physical", "magic"}:
                    continue
                source_key = str(event["source_key"])
                is_auto = source_key == "auto_attacks"
                if source_key not in source_slots and not (
                    is_auto and include_auto_attacks
                ):
                    continue
                event_time = float(event["time"])
                if event_time < start_time - _CAST_SCHEDULE_EPS:
                    continue
                if event_time > end_time + _CAST_SCHEDULE_EPS:
                    continue
                if (
                    abs(event_time - start_time) <= _CAST_SCHEDULE_EPS
                    and not is_auto
                    and source_key in cast_positions
                    and cast_positions[source_key] <= cast_positions.get(slot, -1)
                ):
                    continue
                source_damage += float(event["damage"])

            stored = source_damage * ratio
            if stored > 0.0:
                stored_events.append(
                    {
                        "time": end_time,
                        "damage_type": "true",
                        "damage": stored,
                        "event_precision": "exact",
                    }
                )

        total_stored = sum(float(event["damage"]) for event in stored_events)
        row["total_damage"] = total_stored
        row["total_raw"] = total_stored
        row["damage_type"] = "true"
        row["damage_by_type"] = {"true": total_stored} if total_stored > 0.0 else {}
        row["damage_events"] = stored_events
        row["event_phase"] = "ability"
        if total_stored > 0.0:
            row["detail"] = (
                f"{ratio * 100:g}% of post-mitigation physical and magic "
                f"champion damage stored in {len(stored_events)} Spirit Form "
                f"window{'s' if len(stored_events) != 1 else ''}"
            )
            state.total_damage += total_stored
