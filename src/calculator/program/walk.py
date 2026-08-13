"""The one kernel call site, and the frozen result five views project.

Two engines pricing one mechanic is failure mode C of the incident this
campaign exists to close, and the timeline has two ``run_survival_walk`` call
sites — one for the receipt, one for the score.  They agree because two
pieces of composition code have been kept in step by hand, which is exactly
the arrangement that stopped being true for Imperial Mandate.

This module is where that becomes structural: one call site, one invocation
per pass, and a :class:`WalkResult` the views read instead of re-running the
walk in their own shape.  The result is **frozen** because a view that could
mutate it would be a sixth producer of numbers wearing a projection's name;
freezing it is what lets criterion 3 say "every number a view emits is
already a leaf of the result" as a property rather than a review note.

**The signature is a documented reading of the phase's Shape.**  Shape signs
``walk(program, ledger)``; this kernel carries its ledger *on* the transition
context (``TransitionContext.ledger``), so the parameter here is the context
that holds it.  One object, not two: passing both would create a pair that
can disagree, and the ledger the walk actually drives would be the one nobody
passed.

Repointing the timeline's two legacy call sites at this function is Phase 4
S9's, with the five views; S4 lands the seam and the result type so the views
have something to be projections *of*.

**Which means this module makes criterion 1's counter worse before it makes
it better, and that is worth a sentence rather than a discovery.**  The
criterion asks for exactly one ``run_survival_walk(`` call expression in
``src/`` against a baseline of two; landing the seam beside the two it will
replace makes it **three** — ``participant_timeline.py`` twice and line 77
below — and it stays three until S9 repoints them.  A structural counter
that rises mid-phase is the normal shape of a strangler stage, but a counter
that rises with nothing saying so is indistinguishable from one nobody is
driving.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..survival.actions import SurvivalAction
from ..survival.transitions import TransitionContext, run_survival_walk
from .rung import CompiledFast, Rung


@dataclass(frozen=True, slots=True)
class WalkResult:
    """Everything one walk produced, frozen at the moment it finished.

    ``states`` is the kernel's per-participant state list — the same objects
    the walk mutated, no longer mutable *through this record* — and
    ``actions`` is the exact sequence it consumed, so a receipt row and a
    score contribution can be traced to the same action rather than to two
    reconstructions of it.  ``rung`` rides along because "which engine priced
    this" is a property of the result and not of the caller's memory of it.
    """

    actions: tuple[SurvivalAction, ...]
    states: tuple
    coverage: tuple
    rung: Rung

    def action_count(self) -> int:
        """How many transitions this walk consumed — the one-walk counter."""
        return len(self.actions)


def walk(
    actions: Sequence[SurvivalAction],
    ctx: TransitionContext,
    *,
    coverage: Sequence[Any] = (),
    rung: Rung = CompiledFast(),
) -> WalkResult:
    """Run the kernel exactly once and freeze what it produced.

    The whole body is one call and one record: this function adds no
    arithmetic, no reordering and no filtering, because anything it added
    would be a second engine growing inside the seam that exists to stop
    there being one.  The sort order is the compiler's eight-element key,
    already applied by the caller — sorting again here by a second rule is
    how two engines end up disagreeing about simultaneous events.
    """
    run_survival_walk(actions, ctx)
    return WalkResult(
        actions=tuple(actions),
        states=tuple(ctx.states),
        coverage=tuple(coverage),
        rung=rung,
    )


__all__ = ["WalkResult", "walk"]
