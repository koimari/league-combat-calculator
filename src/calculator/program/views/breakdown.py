"""The breakdown view — one published row per attacker, and nothing else.

Two composition tails built this list, side by side, and they had to agree
field for field, key order and all: the compiled score path assembled it from
the score ledger's parallel arrays, the receipt path from its annotated event
streams.  They were kept in step by hand.  That is the arrangement the
Imperial Mandate incident came out of, one layer up from where it happened.

This module is the one home.  The two paths still derive their numbers
differently -- and legitimately so, since one reads a ledger and the other
sums a stream -- but each hands the *result* to
:class:`~..walk.AttackerOutcome`, and the row shape, the key order and the
precisions are decided here once.  A field added to a published row is now a
line in one function rather than a line in two that a reviewer has to notice
is missing from the second.

Nothing here folds.  Every number below is either a leaf already on the
outcome record or a leaf already on the survival row, re-rounded at its
declared precision; the two sums that used to sit inline (``incoming_damage``
and the per-attacker total) are folded by the composition, because a view
that adds is a view that can disagree with the walk it claims to project.
"""

from __future__ import annotations

from typing import Any

from ..build import Program
from ..precision import round_field
from ..walk import WalkResult
from . import LeafWriter

__all__ = ["breakdown", "breakdown_leaves"]


def breakdown_leaves(
    program: Program,
    result: WalkResult,
    writer: LeafWriter,
    prefix: str = "breakdown",
) -> list[dict[str, Any]]:
    """Project the walk into the published per-attacker rows.

    ``result.outcomes`` is index-aligned with ``program.actors``.  The
    identity strings come off the outcome and not off the roster, which is a
    preserved defect named on :class:`~..walk.AttackerOutcome`: the receipt
    path fills them inside its attacker loop, so a participant who dealt no
    damage is published with an empty champion, and a pure stage may not
    correct that on its way past.

    ``utility_outcomes`` is present only when the composition folded one,
    which is exactly the receipt path: the optimizer's score subset never
    displays a timeline, so it carries no utility receipt and the key is
    *absent* rather than empty.  Absence is the statement.
    """
    if len(result.outcomes) != len(program.actors):
        raise ValueError(
            "the walk folded "
            f"{len(result.outcomes)} outcomes for a program of "
            f"{len(program.actors)} participants; a breakdown row with no "
            "participant behind it is a number about nobody"
        )
    rows: list[dict[str, Any]] = []
    for index, outcome in enumerate(result.outcomes):
        row: dict[str, Any] = {}
        leaf = writer.block(row, f"{prefix}[{index}]")
        leaf.raw("participant_id", outcome.participant_id)
        leaf.raw("team", outcome.team)
        leaf.raw("champion", outcome.champion)
        leaf.measured("total_damage", round_field("total_damage", outcome.total_damage))
        leaf.structure("sources", list(outcome.sources))
        leaf.measured(
            "outgoing_damage_before_death",
            round_field("outgoing_damage_before_death", outcome.total_damage),
        )
        leaf.measured(
            "incoming_damage",
            round_field("incoming_damage", outcome.incoming_damage),
        )
        leaf.measured("health_damage", outcome.health_damage)
        leaf.measured("shield_absorbed", outcome.shield_absorbed)
        leaf.measured("effective_health", outcome.effective_health)
        leaf.measured("healing_received", outcome.healing_received)
        leaf.measured("healing_reduced", outcome.healing_reduced)
        leaf.measured("support_shield_received", outcome.support_shield_received)
        leaf.measured(
            "support_value", round_field("support_value", outcome.support_value)
        )
        leaf.measured(
            "healing_output", round_field("healing_output", outcome.healing_output)
        )
        if outcome.utility_outcomes is not None:
            leaf.structure("utility_outcomes", outcome.utility_outcomes)
        leaf.raw("survived_window", bool(outcome.survived_window))
        leaf.optional_measured("death_time", outcome.death_time)
        rows.append(row)
    return rows


def breakdown(program: Program, result: WalkResult) -> list[dict[str, Any]]:
    """The published rows on their own, for a caller that wants only them.

    The payload views call :func:`breakdown_leaves` with the payload's own
    writer, because one payload carries one ``dispositions`` map.  This is the
    view's front door and the shape criterion 3 checks.
    """
    return breakdown_leaves(program, result, LeafWriter())
