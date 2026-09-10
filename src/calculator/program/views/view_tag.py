"""Whether a published number was delivered or previewed, and the refusal of ranking a preview."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class ViewTag(Enum):
    """Whether a serialized number was *delivered* or merely *previewed*.

    Two members, and "requested" is deliberately not a third.  The ladder is
    requested -> priced -> applied: a request is a program node carrying no
    number and therefore nothing to tag, ``THEORETICAL`` is the pair
    engine's pre-coupling authoring of a number that one attacker-versus-one
    -defender fight would have produced, and ``APPLIED`` is what the coupled
    walk actually delivered against the roster.  Tagging a non-number would
    re-open the zero-versus-absent confusion this campaign exists to close.

    The distinction is load-bearing rather than descriptive.  Imperial
    Mandate's Command is priced twice today -- once pair-side as a preview
    and once by the walk -- and summing the two is a double count with no
    symptom.  So a sum may never mix tags, ``THEORETICAL`` is never an
    optimizer objective and never feeds BIS, and at most one ``APPLIED``
    contribution may exist for one ``(mechanic, subject, event_id)`` across
    every producer (D-62).
    """

    THEORETICAL = "theoretical"
    APPLIED = "applied"


class UnrankableNumber(TypeError):
    """A number the surfaces that pick a winner may not fold into a score.

    D-62's second half — ``THEORETICAL`` is never an optimizer objective and
    never feeds BIS — as a refusal rather than as a review note.  A preview
    is what one attacker-versus-one-defender fight *would* have produced;
    ranking builds by it means ranking by a number no roster delivered, and
    the failure has no symptom because a preview is a perfectly ordinary
    ``MEASURED`` float.

    A ``TypeError`` for two reasons.  :class:`~..build.MixedViewFold`'s: the
    operand is not the right *kind* of number, so its sum is not a wrong
    total but not a total.  And an operational one — ``bis`` wraps each
    candidate in ``except (KeyError, ValueError)`` and turns what it catches
    into a withheld row.  A previewed number is not a bad candidate to drop
    with a receipt; it is the payload meaning something other than what the
    ranking assumed, and being swallowed into ``candidate_loadout_
    unavailable`` would be this rule failing in exactly the shape it exists
    to stop.
    """

    def __init__(self, surface: str, reason: str, paths: Sequence[str]) -> None:
        """Name the surface, what it refused, and the leaves that caused it.

        Assigned, not handed to ``TypeError.__init__``: the audit reads this.
        """
        self.surface = surface
        self.reason = reason
        self.paths = tuple(paths)
        self.args = (f"{surface} may not rank {reason}: {sorted(paths)}",)
