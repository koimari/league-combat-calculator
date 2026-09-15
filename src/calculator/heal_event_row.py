"""What every heal event carries, and what only some of them do.

The third producer measured this way, and it answers like the damage event
rather than like the cast event: several walks author a heal, so a field one
of them stamps is not a field all of them stamp.

Measured over the 1,161 healing rows in the committed coupled baseline,
three keys are on every row:

``time``, ``amount``, ``source``

and every other key is legitimately absent somewhere. ``raw_amount``,
``applied_amount``, ``overheal``, ``attacker``, ``event_id`` and
``healing_reduction_factor`` are each on 909 of 1,161; ``trigger_target`` on
861; ``kind`` on 252.

The accessors below are spelled ``healed_*`` on purpose: ``heal_time`` and
``heal_amount`` are already local names in the modules that read these rows,
and an import that shadows a local is how two earlier slices of this
campaign broke. ``tests/test_heal_event_row.py`` re-derives the split from
the baseline, so neither half of the claim can rot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "HEAL_REQUIRED_FIELDS",
    "healed_amount",
    "healed_source",
    "healed_time",
]

#: The keys every heal event carries, whichever walk authored it.
HEAL_REQUIRED_FIELDS = ("time", "amount", "source")


def _required(event: Mapping[str, Any], field: str) -> Any:
    """One universal field, or a refusal naming what the row does carry."""
    if field not in event:
        raise ValueError(
            f"a heal event carries no {field!r}; every walk that authors one "
            f"stamps it, so this row ({sorted(event)}) is not a heal event or "
            "its producer stopped stamping it"
        )
    return event[field]


def healed_time(event: Mapping[str, Any]) -> float:
    """WHEN the heal landed, where ``0.0`` is the fight's own origin."""
    return float(_required(event, "time"))


def healed_amount(event: Mapping[str, Any]) -> float:
    """How much it healed. ``0.0`` is a real reading: a fully overhealed packet."""
    return float(_required(event, "amount"))


def healed_source(event: Mapping[str, Any]) -> str:
    """The breakdown row this heal belongs to."""
    return str(_required(event, "source"))
