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
from functools import partial
from typing import Any

from .event_row_field import required_field

__all__ = [
    "cast_ordinal",
    "cast_slot",
    "cast_time",
]


_required = partial(required_field, kind="cast event", stamper="ability_rotation")


def cast_time(event: Mapping[str, Any]) -> float:
    """WHEN the cast landed. Absent is a producer break, never the fight's open."""
    return float(_required(event, "time"))


def cast_slot(event: Mapping[str, Any]) -> str:
    """WHICH slot cast. Absent is a producer break, never an unattributed cast."""
    return str(_required(event, "slot"))


def cast_ordinal(event: Mapping[str, Any]) -> int:
    """Which cast of that slot this is, counting from one."""
    return int(_required(event, "ordinal"))
