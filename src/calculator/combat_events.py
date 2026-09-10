"""Validate user-authored spell casts before the combat engine prices them."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class CombatEvent:
    """One requested cast and its explicit recipient."""

    id: str
    time: float
    caster_id: str
    slot: str
    recipient_id: str


def parse_combat_events(value: object) -> tuple[CombatEvent, ...] | None:
    """Preserve absence and validate each cast without coercing user values."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("combat_events must be an array with at most 256 casts")
    events = []
    seen = set()
    fields = {"id", "time", "caster_id", "slot", "recipient_id"}
    for index, row in enumerate(value):
        label = f"combat_events[{index}]"
        if not isinstance(row, Mapping) or set(row) != fields:
            raise ValueError(
                f"{label} requires id, time, caster_id, slot, recipient_id"
            )
        for key in fields - {"time"}:
            if (
                not isinstance(row[key], str)
                or not row[key].strip()
                or len(row[key]) > 120
            ):
                raise ValueError(f"{label}.{key} must be a nonempty short string")
        if row["id"] in seen:
            raise ValueError(f"{label}.id must be unique")
        seen.add(row["id"])
        time = row["time"]
        if (
            isinstance(time, bool)
            or not isinstance(time, (int, float))
            or not math.isfinite(time)
            or time < 0
        ):
            raise ValueError(f"{label}.time must be a finite nonnegative number")
        if row["slot"] not in {"Q", "W", "E", "R"}:
            raise ValueError(f"{label}.slot must be Q, W, E, or R")
        events.append(CombatEvent(**{**row, "time": float(time)}))
    return tuple(sorted(events, key=lambda event: event.time))


def event_receipt(event: CombatEvent) -> dict[str, Any]:
    """Return the public request fields for an accepted cast."""
    return {
        "id": event.id,
        "time": event.time,
        "caster_id": event.caster_id,
        "slot": event.slot,
        "recipient_id": event.recipient_id,
    }


def roster_ids(names: list[str], team: str) -> list[str]:
    """Use receipt IDs and suffix repeated champions in roster order."""
    counts: dict[str, int] = {}
    result = []
    for name in names:
        counts[name] = counts.get(name, 0) + 1
        result.append(
            f"{team}:{name}" + (f":{counts[name]}" if counts[name] > 1 else "")
        )
    return result


def parse_combat_events_mode(value: object) -> str:
    """Choose whether the list replaces a scene or only its named casters."""
    if value is None:
        return "replace"
    if value not in ("replace", "overrides"):
        raise ValueError("combat_events_mode must be replace or overrides")
    return str(value)


def combat_event_contract() -> dict[str, Any]:
    """Publish the same certified recipients that request validation accepts."""
    return {
        "schema_version": 1,
        "modes": ["overrides", "replace"],
        "champions": {
            "Lulu": {
                "Q": {"recipients": ["enemy"]},
                "W": {"recipients": ["self", "ally", "enemy"]},
                "E": {"recipients": ["self", "ally", "enemy"]},
                "R": {"recipients": ["self", "ally"]},
            },
            "Nasus": {"W": {"recipients": ["enemy"]}},
            "Elise": {"E": {"recipients": ["enemy"]}},
            "Rammus": {"E": {"recipients": ["enemy"]}},
            "Zilean": {"E": {"recipients": ["enemy"]}},
            "Vayne": {"E": {"recipients": ["enemy"]}},
        },
    }
