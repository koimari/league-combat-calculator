"""Which engine priced an evaluation, and — when it was not the fast one — why.

The optimizer prefers the compiled panel walk and falls back to the receipt
walk.  "Fell back" alone is not a diagnosis: a fallback the request gate
forced, one this candidate's own loadout forced, and one a search-invariant
failure forced have different costs and different fixes, and a histogram that
reported only *compiled* and *not compiled* would read as uniform fallback
with no cause.  Four rungs, so the histogram names the cause (D-69).

**Two vocabularies, deliberately, and this module holds the bridge.**
``work_counters.Rung`` is the published *label* — a ``StrEnum`` whose four
strings are the keys of every committed bench receipt, so they may not carry
a reason and may not change shape.  The union below is the *decision*, and
two of its four members carry the reason the label cannot.  Projecting one
onto the other is :func:`counter_label`, which is why there is a bridge and
not a second registry: a decision has exactly one label, and the label a
receipt records is derived from the decision rather than chosen beside it.

The distinction between the two failure rungs is the load-bearing one.
:class:`ReceiptWalk` is a *representation choice with a named cause* — a
roster-held receipt-only mechanic selects it once, deterministically, at
context setup, and the search continues.  :class:`SearchPoisoned` is reserved
for a genuine search-invariant **error**.  Reporting a declared roster
mechanic as poison would make a modelled build look like a broken one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Union

from ..work_counters import Rung as CounterRung


@dataclass(frozen=True, slots=True)
class CompiledFast:
    """The compiled panel walk priced this evaluation from cached actions."""


@dataclass(frozen=True, slots=True)
class CompiledFull:
    """The compiled walk priced it, rebuilding actions this evaluation.

    Its own member rather than a flag on :class:`CompiledFast` because the
    two cost different amounts and the residual (R-25) moves between them:
    collapsing them would hide a cache that stopped hitting behind a
    histogram that still reads 100% compiled.
    """


class FallbackScope(Enum):
    """Whether a receipt-walk fallback was the request's or the candidate's.

    Not a fifth rung: D-69 rules four states, and these two share one — the
    receipt walk priced the evaluation either way.  They are published under
    different labels because they have different fixes.  A ``REQUEST_GATE``
    fallback refused before any candidate was looked at (no roster, receipt
    mode, Enemy Hits off), so blaming a build for it would name the wrong
    thing; a ``CANDIDATE`` fallback is this loadout's, and the next candidate
    may still compile.
    """

    REQUEST_GATE = "request_gate"
    CANDIDATE = "candidate"


@dataclass(frozen=True, slots=True)
class ReceiptWalk:
    """The receipt walk priced it, and here is the mechanic that asked for it.

    ``reason`` is a receipt, not a log line: it is the sentence a fallback
    prints, so an amp holder reports *which* declaration the compiled kernel
    cannot represent rather than reporting an unexplained slow path.
    ``scope`` says whose refusal it was, and it is required for the same
    reason: "fell back" without a scope is the uniform-fallback histogram
    D-69 exists to replace.
    """

    reason: str
    scope: FallbackScope = FallbackScope.CANDIDATE


@dataclass(frozen=True, slots=True)
class SearchPoisoned:
    """A search-invariant compilation failure — every later candidate inherits it.

    Never a declared roster mechanic: that is :class:`ReceiptWalk`.  This is
    the roster or a defensive signature panel failing to compile, which is a
    programming error in the compiler or an unmodelled loadout, and the
    reason says which.
    """

    reason: str


Rung = Union[CompiledFast, CompiledFull, ReceiptWalk, SearchPoisoned]

RUNGS: tuple[type, ...] = (CompiledFast, CompiledFull, ReceiptWalk, SearchPoisoned)

# One decision, one published label.  ``CompiledFast`` and ``CompiledFull``
# share a label because the committed bench receipts have one ``compiled``
# key and R-32 forbids moving a baseline to add a second; the split lives in
# the decision, where a later stage can publish it without rewriting history.
_LABELS = {
    CompiledFast: CounterRung.COMPILED,
    CompiledFull: CounterRung.COMPILED,
    SearchPoisoned: CounterRung.SEARCH_POISONED,
}

_FALLBACK_LABELS = {
    FallbackScope.REQUEST_GATE: CounterRung.RECEIPT_WALK_GATE,
    FallbackScope.CANDIDATE: CounterRung.RECEIPT_WALK_CANDIDATE,
}


def counter_label(rung: Rung) -> CounterRung:
    """The published histogram key one decision is recorded under.

    Total over the union: a fifth member added without a label raises here
    rather than being counted as whatever the ``get`` default happened to be.
    """
    if isinstance(rung, ReceiptWalk):
        return _FALLBACK_LABELS[rung.scope]
    try:
        return _LABELS[type(rung)]
    except KeyError:
        raise TypeError(
            f"{type(rung).__name__} is not a Rung; the union is closed "
            f"({', '.join(member.__name__ for member in RUNGS)})"
        ) from None


def reason_of(rung: Rung) -> str:
    """The named cause a failure rung carries; ``""`` for the compiled ones.

    The empty string is the honest answer for a rung that succeeded — there
    is no cause to name — and it is distinguishable from a failure rung
    whose reason is missing, because such a rung cannot be constructed.
    """
    return getattr(rung, "reason", "")


def histogram(rungs: Iterable[Rung]) -> Counter:
    """The four-state histogram, keyed by published label.

    Accounting for 100% of evaluations is the property criterion 16 asserts,
    and it holds by construction here: every rung maps to exactly one label
    and :func:`counter_label` raises rather than dropping one.
    """
    tally: Counter = Counter()
    for rung in rungs:
        tally[str(counter_label(rung))] += 1
    return tally


def gate_rung(reason: str) -> Rung:
    """The rung a request whose shape excludes the compiled path takes."""
    return ReceiptWalk(reason, FallbackScope.REQUEST_GATE)


__all__ = [
    "RUNGS",
    "CompiledFast",
    "CompiledFull",
    "FallbackScope",
    "ReceiptWalk",
    "Rung",
    "SearchPoisoned",
    "counter_label",
    "gate_rung",
    "histogram",
    "reason_of",
]
