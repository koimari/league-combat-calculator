"""The TDD view — total damage dealt, and what it cost the other side.

"TDD" is the calculator's word for outgoing damage that actually landed, and
the objective block is where a request's TDD is summarised: each team's damage
before death, each team's effective health, the focused participant's own
damage, support and healing.  It was assembled inline at the bottom of the
receipt composition, ten aggregates deep inside a return literal, which is
where a total quietly counting a member it should not have counted is least
visible.

Every number here carries :data:`~. .ViewTag.APPLIED`, and that is a claim
rather than a default.  ``THEORETICAL`` is the pair engine's own preview --
what one attacker versus one defender *would* have produced -- and D-62
forbids folding it into a coupled total, so a pair-authored preview does not
reach this block at all.  The tag is published beside every leaf through the
``dispositions`` map so a consumer can see which of the two it is holding
instead of inferring it from where the number came from.

Nothing here folds.  The ten aggregates are summed once by the composition
into :class:`~..walk.ObjectiveFold` and re-rounded here at their declared
precisions -- a view that summed would be a second producer of the total it
claims to project.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..build import Program
from ..precision import round_field
from ..walk import WalkResult
from . import DISCARD, LeafWriter, ViewTag
from .survival import participant_paths, survival_leaves

__all__ = ["tdd", "tdd_leaves"]


def tdd_leaves(
    program: Program,
    result: WalkResult,
    writer: LeafWriter,
    rows: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """The objective block, with every numeric leaf written through *writer*.

    Split from :func:`tdd` so the receipt payload can carry one
    ``dispositions`` map across all of its blocks rather than one map per
    block: the writer is the payload's, the leaves are this view's.

    ``rows`` are the survival rows the payload already published.  They
    arrive rather than being re-projected: this block *republishes* the
    focused participant's row at a second path, and a republication is a
    second place a number lives, not a second time it is computed.
    """
    fold = result.objective
    block: dict[str, Any] = {}
    leaf = writer.block(block, "objective")
    leaf.measured(
        "main_team_damage_before_death",
        round_field(
            "objective.main_team_damage_before_death",
            fold.main_team_damage_before_death,
        ),
        ViewTag.APPLIED,
    )
    leaf.measured(
        "enemy_team_damage_before_death",
        round_field(
            "objective.enemy_team_damage_before_death",
            fold.enemy_team_damage_before_death,
        ),
        ViewTag.APPLIED,
    )
    leaf.raw("surviving_main_team", int(fold.surviving_main_team))
    leaf.raw("focus_participant_id", program.focus)
    leaf.measured(
        "focus_damage_before_death",
        round_field(
            "objective.focus_damage_before_death", fold.focus_damage_before_death
        ),
        ViewTag.APPLIED,
    )
    leaf.structure("focus_survival", rows.get(program.focus))
    leaf.measured(
        "focus_support_value",
        round_field("objective.focus_support_value", fold.focus_support_value),
        ViewTag.APPLIED,
    )
    leaf.structure(
        "focus_utility_outcomes", result.utility_by_actor.get(program.focus, {})
    )
    leaf.measured(
        "focus_healing",
        round_field("objective.focus_healing", fold.focus_healing),
        ViewTag.APPLIED,
    )
    leaf.measured(
        "main_team_effective_health",
        round_field(
            "objective.main_team_effective_health", fold.main_team_effective_health
        ),
        ViewTag.APPLIED,
    )
    leaf.measured(
        "enemy_team_effective_health",
        round_field(
            "objective.enemy_team_effective_health", fold.enemy_team_effective_health
        ),
        ViewTag.APPLIED,
    )
    leaf.measured(
        "total_support_value",
        round_field("objective.total_support_value", fold.total_support_value),
        ViewTag.APPLIED,
    )
    leaf.measured(
        "total_healing_reduced",
        round_field("objective.total_healing_reduced", fold.total_healing_reduced),
        ViewTag.APPLIED,
    )
    return block


def tdd(program: Program, result: WalkResult) -> dict[str, Any]:
    """The objective block on its own, with its own ``dispositions`` map.

    The receipt payload uses :func:`tdd_leaves` instead, because one payload
    carries one map.  This entry point is the view's own front door and the
    shape criterion 3 checks: exactly ``(Program, WalkResult)`` in, published
    leaves out, no arithmetic in between.

    The survival rows the objective republishes are projected through
    ``DISCARD``: this payload publishes them only under ``focus_survival``,
    so entries at ``participants[i].survival`` would name leaves this payload
    does not have -- the ghost half of criterion 5's two-way equality.
    """
    writer = LeafWriter()
    rows = survival_leaves(program, result, DISCARD, participant_paths(program))
    block = tdd_leaves(program, result, writer, rows)
    return {**block, "dispositions": writer.entries()}
