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

from . import DISCARD
from .breakdown import breakdown_leaves
from .survival import survival_leaves

__all__ = ["score"]


def score(program: Any, result: Any) -> dict[str, Any]:
    """Project one walk into the payload a candidate is scored from.

    Both composition paths return exactly this, which is what makes "the
    compiled score path reproduces the receipt walk's numbers" a statement
    about one function rather than about two that have to be compared.
    """
    # No ``dispositions`` map: this payload is compared and thrown away
    # thousands of times per search and is never serialized to anybody.  The
    # published score surfaces -- ``/api/bis`` and ``/api/optimize`` -- build
    # their own map over the leaves they actually publish.  ``DISCARD`` says
    # that in one word instead of leaving it to a reader to notice.
    writer = DISCARD
    rows = survival_leaves(program, result, writer, "participants.survival")
    return {
        "duration": float(result.duration),
        "participants": [
            {
                "participant_id": actor.participant_id,
                "team": actor.team,
                "champion": actor.champion_data.get("name", ""),
                "level": actor.level,
                "survival": rows[actor.participant_id],
            }
            for actor in program.actors
        ],
        "breakdown": breakdown_leaves(program, result, writer),
        "timeline_coverage": result.timeline_coverage,
    }
