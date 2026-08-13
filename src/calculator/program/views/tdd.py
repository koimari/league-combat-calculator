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

from typing import Any

from ..build import Program
from ..precision import round_field
from ..walk import WalkResult
from . import LeafWriter, ViewTag
from .survival import survival_leaves

__all__ = ["tdd", "tdd_leaves"]


def tdd_leaves(
    program: Program, result: WalkResult, writer: LeafWriter
) -> dict[str, Any]:
    """The objective block, with every numeric leaf written through *writer*.

    Split from :func:`tdd` so the receipt payload can carry one
    ``dispositions`` map across all of its blocks rather than one map per
    block: the writer is the payload's, the leaves are this view's.
    """
    fold = result.objective
    rows = survival_leaves(program, result, writer, "participants.survival")
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
    block["surviving_main_team"] = int(fold.surviving_main_team)
    block["focus_participant_id"] = program.focus
    leaf.measured(
        "focus_damage_before_death",
        round_field(
            "objective.focus_damage_before_death", fold.focus_damage_before_death
        ),
        ViewTag.APPLIED,
    )
    block["focus_survival"] = rows.get(program.focus)
    leaf.measured(
        "focus_support_value",
        round_field("objective.focus_support_value", fold.focus_support_value),
        ViewTag.APPLIED,
    )
    block["focus_utility_outcomes"] = result.utility_by_actor.get(program.focus, {})
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
    """
    writer = LeafWriter()
    block = tdd_leaves(program, result, writer)
    return {**block, "dispositions": writer.entries()}
