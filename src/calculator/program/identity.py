"""Who an event belongs to, and what its public id string is.

A public event id is positional string concatenation, so a mis-numbered id
shows up only as a receipt row pointing at the wrong trigger.  This module
names the grammar instead of leaving it to the authoring sites.  An
:class:`EventId` is an :data:`Origin`, who authored the event, and an ordinal,
which of that origin's events it is.  :func:`event_id_text` is the single
producer of the public string.  The four origins render as:

* :class:`PairOrigin` -- ``f"{attacker_id}:{defender_id}:{i}"``, authored by
  ``program.compile.WalkCompiler.add_engine_result`` and rebuilt by
  ``survival.compile.WalkCompiler``.
* :class:`SupportOrigin` -- ``f"{holder_id}:{label}:{i}"``, the timeline's
  ``:warmog:``, ``:heal:``, ``:grey:`` and ``:defy:`` packets.
* :class:`ReactiveOrigin` -- ``f"{trigger_id}:{label}:{i}"``, the timeline's
  ``:reactive:`` packets.
* :class:`DerivedOrigin` -- ``f"{parent_id}:{role}"``, every fan-out clone:
  ``:redirect``, ``:deferred:{tick}``, ``:shield``, ``:maw-omnivamp``,
  ``:ally:{i}``.

The two reference-carrying origins hold a parent :class:`EventId`, not a
parent string, which is what makes "this clone belongs to that packet" a type
invariant instead of a substring convention.  Fan-out is
``DerivedOrigin(parent, role)`` and never a suffix appended to a string, so a
clone whose parent was never authored is unconstructible rather than merely
wrong.

Nothing in ``survival/`` imports this module and nothing may: the kernel's
reference fields are plain ``int`` slots, and ``PIdx`` narrows a roster index
only on the ``program/`` side.  Annotating the kernel with these aliases
would invert the phase's one-way dependency for no runtime gain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, NewType

# A roster index, narrowed.  The kernel stores the same integer in
# ``SurvivalAction.subject`` / ``.attacker`` / ``.holder`` as a plain ``int``;
# this alias exists so a ``program/`` signature can say *which* integer it
# means without dragging the alias into the hot tuple.
PIdx = NewType("PIdx", int)

# Phase 2's ``trigger_stream.CAPABILITIES`` key.  One spelling, declared here
# rather than invented per consumer, so it never becomes a third name for
# ``MechanicCapability.mechanic``.
MechanicId = NewType("MechanicId", str)

# The ordinal an unnumbered id carries.  A fan-out clone that names exactly
# one child per parent ("this packet's redirect", "this hit's omnivamp heal")
# has nothing to number, and numbering it anyway would change the published
# string.  It is a named constant rather than ``None`` so ``EventId`` stays a
# pair of plain values with no optional arithmetic in it.
UNNUMBERED = -1


@dataclass(frozen=True, slots=True)
class PairOrigin:
    """One attacker's fight against one defender.

    The engine numbers a pair fight's damage rows by their position in the
    ledger, which is why the ordinal is order-derived and why the packet
    builder refuses an engine event with no sequence: without it, the walk's
    tie-break would depend on this numbering.
    """

    attacker: str
    defender: str


@dataclass(frozen=True, slots=True)
class SupportOrigin:
    """A holder authoring a packet under a named mechanic label.

    ``label`` is the mechanic's own slug as it already appears in the
    published id (``warmog``, ``heal``, ``grey``, ``defy``), not a display
    name: these strings are public receipt content.
    """

    holder: str
    label: str


@dataclass(frozen=True, slots=True)
class ReactiveOrigin:
    """A packet a *trigger* event caused, numbered within that trigger.

    Distinct from :class:`DerivedOrigin` because the relationship is
    causal rather than structural: a reactive packet is a new event the
    trigger produced, while a derived event is the same event seen on
    another route (redirected, deferred, cloned to an ally).
    """

    trigger: EventId
    label: str


@dataclass(frozen=True, slots=True)
class DerivedOrigin:
    """One event's fan-out clone, named by the role it plays.

    ``role`` is the suffix the rendered id carries.  Holding the parent id
    instead of its rendered text is the point: a role is a closed word about
    *this* parent, so an id cannot be assembled out of a string that names no
    event.
    """

    parent: EventId
    role: str


Origin = PairOrigin | SupportOrigin | ReactiveOrigin | DerivedOrigin


class EventId(NamedTuple):
    """One authored event: who authored it, and which of theirs it is."""

    origin: Origin
    ordinal: int = UNNUMBERED


def origin_text(origin: Origin) -> str:
    """The id-string prefix one origin contributes, without its ordinal.

    Total over the union and fail-closed: a fifth origin added without a
    rendering raises here rather than reaching a caller as a stringified
    dataclass, which would serialize into a public receipt.
    """
    if isinstance(origin, PairOrigin):
        return f"{origin.attacker}:{origin.defender}"
    if isinstance(origin, SupportOrigin):
        return f"{origin.holder}:{origin.label}"
    if isinstance(origin, ReactiveOrigin):
        return f"{event_id_text(origin.trigger)}:{origin.label}"
    if isinstance(origin, DerivedOrigin):
        return f"{event_id_text(origin.parent)}:{origin.role}"
    raise TypeError(
        f"{type(origin).__name__} is not an Origin; the union is closed "
        "(PairOrigin | SupportOrigin | ReactiveOrigin | DerivedOrigin)"
    )


def event_id_text(event: EventId) -> str:
    """The only producer of a public event-id string.

    An ordinal is appended after a colon; :data:`UNNUMBERED` appends nothing,
    which is what a single-child fan-out clone publishes.  Any other negative
    ordinal is a numbering bug and raises, because the two would otherwise
    render alike for ``-1`` and differently for ``-2``.
    """
    text = origin_text(event.origin)
    if event.ordinal == UNNUMBERED:
        return text
    if event.ordinal < 0:
        raise ValueError(
            f"EventId ordinal {event.ordinal} is negative but is not "
            "UNNUMBERED; an id is either numbered from zero or unnumbered"
        )
    return f"{text}:{event.ordinal}"


__all__ = [
    "UNNUMBERED",
    "DerivedOrigin",
    "EventId",
    "MechanicId",
    "Origin",
    "PIdx",
    "PairOrigin",
    "ReactiveOrigin",
    "SupportOrigin",
    "event_id_text",
    "origin_text",
]
