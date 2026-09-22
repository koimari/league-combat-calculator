"""What every heal event carries, and what only some of them do.

The third producer measured this way, and it answers like the damage event
rather than like the cast event: several walks author a heal, so a field one
of them stamps is not a field all of them stamp.

Two streams carry heal rows and they are not one shape either.
``combat/healing_events`` (909 rows) stamps eleven keys on every row,
including ``raw_amount``, ``applied_amount``, ``overheal``, ``attacker``
and ``healing_reduction_factor``. ``fights/self_healing_events`` (252 rows)
stamps four, ``time``, ``amount``, ``source`` and ``kind``, and carries
none of the others.

The three required accessors below are the intersection, which is what a
caller serving both streams may require. ``tests/test_row_stream_census.py``
holds the per-stream table for a caller that knows which one it has.
:func:`healed_category` is the exception and says so in its own docstring:
neither census measures it, so it answers ``None`` rather than raising.

The accessors below are spelled ``healed_*`` on purpose: ``heal_time`` and
``heal_amount`` are already local names in the modules that read these rows,
and an import that shadows a local silently changes what a module reads.
``tests/test_heal_event_row.py`` re-derives the split from the baseline, so
neither half of the claim can rot.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

from .event_row_field import optional_field, required_field

__all__ = [
    "HEAL_REQUIRED_FIELDS",
    "healed_amount",
    "healed_category",
    "healed_source",
    "healed_time",
]

#: The keys every heal event carries, whichever walk authored it.
HEAL_REQUIRED_FIELDS = ("time", "amount", "source")


_required = partial(
    required_field, kind="heal event", stamper="every walk that authors one"
)


def healed_time(event: Mapping[str, Any]) -> float:
    """WHEN the heal landed, where ``0.0`` is the fight's own origin."""
    return float(_required(event, "time"))


def healed_amount(event: Mapping[str, Any]) -> float:
    """How much it healed. ``0.0`` is a real reading: a fully overhealed packet."""
    return float(_required(event, "amount"))


def healed_source(event: Mapping[str, Any]) -> str:
    """The breakdown row this heal belongs to."""
    return str(_required(event, "source"))


def healed_category(event: Mapping[str, Any]) -> str | None:
    """Which recovery family this heal belongs to; neither census measures it."""
    return optional_field(event, "healing_category", str)
