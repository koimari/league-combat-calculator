"""What every damage event carries, and what only some of them do.

The cast-event row has one producer that stamps every field on every row
(:mod:`cast_event_row`). A damage event does not: ``fight.ledger.event_ledger``
builds most of them, and the keystone walks build their own, so what a row
carries depends on which walk authored it.

That difference decides which reads may be fail-closed, so it is measured
rather than inferred. Two streams carry damage rows, and they are NOT one
shape with optional fields, which is what a first pass at this concluded by
pooling them:

``combat/events`` (1,706 rows) stamps twelve keys on every row, including
``raw_damage``, ``sequence``, ``attacker``, ``event_id``, ``overkill``,
``pair_damage`` and ``target``. ``fights/damage_events`` (752 rows) stamps
five, ``time``, ``damage``, ``damage_type``, ``source`` and ``phase``, and
carries none of those seven at all.

Pooled, that reads as "``raw_damage`` is on 1,706 of 2,458 rows", which
invites the wrong conclusion that some producer stamps inconsistently. It
does not: a reader holding a ``combat/events`` row may read ``raw_damage``
fail-closed, and a reader holding a fight row may never.

The accessors below take the INTERSECTION, because the callers that adopted
them serve both streams. A caller that knows which stream it holds may
require more, and ``tests/test_row_stream_census.py`` is the table to check
before doing so.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "REQUIRED_FIELDS",
    "event_damage",
    "event_damage_type",
    "event_source",
    "event_time",
]

#: The keys every damage event carries, whichever walk authored it. Derived
#: from the committed baseline, not from a producer's source.
REQUIRED_FIELDS = ("time", "damage", "damage_type", "source")


def _required(event: Mapping[str, Any], field: str) -> Any:
    """One universal field, or a refusal naming what the row does carry."""
    if field not in event:
        raise ValueError(
            f"a damage event carries no {field!r}; every walk that authors one "
            f"stamps it, so this row ({sorted(event)}) is not a damage event "
            "or its producer stopped stamping it"
        )
    return event[field]


def event_time(event: Mapping[str, Any]) -> float:
    """WHEN the packet landed, where ``0.0`` is the fight's own origin."""
    return float(_required(event, "time"))


def event_damage(event: Mapping[str, Any]) -> float:
    """The mitigated damage. ``0.0`` is a real reading, so absent is not it."""
    return float(_required(event, "damage"))


def event_damage_type(event: Mapping[str, Any]) -> str:
    """Which resistance the packet met."""
    return str(_required(event, "damage_type"))


def event_source(event: Mapping[str, Any]) -> str:
    """The breakdown row this packet belongs to."""
    return str(_required(event, "source"))
