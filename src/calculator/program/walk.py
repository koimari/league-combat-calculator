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
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
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

    The three identity strings are here rather than read off ``Program`` for
    one measured reason, and it is a **preserved defect**: the receipt path
    fills a breakdown row's identity inside its attacker loop, so a
    participant who dealt no damage in the window is published with an empty
    ``champion`` and an empty ``team``.  Reading identity off the roster
    instead would quietly *fix* that -- and this stage is pure, so it may
    relocate the decision but not revise it.  The published strings are
    therefore whatever the composition folded, and correcting them is its own
    slice with its own baseline move.
    """

    participant_id: str
    team: str
    champion: str
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
class SurvivalFold:
    """The three numbers one participant's settled state *implies*.

    The kernel stores three shield pools, a health and a max health; the
    published survival row wants their sum, their ratio and the five-term
    effective health.  Those three additions were being performed by the
    survival view, on ledger values, which is exactly what criterion 3
    forbids: a view that adds is a second producer of the number it claims to
    project, and a projection that can disagree with its walk is the
    incident's own shape one layer up.

    They are folded here instead, at the moment the walk settles, so what
    reaches the view is a leaf rather than three ingredients.  Nothing about
    the arithmetic changes -- the expressions below are the view's own,
    moved: ``remaining_shield`` keeps ``sum`` over the three-tuple and
    ``effective_health`` keeps its five terms in their original order,
    because float addition is not associative and a re-spelled sum is a
    changed number.
    """

    remaining_shield: float
    ending_health_ratio: float
    effective_health: float


def survival_folds(states: Sequence[Any]) -> tuple[SurvivalFold, ...]:
    """One :class:`SurvivalFold` per settled participant state, in walk order.

    Exported rather than inlined into :func:`walk` so a caller assembling a
    result by hand -- a fixture, a second composition -- folds through the
    same expression the walk does instead of writing a fourth copy of it.
    """
    folds: list[SurvivalFold] = []
    for state in states:
        pools = state["pools"]
        folds.append(
            SurvivalFold(
                remaining_shield=sum(
                    (pools.magic_shield, pools.physical_shield, pools.general_shield)
                ),
                ending_health_ratio=(
                    pools.health / pools.max_health if pools.max_health > 0.0 else 0.0
                ),
                effective_health=(
                    pools.max_health
                    + state["starting_shield"]
                    + state["support_shield_received"]
                    - pools.shield_expired
                    + state["healing_received"]
                ),
            )
        )
    return tuple(folds)


@dataclass(frozen=True, slots=True)
class ObjectiveFold:
    """The ten aggregates the objective block publishes, summed once.

    They were ten inline sums inside the receipt's return literal, which is
    where a total quietly counting a member it should not have counted is
    least visible.  Folding them here is what lets the TDD view publish them
    without adding: a view that sums is a second producer of the total it
    claims to project, and two producers of one total is the incident's own
    shape at the aggregate.
    """

    main_team_damage_before_death: float
    enemy_team_damage_before_death: float
    surviving_main_team: int
    focus_damage_before_death: float
    focus_support_value: float
    focus_healing: float
    main_team_effective_health: float
    enemy_team_effective_health: float
    total_support_value: float
    total_healing_reduced: float


@dataclass(frozen=True, slots=True)
class WalkResult:
    """Everything one walk produced, frozen at the moment it finished.

    ``states`` is the kernel's per-participant state list — the same objects
    the walk mutated, no longer mutable *through this record* — and
    ``actions`` is the exact sequence it consumed, so a receipt row and a
    score contribution can be traced to the same action rather than to two
    reconstructions of it.  ``rung`` rides along because "which engine priced
    this" is a property of the result and not of the caller's memory of it.

    ``outcomes``, ``grey_health`` and ``timeline_coverage`` are the folds the
    composition made after the kernel returned, empty until it does.  They are
    on the result rather than passed beside it because a view takes exactly
    ``(Program, WalkResult)``, and a number a view publishes that reached it
    by some other route is a number no counter can trace to this walk.
    """

    actions: tuple[SurvivalAction, ...]
    states: tuple
    coverage: tuple
    rung: Rung
    duration: float = 0.0
    survival: tuple[SurvivalFold, ...] = ()
    outcomes: tuple[AttackerOutcome, ...] = ()
    grey_health: Mapping[str, Any] | None = None
    timeline_coverage: Mapping[str, Any] | None = None
    damage_events: tuple[Mapping[str, Any], ...] = ()
    healing_events: tuple[Mapping[str, Any], ...] = ()
    support_events: tuple[Mapping[str, Any], ...] = ()
    utility_by_actor: Mapping[str, Any] = MappingProxyType({})
    target_allocation: Mapping[str, Any] | None = None
    objective: ObjectiveFold | None = None

    def action_count(self) -> int:
        """How many transitions this walk consumed — the one-walk counter."""
        return len(self.actions)

    def projected(self, **folds: Any) -> "WalkResult":
        """The same walk, carrying a fold the composition derived from it.

        A new record rather than a mutation: the result is frozen because a
        view that could write to it would be a sixth producer of numbers
        wearing a projection's name, and a fold that could edit it in place
        would be the same thing one step earlier.

        Only the named folds move, so a caller adding one cannot silently drop
        another -- and a fold this record does not declare raises here rather
        than being carried as an attribute the views would never find.
        """
        unknown = sorted(set(folds) - _FOLD_FIELDS)
        if unknown:
            raise TypeError(
                "the walk result declares no fold named " + ", ".join(unknown)
            )
        return replace(
            self,
            **{
                name: tuple(value) if name in _SEQUENCE_FOLDS else value
                for name, value in folds.items()
            },
        )


def walk(
    actions: Sequence[SurvivalAction],
    ctx: TransitionContext,
    *,
    coverage: Sequence[Any] = (),
    rung: Rung = CompiledFast(),
) -> WalkResult:
    """Run the kernel exactly once and freeze what it produced.

    The body is one call, one settlement, one fold and one record: this
    function adds no reordering and no filtering, because anything it added
    would be a second engine growing inside the seam that exists to stop
    there being one.  The one fold is :func:`survival_folds`, and it is here
    rather than in the view for the reason criterion 3 names: three sums the
    settled state implies belong to the walk that settled it, so what a
    projection receives is a leaf.  The sort order is the compiler's eight-element key,
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
        survival=survival_folds(ctx.states),
    )


# Every field a composition may hand back after the kernel returned.  Derived
# from the record rather than listed, so a fold added to ``WalkResult`` is
# settable the moment it exists and a typo in a caller is a raise rather than
# a silently ignored keyword.
_FOLD_FIELDS = frozenset(
    field.name
    for field in fields(WalkResult)
    if field.name
    not in {"actions", "states", "coverage", "rung", "duration", "survival"}
)

# The folds that are sequences.  Frozen means frozen: a list handed in here
# would leave the "result" mutable through the caller's own variable, which is
# the one thing freezing it was for.
_SEQUENCE_FOLDS = frozenset(
    {"outcomes", "damage_events", "healing_events", "support_events"}
)

__all__ = [
    "AttackerOutcome",
    "ObjectiveFold",
    "SurvivalFold",
    "WalkResult",
    "survival_folds",
    "walk",
]
