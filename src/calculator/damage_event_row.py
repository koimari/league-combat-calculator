"""What every damage event carries, and what only some of them do.

The cast-event row has one producer that stamps every field on every row
(:mod:`cast_event_row`). A damage event does not: ``fight.ledger.event_ledger``
builds most of them, and the keystone walks build their own, so what a row
carries depends on which walk authored it.

That difference decides which reads may be fail-closed. Measured over the
2,458 damage and combat event rows in the committed coupled baseline, four
keys are on every row:

``time``, ``damage``, ``damage_type``, ``source``

and every other key is legitimately absent somewhere. ``raw_damage``,
``sequence``, ``attacker``, ``event_id``, ``overkill`` and ``pair_damage``
are each on 1,706 of 2,458; ``phase`` on 752; ``cc_duration`` on 54.

So a reader for one of those four refuses an absent key, and a reader for
any other takes the caller's default and is not a rule-5 violation. Anyone
converting the ER5 tail in bulk should read this first: treating the
optional keys as required raises on rows the engine legitimately produces,
and ``tests/test_damage_event_row.py`` re-derives the split from the
committed baseline so the claim above cannot rot.
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
