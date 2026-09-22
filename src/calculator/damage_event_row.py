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

``raw_damage`` is the one field outside that intersection with an accessor,
and it takes the optional form for exactly the reason above: a reader that
serves both streams gets ``None`` from a fight row and says for itself what
it prices without a pre-mitigation number.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

from .event_row_field import optional_field, required_field

__all__ = [
    "REQUIRED_FIELDS",
    "event_damage",
    "event_damage_type",
    "event_execute_threshold_ratio",
    "event_precision",
    "event_raw_damage",
    "event_source",
    "event_time",
]

#: The keys every damage event carries, whichever walk authored it. Derived
#: from the committed baseline, not from a producer's source.
REQUIRED_FIELDS = ("time", "damage", "damage_type", "source")


_required = partial(
    required_field, kind="damage event", stamper="every walk that authors one"
)


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


def event_raw_damage(event: Mapping[str, Any]) -> float | None:
    """The pre-mitigation damage; ``None`` where this row's walk priced none."""
    return optional_field(event, "raw_damage", float)


def event_precision(event: Mapping[str, Any]) -> str | None:
    """How exactly this packet's time is placed; ``None`` where none was stated."""
    return optional_field(event, "event_precision", str)


def event_execute_threshold_ratio(event: Mapping[str, Any]) -> float | None:
    """The health share below which this packet executes; ``None`` if it cannot."""
    return optional_field(event, "execute_threshold_ratio", float)
