"""A fight that has to be priced twice, expressed as two passes and not recursion.

Catalyst of Aeons is the live case: its shield is a function of a number the
fight itself produces, so the timeline prices the fight, reads the number, and
prices it again.  Today that second pricing happens by **re-entering
``build_participant_timeline`` from inside itself**, which is why the current
path cannot be represented as one walk: a walk that can call the thing that
called it has no single invocation to count, no single result to project five
views from, and no way to say which pass a receipt row came from.

The shape here removes the recursion without removing the dependency.  A
:class:`CrossPassDependency` declares *how many passes* the mechanic needs and
*what changes between them*, the program is rebuilt per pass from the same
inputs plus a :class:`~.build.ParamPatch`, and the walk is entered once per
pass and never from inside itself.  ``max_passes`` is bounded and declared, so
a dependency that never settles raises :class:`IncompleteDependency` naming
itself rather than recursing until the stack ends.

**The driver's signature is a documented reading of the phase's Shape.**
Shape signs ``run_passes(program, deps, ledger) -> WalkResult``.  That
signature presumes the composition already runs *through* ``Program`` and
``WalkResult``, and it does not yet: the timeline's two legacy walk call
sites are repointed at :func:`~.walk.walk` by S9, not by S8.  A driver
written to that signature on this commit would drive nothing, and Catalyst
would stay recursive behind a function whose name said otherwise — the
prose-outruns-code shape this campaign exists to remove.  So the driver
takes the **pass function** instead: one callable, invoked once per pass,
whose result is either the finished composition or a :class:`PassRequest`.
Every ruled property survives the reading — one invocation per pass, a
rebuild rather than a re-entry, a :class:`~.build.ParamPatch` as the only
difference between passes, and a declared bound that raises — and S9 hands
it a pass function that builds a program and walks it, without the driver
changing shape.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, Union

from .build import ParamPatch
from .identity import MechanicId


@dataclass(frozen=True, slots=True)
class CrossPassDependency:
    """One mechanic whose number depends on a number its own fight produces.

    ``max_passes`` is required and bounded: two, for Catalyst, because the
    second pass reads a total the first produced and the third would read a
    total the second produced, which is a fixpoint nobody has argued
    converges.  A dependency asking for more than it can justify is a
    declaration a reviewer can see, which an unbounded loop is not.

    ``reads`` names the walk result field the later pass consumes, so "what
    does pass 2 know that pass 1 did not" is answerable without reading the
    driver.
    """

    mechanic: MechanicId
    max_passes: int
    reads: str

    def __post_init__(self) -> None:
        """A pass count below two is not a cross-pass dependency at all."""
        if self.max_passes < 2:
            raise ValueError(
                f"{self.mechanic!r} declares max_passes={self.max_passes}; a "
                "cross-pass dependency needs at least two passes, and one "
                "pass is an ordinary mechanic that should not be declared here"
            )
        if not self.reads:
            raise ValueError(
                f"{self.mechanic!r} declares no walk-result field to read; a "
                "second pass that reads nothing from the first is a second "
                "identical pass"
            )


class IncompleteDependency(RuntimeError):
    """A declared dependency the pass budget did not satisfy.

    Replaces the untyped ``ValueError`` the recursive path raises.  Untyped
    is the problem, not the raise: a caller cannot tell "this build needs
    another pass" from "this build is malformed" when both arrive as the
    same exception, so one of them gets caught by a handler written for the
    other.

    ``detail`` carries whatever the *asking* site knows and the declaration
    does not — which participant, which slot, which ledger came back short.
    It rides beside the declaration rather than replacing it, because the
    declaration is what says how many passes were owed and the detail is
    what says why the last one could not use them.
    """

    def __init__(
        self,
        dependency: CrossPassDependency,
        passes_run: int,
        *,
        detail: str | None = None,
    ) -> None:
        message = (
            f"{dependency.mechanic!r} still depends on {dependency.reads!r} "
            f"after {passes_run} of {dependency.max_passes} declared passes"
        )
        super().__init__(f"{message}; {detail}" if detail else message)
        self.dependency = dependency
        self.passes_run = passes_run
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PassRequest:
    """One pass's statement that it cannot finish without another.

    Returned by a pass function rather than raised, because asking for a
    second pass is an ordinary outcome and an exception would make the
    driver's happy path an ``except`` clause.  ``value`` is what the pass
    learned and the next pass consumes — it lands in the next
    :class:`~.build.ParamPatch` under the dependency's declared ``reads``
    field, so "what does pass 2 know that pass 1 did not" has exactly one
    answer and it is written down.
    """

    dependency: CrossPassDependency
    value: Any


_Result = TypeVar("_Result")

#: What a pass function hands back: the finished composition, or a request.
PassOutcome = Union[_Result, PassRequest]

#: One pass, as the driver sees it — given its pass number and the patch it
#: carries, it either finishes or asks for another.
PassFunction = Callable[[int, ParamPatch | None], PassOutcome]


def pass_count(dependencies: Sequence[CrossPassDependency]) -> int:
    """How many passes a roster's declared dependencies require.

    The maximum rather than the sum: passes are shared, so two mechanics each
    needing two passes need two passes and not four.  One pass when nothing
    is declared, which is every roster that holds no Catalyst.
    """
    return max((dep.max_passes for dep in dependencies), default=1)


def patch_for_pass(
    dependency: CrossPassDependency, value: Any, pass_index: int
) -> ParamPatch:
    """The parameter patch pass *pass_index* carries for one dependency.

    A patch rather than a mutation, and a named reason rather than a bare
    override: pass 2 differing from pass 1 is a fact a receipt has to be able
    to state, and "the program was rebuilt with different parameters" is not
    a statement anyone can check without knowing which ones.

    ``value`` is whatever the declaration's ``reads`` field names — a pooled
    float for one mechanic, an ordered per-participant restore ledger for
    Catalyst.  The patch does not interpret it; the pass that declared the
    field is the one that knows its shape.
    """
    return ParamPatch(
        overrides={dependency.reads: value},
        reason=(
            f"{dependency.mechanic} reads {dependency.reads} from the "
            f"previous pass; this is pass {pass_index} of "
            f"{dependency.max_passes}"
        ),
    )


def run_passes(
    run_pass: PassFunction,
    dependencies: Sequence[CrossPassDependency],
) -> Any:
    """Drive one composition across its declared passes and fold the result.

    The loop is the whole design.  ``run_pass`` is called once per pass with
    the pass number and the patch that pass carries — ``None`` for the
    first — and its result is either the finished composition, returned
    untouched, or a :class:`PassRequest`, which buys exactly one more pass.
    Nothing here re-enters ``run_pass`` from inside ``run_pass``: the passes
    are siblings in a loop rather than ancestors on a stack, which is what
    makes "one walk per pass" a countable property instead of a claim about
    a recursion whose depth nobody can see (D-70).

    The budget comes from the declarations and never from the request, so a
    pass asking for a dependency the composition never declared gets a named
    refusal rather than a silent second pass — and a pass that keeps asking
    exhausts a bound rather than a stack.
    """
    declared = set(dependencies)
    budget = pass_count(dependencies)
    patch: ParamPatch | None = None
    # Reaching the raise below requires at least one loop pass to have set
    # this: every other exit from the loop body returns or raises.
    pending: PassRequest = None  # type: ignore[assignment]
    for index in range(1, budget + 1):
        outcome = run_pass(index, patch)
        if not isinstance(outcome, PassRequest):
            return outcome
        if outcome.dependency not in declared:
            raise IncompleteDependency(
                outcome.dependency,
                index,
                detail=(
                    "this composition declares no such cross-pass dependency, "
                    "so the pass budget was never sized for it"
                ),
            )
        pending = outcome
        patch = patch_for_pass(outcome.dependency, outcome.value, index + 1)
    raise IncompleteDependency(pending.dependency, budget)


__all__ = [
    "CrossPassDependency",
    "IncompleteDependency",
    "PassFunction",
    "PassOutcome",
    "PassRequest",
    "pass_count",
    "patch_for_pass",
    "run_passes",
]
