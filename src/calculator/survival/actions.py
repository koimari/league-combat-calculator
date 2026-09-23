"""The order the survival walk consumes actions in.

``action_key``, ``participant_order``, ``event_sequence`` and
``event_timestamp`` build the total order.  The sort key is part of an
action's identity, so the receipt composition and the score compiler build
the same keys from here.

The rest of this interface lives beside it, one concept per module: the typed
action, its kind and its live amplification in :mod:`typed_action`, the record
each kind is built as in :mod:`action_families`, what an
event *is* and which modifier classes it declares in :mod:`classify`, when a
transition resolves in :mod:`phases`, and the kernel's four event references in
:mod:`event_slots`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .phases import TransitionRank, ordering_slot

# ---------------------------------------------------------------------------
# Ordering helpers (shared by the receipt composition and the compiler)
# ---------------------------------------------------------------------------


def event_sequence(event: Mapping[str, Any]) -> int:
    """Return a stable source sequence for simultaneous event ordering."""
    value = event.get("sequence", event.get("_trigger_sequence", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def event_timestamp(event: Mapping[str, Any]) -> float:
    """Return one raw event row's timestamp, the walk's ordering axis.

    A row that states no time is at 0.0, the fight's own origin; a row
    that states an unusable one is a stop, because no total order can
    place it.
    """
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("event time must be finite")
    return parsed


def participant_order(participant_id: object) -> tuple[int, str]:
    """Use a deterministic side order when sources share a timestamp."""
    text = str(participant_id or "")
    if text == "main":
        return (0, text)
    if text.startswith("ally:"):
        return (1, text)
    if text.startswith("enemy:"):
        return (2, text)
    return (3, text)


#: The walk's total order for one action: time, ordering slot, sequence,
#: participant order (side, id), participant id, event id, source.
ActionSortKey = tuple[float, TransitionRank, int, int, str, str, str, str]


def scheduled_heal_time(heal_event: Mapping[str, Any]) -> float:
    """WHEN a walk-authored heal lands, refusing an event that does not say.

    Both ledgers that schedule one read this, so the two walks place it at
    the same instant. A ``0.0`` default sorted a heal that lost its stamp to
    the fight's open: earlier than everything it should follow, and silent.
    """
    time = heal_event.get("time")
    if time is None:
        raise ValueError(
            "a walk-authored heal carries no 'time'; the producer "
            f"({heal_event.get('source_key', '<unnamed>')!r}) must stamp when "
            "it lands, because the ledger cannot place it otherwise"
        )
    return float(time)


def action_key(
    event_time: float,
    phase: TransitionRank,
    participant_id: str,
    event: Mapping[str, Any],
) -> ActionSortKey:
    """The survival walk's total order over event phases, never comparing
    payload dictionaries; pair packets precompute it per event (``_sk``).

    Element 1 is the rank's :func:`ordering_slot`, so one pair of ranks
    resolves together and ``compile.py``'s inline sort tuples stay comparable
    with this one.  ``_event_id`` is a dead tie-break for engine damage
    events: ``sequence`` is unique per pair fight, so an event without one is
    rejected rather than letting numbering become order-relevant.  NaN/inf is
    the one time ``float()`` accepts that no total order can place, and every
    action reaches this function, so the one guard is here.
    """
    time_value = float(event_time)
    if not math.isfinite(time_value):
        raise ValueError(
            f"action_key: event time must be finite, got {event_time!r} "
            f"(event_id={event.get('_event_id')!r}); a non-finite timestamp "
            "cannot establish a stable total order"
        )
    source_id = event.get("attacker", participant_id)
    return (
        time_value,
        ordering_slot(phase),
        event_sequence(event),
        *participant_order(source_id),
        str(participant_id),
        str(event.get("_event_id", "")),
        str(event.get("source", event.get("source_key", ""))),
    )


# ---------------------------------------------------------------------------
# Event classification (receipt adapter)
# ---------------------------------------------------------------------------


# The two helpers above are public because the one constructor lives in
# ``program.compile.action_from_event``, which classifies over prefetched
# hot fields and resolves a packet's declared class sets: a leading
# underscore on a name another layer must call is a boundary nobody can
# see.  What stays here is the vocabulary that constructor converts *into*.


__all__ = ["action_key", "event_sequence", "event_timestamp", "participant_order"]
