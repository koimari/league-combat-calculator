"""The optimizer's work-counter seam: one sink, threaded, never patched.

An optimizer request does three kinds of work — it *proposes* candidate
builds, it *scores* the ones its memo does not already know, and each score
drives some number of one-pair fights.  Wall time mixes all three with the
machine it ran on; these counters separate them, and the difference between
the pair-fight count and ``evaluations x enemies`` (the campaign runbook's
*residual*, R-25) moves the moment a cache stops hitting or a candidate stops
compiling — long before wall time leaves the noise.

Nothing here counts anything.  This module declares only *what* a counter
sink looks like and *which rung* priced an evaluation; the optimizer and the
participant timeline increment a sink the caller supplied, and the concrete
sink is the benchmark harness's own dataclass in
``scripts/bench_coupled_optimizer.py``.  That direction is deliberate (R-24):
a harness that monkey-patched the search to observe it could not be unit
tested and would not be measuring the code CI ships.  With no sink installed
every counting site is a single ``is None`` test.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Protocol


class Rung(StrEnum):
    """Which engine priced one coupled candidate evaluation.

    The coupled optimizer prefers the compiled panel walk and falls back to
    the receipt walk, but "fell back" alone is not a diagnosis: a fallback
    forced by the request gate, one forced by the candidate's own loadout,
    and one forced by a search-invariant failure that poisons every later
    evaluation have completely different costs and completely different
    fixes.  Four rungs, so a histogram reports the cause and not just the
    fact.
    """

    COMPILED = "compiled"
    """The compiled panel walk produced the score."""

    RECEIPT_WALK_GATE = "receipt_walk_gate"
    """The compiled path was never attempted — the request shape excludes it
    (no roster, receipt mode, Enemy Hits disabled) or it was switched off."""

    RECEIPT_WALK_CANDIDATE = "receipt_walk_candidate"
    """This candidate's own loadout holds a transition the compiler cannot
    represent; the next candidate may still compile."""

    SEARCH_POISONED = "search_poisoned"
    """A search-invariant compilation failure — the roster or a defensive
    signature panel — so no later evaluation in this search can compile."""


class WorkCounterSink(Protocol):  # pylint: disable=too-few-public-methods
    """What the optimizer needs of a work-counter sink: five mutable fields.

    A structural type with no methods is the whole point — the sink is data,
    and demanding two public methods of it would only invite behaviour into
    a counter.

    ``public_evaluations`` is deliberately absent: that figure is published
    in the optimizer's own response and the harness reads it there, so no
    counting site in ``src/`` can disagree with it.

    ``walk_invocations`` is the structural half of Phase 4's one-walk
    property.  Source counting says there is one ``run_survival_walk`` call
    expression in the tree; only a runtime counter says a composition
    entered it once **per pass** rather than twice per pass under two names,
    which is the failure "one call site" cannot see.  It is not one of the
    report's four counter families and is deliberately absent from the
    harness's published counters: it answers a structural question a test
    asks, not a work question a benchmark compares across runs.
    """

    measured_proposals: int
    score_memo_misses: int
    pair_run_fight_calls: int
    walk_invocations: int
    rungs: Counter[str]


def record_rung(sink: WorkCounterSink | None, rung: Rung) -> None:
    """Attribute one coupled evaluation to the engine that priced it."""
    if sink is not None:
        sink.rungs[str(rung)] += 1


def record_walk(sink: WorkCounterSink | None) -> None:
    """Count one entry into the kernel — the one-walk property, at runtime."""
    if sink is not None:
        sink.walk_invocations += 1
