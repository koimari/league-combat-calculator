"""How wide a crowd-control effect reaches — declared, or declared unread.

:mod:`route` names *who* receives an event.  This module names the one input
to that question the tree has never had: how many roster targets a single
cast's crowd control actually applies to.  Nothing answered it, so the answer
fell out of construction — the rotation is run once per defender, the support
scan reads the first of those pair fights, and Imperial Mandate's Command mark
therefore lands on whichever enemy sits first in the roster.  Which enemy a
cone stun marks was decided by roster order and by nothing else.

The umbrella records **H2** as *deferred, default shipped*: the sourced wiki
reading of Syndra E's cone (how many targets, under what cap) is not in, and
the shipped answer until it is, is that an :class:`Unreviewed` scope resolves
to :class:`SingleTarget` on the pair defender **with a disclosure naming the
ability**.  That is a positive construction, not an absence, and this module
is where it is constructed:

* :func:`reviewed_scope` applies the default and returns the disclosure with
  it, so a caller cannot take the routing answer without the sentence that
  qualifies it.
* :func:`scope_policy` maps a *reviewed* scope onto a :mod:`route` policy and
  raises on :class:`Unreviewed` — an unreviewed scope has no policy until the
  default has been applied, which is what keeps "we did not read this" from
  silently becoming "we read this and it is one target".

Answering H2 later is authoring a value here — a :class:`MultiTarget` cap on
the ability that declares it — and not adding a type.  That is the whole
reason the union carries a member nobody declares yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from . import route

# ---------------------------------------------------------------------------
# The three scopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SingleTarget:
    """One subject: the defender this cast's fight was actually resolved against.

    A claim about one fight rather than about the roster, which is why it
    resolves to :class:`route.PairDefender` and not to an opponent scan.
    """


@dataclass(frozen=True, slots=True)
class MultiTarget:
    """Every opponent the cast reaches, up to a sourced cap.

    Declared by nobody today: the cap is exactly what H2 is blocked on.  The
    member exists so that answering H2 is authoring ``MultiTarget(cap=n)`` on
    the ability that earned it, rather than adding a routing concept to a
    union under time pressure.
    """

    cap: int

    def __post_init__(self) -> None:
        if self.cap < 1:
            raise ValueError(
                f"MultiTarget cap must be at least 1, got {self.cap!r}; a scope "
                "that reaches nobody is not a scope, it is a missing trigger"
            )


@dataclass(frozen=True, slots=True)
class Unreviewed:
    """Nobody has read this ability's crowd-control scope.

    Carries the ability it belongs to, because the shipped default's
    disclosure has to name it: a receipt that says "an unreviewed scope was
    assumed single-target" and cannot say *whose* is a disclosure nobody can
    act on.
    """

    ability: str

    def __post_init__(self) -> None:
        if not self.ability.strip():
            raise ValueError(
                "Unreviewed requires the ability that authored the crowd "
                "control; the shipped H2 default's disclosure names it"
            )


CcScope = Union[SingleTarget, MultiTarget, Unreviewed]

CC_SCOPES: tuple[type, ...] = (SingleTarget, MultiTarget, Unreviewed)

UNREVIEWED_SCOPE_LABEL = "cc_scope_unreviewed"


# ---------------------------------------------------------------------------
# H2's shipped default, and the policy a reviewed scope resolves to
# ---------------------------------------------------------------------------


def reviewed_scope(scope: CcScope) -> tuple[CcScope, tuple[route.RouteAnnotation, ...]]:
    """H2's recorded default, applied once and disclosed in the same breath.

    An :class:`Unreviewed` scope reads as :class:`SingleTarget` and carries a
    :class:`route.RouteAnnotation` naming the ability it was assumed for.  Any
    other scope is returned unchanged with no disclosure, because a scope
    somebody read owes the receipt nothing.

    The disclosure and the reading are returned together deliberately: a
    caller that wanted only the routing answer would have to drop the
    annotation on the floor to get it, and that is visible at the call site
    rather than buried in a branch.
    """
    if isinstance(scope, Unreviewed):
        return (
            SingleTarget(),
            (
                route.RouteAnnotation(
                    label=UNREVIEWED_SCOPE_LABEL,
                    reason=(
                        f"{scope.ability} declares no reviewed crowd-control "
                        "scope (H2, deferred with the default shipped), so this "
                        "mark is delivered to the single defender of the pair "
                        "fight it was priced in: a claim about one fight, not "
                        "about the roster."
                    ),
                ),
            ),
        )
    return scope, ()


def scope_policy(scope: CcScope) -> route.RoutePolicy:
    """The :mod:`route` policy a **reviewed** scope resolves to.

    Total over :data:`CC_SCOPES` and fail-closed on :class:`Unreviewed`: an
    unreviewed scope has no policy until :func:`reviewed_scope` has applied
    the recorded default, so reaching here with one means a caller took the
    routing answer without the disclosure that qualifies it.
    """
    if isinstance(scope, SingleTarget):
        return route.PairDefender()
    if isinstance(scope, MultiTarget):
        return route.AllOpponents()
    if isinstance(scope, Unreviewed):
        raise UnscopedCrowdControl(scope)
    raise TypeError(
        f"{type(scope).__name__} is not a CcScope; the union is closed "
        f"({', '.join(member.__name__ for member in CC_SCOPES)})"
    )


class UnscopedCrowdControl(ValueError):
    """An :class:`Unreviewed` scope asked for a policy — a programming error.

    Never a data condition: an unreviewed ability is the *ordinary* case and
    :func:`reviewed_scope` answers it.  Reaching this means a call site read
    the scope and skipped the default, which would deliver the mark with no
    disclosure beside it.
    """

    def __init__(self, scope: Unreviewed) -> None:
        super().__init__(
            f"{scope.ability} has an unreviewed crowd-control scope and no "
            "route policy; call reviewed_scope() first so the shipped H2 "
            "default lands with the disclosure that qualifies it"
        )
        self.scope = scope


__all__ = [
    "CC_SCOPES",
    "UNREVIEWED_SCOPE_LABEL",
    "CcScope",
    "MultiTarget",
    "SingleTarget",
    "Unreviewed",
    "UnscopedCrowdControl",
    "reviewed_scope",
    "scope_policy",
]
