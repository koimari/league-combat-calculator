"""The one kernel call site, and the frozen result five views project.

Two engines pricing one mechanic is how the receipt and the score come to
disagree, so ``src/`` holds exactly one ``run_survival_walk(`` call
expression: the one below.  Every view reads the :class:`WalkResult` it
returns instead of re-running the walk in its own shape.  The result is
frozen, which makes "every number a view emits is already a leaf of the
result" a property rather than a review note.

The kernel carries its ledger on the transition context
(``TransitionContext.ledger``), so this signature takes the context rather
than the pair ``(program, ledger)``.  One object, not two: passing both
creates a pair that can disagree, and the ledger the walk drives would be the
one nobody passed.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import Any

from ..cleanse_eligibility import merged_interval_duration
from ..delivery_eligibility import (
    delivery_declarations_receipt,
    spell_shield_rules_receipt,
)
from ..interaction_effects import public_defense
from ..survival.actions import SurvivalAction
from ..survival.transitions import TransitionContext, finalize_states, run_survival_walk
from ..work_counters import WorkCounterSink, record_walk
from .precision import round_field
from .rung import CompiledFast, Rung


@dataclass(frozen=True, slots=True)
class AttackerOutcome:
    """One participant's folded numbers, exactly as the walk left them.

    Every field is a leaf: a number some rule already computed, carried here so
    a view can publish it without adding one.  The folding happens once, in the
    composition, so what reaches a view is the answer and not the ingredients.

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


def _crowd_control_immunity(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """One settled state's crowd-control immunity receipt, or ``None``.

    Folded here rather than in the view because the eligibility record
    answers with :meth:`public_receipt`, and a view's call graph may not
    reach a method that computes -- the window's own expiry is an addition.
    The recipient id is *not* stamped here: naming who the row belongs to is
    the projection's job and needs no arithmetic.
    """
    grants = state.get("crowd_control_immunity_grants") or ()
    if not grants:
        return None
    latest = grants[-1]
    eligibility = state.get("crowd_control_immunity_eligibility")
    return {
        "shield_source": latest["source"],
        "source_atoms": [dict(atom) for atom in latest.get("source_atoms", ())],
        "window": (
            eligibility.window.public_receipt() if eligibility is not None else None
        ),
        "active_until": round_field(
            "crowd_control_immunity.active_until", float(latest["expires_at"])
        ),
        "reason_immunity_ended": latest.get("ended_reason"),
        "eligibility": (
            eligibility.public_receipt() if eligibility is not None else None
        ),
        "blocked": [
            dict(entry) for entry in state.get("crowd_control_immunity_blocked", [])
        ],
        "decisions": [
            dict(entry) for entry in state.get("crowd_control_immunity_decisions", [])
        ],
    }


def _spell_shield(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """One settled state's spell-shield receipt, or ``None`` where none was
    declared.

    Extends the kernel declaration with the walk-observed lifecycle: the
    sourced window (an infinite Annul window publishes ``until`` as ``None``),
    the acceptance and block rule, the selected cast identity, the one-use
    budget before and after, the blocked packets, every eligibility decision,
    the triggered heal, the declared categorical rules and the receipted
    cooldown.  Here for the same reason as :func:`_crowd_control_immunity`.
    """
    eligibility = state.get("spell_shield_eligibility")
    if eligibility is None:
        return None
    window = eligibility.window.public_receipt()
    if window["until"] == float("inf"):
        window["until"] = None
    blocked_cast = state["spell_shield_blocked_cast"]
    return {
        "source": state["spell_shield_source"],
        "window": window,
        "acceptance": eligibility.acceptance.public_receipt(),
        "block_rule": eligibility.block_rule,
        "rules": spell_shield_rules_receipt(),
        "uses_before": 1,
        "uses_after": state.get("spell_shield_uses_remaining"),
        "selected_cast_identity": (str(blocked_cast[-1]) if blocked_cast else None),
        "blocked_packets": [
            dict(entry) for entry in state.get("spell_shield_blocked_packets", [])
        ],
        "decisions": [dict(entry) for entry in state.get("spell_shield_decisions", [])],
        "triggered_heal": (
            {
                "time": round_field(
                    "spell_shield.triggered_heal.time",
                    float(state["spell_shield_heal_time"]),
                ),
                "amount": round_field(
                    "spell_shield.triggered_heal.amount",
                    float(state["spell_shield_heal_amount"]),
                ),
                "delay": round_field(
                    "spell_shield.triggered_heal.delay",
                    float(state["spell_shield_heal_delay"]),
                ),
                "source": state["spell_shield_heal_source"],
            }
            if state.get("spell_shield_heal_time") is not None
            else None
        ),
        "cooldown_seconds": state.get("spell_shield_cooldown_seconds"),
        "cooldown_atom": (
            dict(state["spell_shield_cooldown_atom"])
            if state.get("spell_shield_cooldown_atom") is not None
            else None
        ),
        # The rearm clock and every rearm the walk observed.  ``None`` is a
        # shield that carries no clock at all (Sivir's timed shield); a clock
        # with ``sourced`` False never rearms, and an empty ``rearms`` list on
        # a sourced clock means the cooldown outlasted the fight.  Both are
        # published so a second block is never an unexplained one.
        "rearm": (
            state["spell_shield_rearm"].public_receipt()
            if state.get("spell_shield_rearm") is not None
            else None
        ),
        "rearms": [dict(entry) for entry in state.get("spell_shield_rearm_events", [])],
    }


def _projectile_defense(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """One settled state's projectile-defense receipt, or ``None``.

    Extends the static declaration (:func:`public_defense`) with the
    walk-observed state: the remaining full-block uses, the six typed
    delivery declarations, and -- for an event-id selection -- the selected
    ids that never matched an incoming event, which is the named fail-closed
    receipt for a positional selection no option parse could validate.  Here
    for the same reason as :func:`_crowd_control_immunity`: both
    ``public_defense`` and ``delivery_declarations_receipt`` answer through
    ``public_receipt``, and a view's call graph may not reach a method that
    computes.
    """
    base = public_defense(state["projectile_defense"])
    if base is None:
        return None
    base["remaining_uses"] = state.get("projectile_defense_uses_remaining")
    base["delivery_declarations"] = delivery_declarations_receipt()
    eligibility = state.get("projectile_defense_eligibility")
    if eligibility is not None and eligibility.selection.blocked_event_ids:
        matched = state.get("projectile_defense_event_id_matches", set())
        base["blocked_event_ids_unmatched"] = [
            event_id
            for event_id in eligibility.selection.blocked_event_ids
            if event_id not in matched
        ]
    return base


@dataclass(frozen=True, slots=True)
class SurvivalFold:
    """What one participant's settled state *implies*, folded once.

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

    The last five members joined for the same rule and not for a different
    one.  Two are interval unions the row publishes (the action downtime and
    the post-cleanse control downtime); three are receipt objects assembled
    through ``public_receipt``, whose bodies compute.  All five are
    ingredients the view would otherwise fold, so all five are folded here.
    """

    remaining_shield: float
    ending_health_ratio: float
    effective_health: float
    action_downtime: float
    crowd_control_downtime: float
    crowd_control_immunity: Mapping[str, Any] | None
    spell_shield: Mapping[str, Any] | None
    projectile_defense: Mapping[str, Any] | None


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
                action_downtime=merged_interval_duration(
                    state["action_downtime_intervals"]
                ),
                crowd_control_downtime=merged_interval_duration(
                    state["crowd_control_intervals"]
                ),
                crowd_control_immunity=_crowd_control_immunity(state),
                spell_shield=_spell_shield(state),
                projectile_defense=_projectile_defense(state),
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


# One entry into the kernel, one number.  Process-local and monotonic, so a
# walk's identity is also readable — "walk 3 of this process" — rather than
# only comparable.
_WALK_SEQUENCE = itertools.count(1)


@dataclass(frozen=True, slots=True, eq=False)
class WalkOrigin:
    """*Which* entry into the kernel a result and its projections came from.

    Criterion 1 asks that the record feeding the score view and the receipt
    view of one request be **the same object (``is``)**, and a frozen result
    that gains folds after the walk cannot be: ``projected`` returns a
    descendant, so the last view and the first hold two records by
    construction (that is criterion 3's own layering — a view receives
    leaves, and a leaf derived after the walk can only arrive as a new
    record).

    This is the object that *can* be identical, and it is the one the
    criterion is actually about.  :func:`walk` mints one per entry into the
    kernel and every descendant carries it unchanged, so "these two
    projections came from one walk" is an ``is`` on a token rather than an
    inference from three field identities.  Two walks mint two tokens and
    fail it; a re-projection does not, and a re-projection is not a second
    engine.

    ``eq=False`` makes identity the only comparison: two entries into the
    kernel are two walks even when every number they produced agrees, which
    is precisely the case the criterion exists to catch.
    """

    sequence: int = field(default_factory=lambda: next(_WALK_SEQUENCE))


@dataclass(frozen=True, slots=True)
class WalkResult:
    """Everything one walk produced, frozen at the moment it finished.

    ``states`` is the kernel's per-participant state list, the same objects the
    walk mutated and not mutable *through this record*, and ``actions`` is the
    exact sequence it consumed, so a receipt row and a score contribution trace
    to the same action rather than to two reconstructions of it.  ``rung`` rides
    along because "which engine priced this" is a property of the result and not
    of the caller's memory of it.

    ``outcomes``, ``grey_health`` and ``timeline_coverage`` are the folds the
    composition made after the kernel returned, empty until it does.  They are
    on the result rather than passed beside it because a view takes exactly
    ``(Program, WalkResult)``, and a number a view publishes that reached it
    by some other route is a number no counter can trace to this walk.

    ``origin`` is which walk this record descends from — see
    :class:`WalkOrigin`.  It is ``compare=False`` because two walks that
    produced identical numbers *are* equal as results and are not the same
    walk, and collapsing those two questions into one operator would make
    the R-05 negative below untypable: the fixture's hand-built second
    record has to be equal to the kernel's and identifiable as a second
    entry, at the same time.
    """

    actions: tuple[SurvivalAction, ...]
    states: tuple
    coverage: tuple
    rung: Rung
    origin: WalkOrigin = field(default_factory=WalkOrigin, compare=False)
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
    # Fail-closed denials the composition collected instead of applying
    # (Renata W Bailout's withheld half, an unreadable self-shield
    # payload).  A denial is a receipt, never a packet: it is folded here
    # so the one receipt view publishes it beside the packets it replaced.
    item_denial_receipts: tuple[Mapping[str, Any], ...] = ()
    objective: ObjectiveFold | None = None

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
    counters: WorkCounterSink | None = None,
) -> WalkResult:
    """Run the kernel exactly once and freeze what it produced.

    ``counters`` counts entries, which is what says a composition did not enter
    the one walk twice per pass; the single call expression in ``src/`` only
    says a second engine has not been written.  It is ``None`` outside an
    instrumented search, so the cost with no sink is one ``is None``.  Nothing
    here reorders or filters: the caller has already applied the compiler's
    eight-element sort key, and a second rule is how two engines come to
    disagree about simultaneous events.  :func:`survival_folds` and
    ``finalize_states`` run inside, so a view receives settled leaves.
    """
    record_walk(counters)
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
    record_field.name
    for record_field in fields(WalkResult)
    if record_field.name
    not in {
        "actions",
        "states",
        "coverage",
        "rung",
        # Not a fold: the walk's identity.  A composition that could re-mint
        # it through ``projected`` could launder a second walk into looking
        # like a projection of the first, which is the one thing the token
        # exists to make impossible.
        "origin",
        "duration",
        "survival",
    }
)

# The folds that are sequences.  Frozen means frozen: a list handed in here
# would leave the "result" mutable through the caller's own variable, which is
# the one thing freezing it was for.
_SEQUENCE_FOLDS = frozenset(
    {
        "outcomes",
        "damage_events",
        "healing_events",
        "support_events",
        "item_denial_receipts",
    }
)

__all__ = [
    "AttackerOutcome",
    "ObjectiveFold",
    "SurvivalFold",
    "WalkResult",
    "survival_folds",
    "walk",
]
