"""One cast the rotation placed, read through its producer's contract.

``fight.rotation.ability_rotation`` builds every ``cast_events`` row from one
comprehension and stamps ``time``, ``slot``, ``name``, ``ordinal``,
``cast_id``, ``target_id`` and ``resource_cost`` on all of them,
unconditionally. Consumers nonetheless read those fields through literal
defaults, and the defaults are the problem rather than the values: a cast
missing its ``time`` would be placed at the fight's own origin and a cast
missing its ``slot`` would be attributed to ``""``, both silently, and only
if the producer ever broke. That is the failure rule 5 exists to stop, and
the reason it survives review is that the default can never fire while the
producer is whole.

So the contract gets a name. These accessors raise for a field the producer
did not stamp, naming the field and what the row does carry, and a reader
that wants the whole row takes :class:`CastEventRow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CastEventRow",
    "cast_ordinal",
    "cast_row",
    "cast_slot",
    "cast_time",
]


@dataclass(frozen=True, slots=True)
class CastEventRow:
    """The fields every ``cast_events`` row carries, as one record."""

    time: float
    slot: str
    ordinal: int
    name: str
    cast_id: str


def _required(event: Mapping[str, Any], field: str) -> Any:
    """One stamped field, or a refusal naming what the row does carry."""
    if field not in event:
        raise ValueError(
            f"a cast event carries no {field!r}; ability_rotation stamps it on "
            f"every row it builds, so this row ({sorted(event)}) did not come "
            "from the rotation or the producer stopped stamping it"
        )
    return event[field]


def cast_time(event: Mapping[str, Any]) -> float:
    """WHEN the cast landed. Absent is a producer break, never the fight's open."""
    return float(_required(event, "time"))


def cast_slot(event: Mapping[str, Any]) -> str:
    """WHICH slot cast. Absent is a producer break, never an unattributed cast."""
    return str(_required(event, "slot"))


def cast_ordinal(event: Mapping[str, Any]) -> int:
    """Which cast of that slot this is, counting from one."""
    return int(_required(event, "ordinal"))


def cast_row(event: Mapping[str, Any]) -> CastEventRow:
    """The whole row, for a reader that wants more than one field."""
    return CastEventRow(
        time=cast_time(event),
        slot=cast_slot(event),
        ordinal=cast_ordinal(event),
        name=str(_required(event, "name")),
        cast_id=str(_required(event, "cast_id")),
    )
