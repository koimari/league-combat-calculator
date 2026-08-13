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

**What is not here.**  ``run_passes`` — the driver that walks each pass and
folds the results — is Phase 4 S8's, the stage that de-recurses Catalyst and
owns the fixture proving pass 2 compiled equals pass 2 receipted.  Declaring
its name here with nothing behind it would be the prose-outruns-code shape
this campaign exists to remove; the declaration below is what S8 consumes,
and this sentence is where a reader learns which stage supplies the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
    """

    def __init__(self, dependency: CrossPassDependency, passes_run: int) -> None:
        super().__init__(
            f"{dependency.mechanic!r} still depends on {dependency.reads!r} "
            f"after {passes_run} of {dependency.max_passes} declared passes"
        )
        self.dependency = dependency
        self.passes_run = passes_run


def pass_count(dependencies: Sequence[CrossPassDependency]) -> int:
    """How many passes a roster's declared dependencies require.

    The maximum rather than the sum: passes are shared, so two mechanics each
    needing two passes need two passes and not four.  One pass when nothing
    is declared, which is every roster that holds no Catalyst.
    """
    return max((dep.max_passes for dep in dependencies), default=1)


def patch_for_pass(
    dependency: CrossPassDependency, value: float, pass_index: int
) -> ParamPatch:
    """The parameter patch pass *pass_index* carries for one dependency.

    A patch rather than a mutation, and a named reason rather than a bare
    override: pass 2 differing from pass 1 is a fact a receipt has to be able
    to state, and "the program was rebuilt with different parameters" is not
    a statement anyone can check without knowing which ones.
    """
    return ParamPatch(
        overrides={dependency.reads: value},
        reason=(
            f"{dependency.mechanic} reads {dependency.reads} from the "
            f"previous pass; this is pass {pass_index} of "
            f"{dependency.max_passes}"
        ),
    )


__all__ = [
    "CrossPassDependency",
    "IncompleteDependency",
    "pass_count",
    "patch_for_pass",
]
