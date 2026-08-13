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

S4 landed the seam and the result type so the views had something to be
projections *of*, and S9 repointed the timeline's two legacy call sites here
with the five views.

**Which means this module made criterion 1's counter worse before it made it
better, and that was worth a sentence rather than a discovery.**  The
criterion asks for exactly one ``run_survival_walk(`` call expression in
``src/`` against a baseline of two; landing the seam beside the two it would
replace made it **three** — ``participant_timeline.py`` twice and the one
below — and it stayed three from S4 to S9.  A structural counter that rises
mid-phase is the normal shape of a strangler stage, but a counter that rises
with nothing saying so is indistinguishable from one nobody is driving.  It
is now the criterion's one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..survival.actions import SurvivalAction
from ..survival.transitions import TransitionContext, finalize_states, run_survival_walk
from .rung import CompiledFast, Rung


@dataclass(frozen=True, slots=True)
class AttackerOutcome:
    """One participant's folded numbers, exactly as the walk left them.

    Every field is a **leaf**: a number some rule already computed, carried
    here so a view can publish it without adding one.  That is the whole
    trick behind "a view re-runs no arithmetic" — the folding that used to
    happen inline in two composition tails happens once, in the composition,
    and what reaches a view is the answer rather than the ingredients.

    The two composition paths derive these differently and legitimately so:
    the compiled score path reads the score ledger's parallel arrays, the
    receipt path sums its annotated event streams.  Naming the *result* is
    what lets one view serve both without unifying two numerically distinct
    folds inside a stage labelled pure.
    """

    participant_id: str
    team: str
    champion: str
    level: int
    total_damage: float
    incoming_damage: float
    health_damage: float
    shield_absorbed: float
    effective_health: float
    healing_received: float
    healing_reduced: float
    support_shield_received: float
    support_value: float
    healing_output: float
    survived_window: bool
    death_time: float | None
    sources: tuple[Mapping[str, Any], ...] = ()
    utility_outcomes: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WalkResult:
    """Everything one walk produced, frozen at the moment it finished.

    ``states`` is the kernel's per-participant state list — the same objects
    the walk mutated, no longer mutable *through this record* — and
    ``actions`` is the exact sequence it consumed, so a receipt row and a
    score contribution can be traced to the same action rather than to two
    reconstructions of it.  ``rung`` rides along because "which engine priced
    this" is a property of the result and not of the caller's memory of it.

    ``outcomes`` is the per-participant fold the composition made after the
    kernel returned, empty until it does.  It is on the result rather than
    passed beside it because a view takes exactly ``(Program, WalkResult)``,
    and a number a view publishes that reached it by some other route is a
    number no counter can trace to this walk.
    """

    actions: tuple[SurvivalAction, ...]
    states: tuple
    coverage: tuple
    rung: Rung
    duration: float = 0.0
    outcomes: tuple[AttackerOutcome, ...] = ()

    def action_count(self) -> int:
        """How many transitions this walk consumed — the one-walk counter."""
        return len(self.actions)

    def with_outcomes(self, outcomes: Sequence[AttackerOutcome]) -> "WalkResult":
        """The same walk, carrying the fold the composition derived from it.

        A new record rather than a mutation: the result is frozen because a
        view that could write to it would be a sixth producer of numbers
        wearing a projection's name, and a fold that could edit it in place
        would be the same thing one step earlier.
        """
        return replace(self, outcomes=tuple(outcomes))


def walk(
    actions: Sequence[SurvivalAction],
    ctx: TransitionContext,
    *,
    coverage: Sequence[Any] = (),
    rung: Rung = CompiledFast(),
) -> WalkResult:
    """Run the kernel exactly once and freeze what it produced.

    The body is one call, one settlement and one record: this function adds
    no arithmetic, no reordering and no filtering, because anything it added
    would be a second engine growing inside the seam that exists to stop
    there being one.  The sort order is the compiler's eight-element key,
    already applied by the caller — sorting again here by a second rule is
    how two engines end up disagreeing about simultaneous events.

    ``finalize_states`` is inside rather than beside: both composition paths
    called it on the line after their own ``run_survival_walk``, which made
    "the walk has settled" a two-line convention two callers had to keep.  A
    caller that forgot it would read a state the kernel had not closed out,
    and nothing would say so.
    """
    run_survival_walk(actions, ctx)
    finalize_states(ctx.states, ctx.duration)
    return WalkResult(
        actions=tuple(actions),
        states=tuple(ctx.states),
        coverage=tuple(coverage),
        rung=rung,
        duration=float(ctx.duration),
    )


__all__ = ["AttackerOutcome", "WalkResult", "walk"]
