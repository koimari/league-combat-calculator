"""What every row of a composed roster pass carries.

``participant_timeline`` folds each pair fight's damage rows into the
``incoming`` and ``outgoing`` books of ``timeline.records.Ledgers``, and its
own schedulers append reactive rows to the same books. So a reader holding
one of these rows is holding the intersection of several producers, not one
producer's shape, and the fields below are that intersection.

Two committed corpora fix it, and neither is this module's own reading:

* ``docs/receipts/internal-row-census.json`` measures the ``damage_events``
  the engine hands the composition, 3,961 rows over every registered
  champion, and carries ``damage``, ``damage_type``, ``sequence``,
  ``source_key`` and ``time`` on every one.
* ``tests/test_row_stream_census.py`` measures the published projection of
  these very books, ``combat/events``, 1,706 rows, and adds ``attacker`` and
  ``target`` to that set.

A field the composition's own schedulers stamp but neither census names --
``_event_id``, ``_sk``, ``ability_instance`` -- is read with its own default
here rather than required, because no committed corpus speaks for it.

``raw_damage`` is the one field with an accessor and no requirement: the
publisher measures it at 1,365 of 1,706 rows, so it gets the optional form
and each caller states what it does without one.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

from .event_row_field import optional_field, required_field

__all__ = [
    "COMPOSED_REQUIRED_FIELDS",
    "row_attacker",
    "row_damage",
    "row_damage_type",
    "row_raw_damage",
    "row_sequence",
    "row_source_key",
    "row_target",
    "row_time",
]

#: The keys every composed row carries, whichever producer appended it.
COMPOSED_REQUIRED_FIELDS = (
    "attacker",
    "damage",
    "damage_type",
    "sequence",
    "source_key",
    "target",
    "time",
)


_required = partial(
    required_field,
    kind="composed roster row",
    stamper="every producer that appends to a composed book",
)


def row_time(event: Mapping[str, Any]) -> float:
    """WHEN the packet landed, where ``0.0`` is the fight's own origin."""
    return float(_required(event, "time"))


def row_damage(event: Mapping[str, Any]) -> float:
    """The mitigated damage. ``0.0`` is a real reading, so absent is not it."""
    return float(_required(event, "damage"))


def row_damage_type(event: Mapping[str, Any]) -> str:
    """Which resistance the packet met."""
    return str(_required(event, "damage_type"))


def row_raw_damage(event: Mapping[str, Any]) -> float | None:
    """The pre-mitigation damage; ``None`` where the producer priced none."""
    return optional_field(event, "raw_damage", float)


def row_source_key(event: Mapping[str, Any]) -> str:
    """The breakdown key this packet sums into."""
    return str(_required(event, "source_key"))


def row_sequence(event: Mapping[str, Any]) -> int:
    """Where the engine placed this packet among those sharing its timestamp."""
    return int(_required(event, "sequence"))


def row_attacker(event: Mapping[str, Any]) -> str:
    """Which participant dealt it."""
    return str(_required(event, "attacker"))


def row_target(event: Mapping[str, Any]) -> str:
    """Which participant took it."""
    return str(_required(event, "target"))
