"""The score view — the shape the optimizer and BIS evaluate a candidate in.

``_score_with_search_context`` used to end in about a hundred and fifty lines
that rebuilt this payload from the score ledger, and
``build_participant_timeline``'s ``include_receipt=False`` branch rebuilt the
same payload from the receipt walk.  Both claimed to produce "the exact
score-only receipt the other would produce", and the only thing making that
true was that somebody kept the two bodies matching.  The phase's whole thesis
is that a claim of that shape belongs to the layering rather than to
diligence: score mode and receipt mode agree because there is one projection
and it takes the walk's own result.

So the assembly is deleted rather than mirrored, and this is where it went.

What a score consumer reads is deliberately small -- the survival rows, the
per-attacker breakdown and the ordering receipt -- because nothing ever
displays a candidate's serialized timeline.  That is a *projection* choice and
not a compilation one: both paths walk the same events, and this view reads
fewer fields off the result.  The distinction is the reason the Mandate
incident is unrepresentable here: an event the score path never sees would be
an event the program never held, and the program is built before any
representation choice is made.
"""

from __future__ import annotations

from typing import Any

from ..build import Program
from ..walk import WalkResult
from . import LeafWriter
from .breakdown import breakdown_leaves
from .survival import participant_paths, survival_leaves

__all__ = ["score", "score_leaves"]


def score_leaves(
    program: Program, result: WalkResult, writer: LeafWriter
) -> dict[str, Any]:
    """The scoring payload, with every numeric leaf written through *writer*.

    Split from :func:`score` exactly as the other four views split theirs,
    and for a sharper reason.  The optimizer evaluates thousands of
    candidates per search and shows none of them: a ``dispositions`` map per
    evaluation is a few hundred dict entries on the hot path, measured at
    +19.7% on the S4 allocation probe, which criterion 17 says is never to
    be relaxed.  So that caller passes :data:`~. .DISCARD` and says why at
    its own call site.

    What it may not do is decide for everybody.  The view used to bind
    ``DISCARD`` itself, on the grounds that nobody reads a candidate's
    payload -- and three score-mode coupled scenarios snapshot 133 of its
    numbers each, every one of them carrying no entry at all.  The front
    door below is what a caller that keeps the payload gets, and it takes
    the two inputs criterion 3 gives a view and nothing else.
    """
    payload: dict[str, Any] = {}
    root = writer.block(payload, "")
    rows = survival_leaves(program, result, writer, participant_paths(program))
    root.measured("duration", float(result.duration))
    # The participant row carries no quantity of its own: an id, a team, a
    # champion, an int level and the survival row whose leaves were written
    # above at their own paths.  A block per participant would allocate one
    # object per row per evaluation to make five ``raw`` calls, which write
    # no entry by definition -- so the literal stays a literal.
    root.raw(
        "participants",
        [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "survival": rows[actor.participant_id],
            }
            for actor in program.actors
        ],
    )
    root.raw("breakdown", breakdown_leaves(program, result, writer))
    root.structure("timeline_coverage", result.timeline_coverage)
    if writer.records:
        payload["dispositions"] = writer.entries()
    return payload


def score(program: Program, result: WalkResult) -> dict[str, Any]:
    """Project one walk into the payload a candidate is scored from.

    Both composition paths return exactly this, which is what makes "the
    compiled score path reproduces the receipt walk's numbers" a statement
    about one function rather than about two that have to be compared.

    This is the view's front door and the shape criterion 3 checks: exactly
    ``(Program, WalkResult)`` in, published leaves out -- and, since S9's
    coverage slice, the ``dispositions`` map naming every one of them.
    """
    return score_leaves(program, result, LeafWriter())
