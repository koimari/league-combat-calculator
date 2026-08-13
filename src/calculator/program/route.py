"""Who receives an event — resolved once, totally, and fail-closed.

Subject resolution today is a set of scattered scans.  The worst of them is
the coupled walk's first-defender scan: an event that marks "the enemy this
cast hit" is delivered to whichever defender happens to sit first in the
roster, because the rotation is run once per defender and nobody named the
scope of the mark.  That is not a routing decision; it is the absence of one,
and it produces a number no reader can trace back to a rule.

A :data:`RoutePolicy` is that decision, named.  Ten members cover every live
delivery shape, :func:`resolve_route` is **total** over the union — a
policy with no branch raises rather than returning an empty tuple — and an
unresolvable context raises :class:`UnroutableEvent` instead of quietly
delivering to nobody.  An empty result is legal only where a policy's own
docstring says the empty roster is the answer (no teammates, no opponents);
everywhere else emptiness means the context was wrong.

:class:`RouteAnnotation` is the other half.  Twelve labels in the live
support layer read like scopes and are not: they are disclosures a receipt
prints beside a number ("this figure assumes the aura reached every enemy in
range"). ``TODO(issue #142)`` says so in the tree today.  Modelling them as
policies would let a disclosure silently change who gets an event, so they
ride a *resolved* route rather than deciding one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Union

from .identity import PIdx

# ---------------------------------------------------------------------------
# The ten policies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelfOnly:
    """The authoring participant, and nobody else."""


@dataclass(frozen=True, slots=True)
class Holder:
    """The participant holding the item or rune that authored the event.

    Distinct from :class:`SelfOnly` because an ally-authored support packet's
    *author* and its *holder* are the same participant only when the ally is
    the one who owns the effect; a shared aura is authored per subject.
    """


@dataclass(frozen=True, slots=True)
class PairDefender:
    """The single defender of the pair fight this event was priced in.

    The fail-closed answer for an unreviewed crowd-control scope: one cone
    stun is delivered to the defender the rotation was actually run against,
    which is a claim about one fight rather than about the roster.
    """


@dataclass(frozen=True, slots=True)
class AllOpponents:
    """Every participant on the other side, empty roster included."""


@dataclass(frozen=True, slots=True)
class AllTeammates:
    """Every ally except the author."""


@dataclass(frozen=True, slots=True)
class SelfAndAllTeammates:
    """The author and every ally — the ordinary team-wide support shape."""


@dataclass(frozen=True, slots=True)
class OneTeammate:
    """A single named ally, by roster slot."""

    teammate: PIdx


@dataclass(frozen=True, slots=True)
class SelfAndOneTeammate:
    """The author and one named ally — Knight's Vow and its shape-mates."""

    teammate: PIdx


@dataclass(frozen=True, slots=True)
class ExplicitTargets:
    """A tuple the author resolved itself, delivered verbatim.

    The only policy that carries subjects rather than deriving them, and it
    is deliberately not a fallback: an author using it has *already* made the
    routing decision, so the receipt can name where that decision was made.
    """

    targets: tuple[PIdx, ...]


@dataclass(frozen=True, slots=True)
class TriggerTarget:
    """Whoever the triggering event reached.

    The policy that replaces the first-defender scan: the subjects come from
    the trigger, so a mark that hit two enemies routes to two enemies and a
    mark that hit one routes to one — instead of both routing to roster slot
    zero because the scan stopped there.
    """


RoutePolicy = Union[
    SelfOnly,
    Holder,
    PairDefender,
    AllOpponents,
    AllTeammates,
    SelfAndAllTeammates,
    OneTeammate,
    SelfAndOneTeammate,
    ExplicitTargets,
    TriggerTarget,
]

ROUTE_POLICIES: tuple[type, ...] = (
    SelfOnly,
    Holder,
    PairDefender,
    AllOpponents,
    AllTeammates,
    SelfAndAllTeammates,
    OneTeammate,
    SelfAndOneTeammate,
    ExplicitTargets,
    TriggerTarget,
)


# ---------------------------------------------------------------------------
# Annotations — disclosures, not scopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteAnnotation:
    """A disclosure a receipt prints beside a routed number.

    ``label`` is the live support layer's own token so a receipt reads the
    same as it does today; ``reason`` is the sentence that token stood for
    and never wrote down.  An annotation cannot change who receives an
    event — it has no resolution branch — which is exactly the property
    that separates it from a policy.
    """

    label: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """One event's subjects, plus every disclosure that qualifies them."""

    subjects: tuple[PIdx, ...]
    annotations: tuple[RouteAnnotation, ...] = ()


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class UnroutableEvent(ValueError):
    """A policy whose context cannot answer it — a programming error.

    Never a data condition: a context is assembled by the builder from the
    roster it already has, so a missing trigger subject or an out-of-range
    teammate means the builder and the author disagree.  Raising names both
    halves rather than delivering the event to nobody.
    """

    def __init__(self, policy: RoutePolicy, reason: str) -> None:
        super().__init__(f"{type(policy).__name__} cannot be resolved: {reason}")
        self.policy = policy
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RouteContext:
    """Everything subject resolution may read, and nothing it may not.

    Deliberately small: a context that carried the whole roster object would
    let a policy reach a stat, and a routing rule that reads a stat is a
    pricing rule wearing a routing rule's name.  Every field is a roster
    slot or a tuple of them.
    """

    author: PIdx
    holder: PIdx
    pair_defender: PIdx | None = None
    teammates: tuple[PIdx, ...] = ()
    opponents: tuple[PIdx, ...] = ()
    trigger_subjects: tuple[PIdx, ...] = ()
    annotations: tuple[RouteAnnotation, ...] = field(default=())


def _checked(policy: RoutePolicy, subjects: Sequence[PIdx], roster: int) -> tuple:
    """Every subject inside the roster, or an :class:`UnroutableEvent`.

    A negative or over-range slot is the shape a stale index takes, and the
    walk would read it as somebody else's state, so the bound is checked
    here — once, for every policy — rather than at ten call sites.
    """
    for subject in subjects:
        if not 0 <= int(subject) < roster:
            raise UnroutableEvent(
                policy, f"subject {int(subject)} is outside a roster of {roster}"
            )
    return tuple(subjects)


def resolve_route(  # pylint: disable=too-many-return-statements
    policy: RoutePolicy, ctx: RouteContext, *, roster_size: int
) -> tuple[PIdx, ...]:
    """Total, fail-closed subject resolution for item and champion packets.

    ``roster_size`` is a parameter rather than a context field because it is
    a property of the walk, not of the event: a context is built per author
    and the roster it is bounded by is the same for all of them.  A policy
    the union gains without a branch here raises at the bottom, which is
    what makes this function total rather than merely long.
    """
    if isinstance(policy, SelfOnly):
        return _checked(policy, (ctx.author,), roster_size)
    if isinstance(policy, Holder):
        return _checked(policy, (ctx.holder,), roster_size)
    if isinstance(policy, PairDefender):
        if ctx.pair_defender is None:
            raise UnroutableEvent(policy, "the context names no pair defender")
        return _checked(policy, (ctx.pair_defender,), roster_size)
    if isinstance(policy, AllOpponents):
        return _checked(policy, ctx.opponents, roster_size)
    if isinstance(policy, AllTeammates):
        return _checked(policy, ctx.teammates, roster_size)
    if isinstance(policy, SelfAndAllTeammates):
        return _checked(policy, (ctx.author, *ctx.teammates), roster_size)
    if isinstance(policy, OneTeammate):
        return _checked(policy, (policy.teammate,), roster_size)
    if isinstance(policy, SelfAndOneTeammate):
        return _checked(policy, (ctx.author, policy.teammate), roster_size)
    if isinstance(policy, ExplicitTargets):
        return _checked(policy, policy.targets, roster_size)
    if isinstance(policy, TriggerTarget):
        if not ctx.trigger_subjects:
            raise UnroutableEvent(
                policy,
                "the triggering event reached nobody; a mark that hit no "
                "subject routes to no subject rather than to roster slot zero",
            )
        return _checked(policy, ctx.trigger_subjects, roster_size)
    raise TypeError(
        f"{type(policy).__name__} is not a RoutePolicy; the union is closed "
        f"({', '.join(member.__name__ for member in ROUTE_POLICIES)})"
    )


def resolve(
    policy: RoutePolicy, ctx: RouteContext, *, roster_size: int
) -> ResolvedRoute:
    """:func:`resolve_route` plus the context's disclosures, as one record."""
    return ResolvedRoute(
        resolve_route(policy, ctx, roster_size=roster_size), ctx.annotations
    )


__all__ = [
    "ROUTE_POLICIES",
    "AllOpponents",
    "AllTeammates",
    "ExplicitTargets",
    "Holder",
    "OneTeammate",
    "PairDefender",
    "ResolvedRoute",
    "RouteAnnotation",
    "RouteContext",
    "RoutePolicy",
    "SelfAndAllTeammates",
    "SelfAndOneTeammate",
    "SelfOnly",
    "TriggerTarget",
    "UnroutableEvent",
    "resolve",
    "resolve_route",
]
