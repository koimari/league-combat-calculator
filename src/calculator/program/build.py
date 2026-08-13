"""The whole fight, frozen, before any representation choice is made.

The Imperial Mandate incident was an event that never reached the compiler:
the emission gate dropped a crowd-control marker before compilation, so the
compiler's fail-closed raise — which exists precisely to catch a transition
the compiled kernel cannot stage — never fired.  A gate that runs *before*
the program is built cannot fail closed, because there is nothing left to
fail on.

So the ordering here is the design.  :func:`build_program` authors every
event the fight contains, routed and ranked, and only then does a
:class:`Projection` decide **which fields the compiler reads** — never which
events exist.  A score-mode program and a receipt-mode program hold the same
events; they differ in what is read off them.  That is what makes "the
optimizer scored a build whose amp it silently dropped" unrepresentable
rather than merely tested-for.

:class:`CapabilityView` is this package's only reader of the shared
capability registry, and it is a frozen projection of values — never
callables and never the live objects.  ``program/`` asks three questions of a
mechanic (can it compile, what does its number mean, does a second holder arm
a second copy), and a view that could reach the rest of the declaration would
grow a fourth by accident.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from functools import cache
from types import MappingProxyType

from ..item_behavior import Compilable, Compilability, EngineLane
from ..survival.actions import TransitionRank
from ..trigger_stream import (
    CAPABILITIES,
    Engine,
    HolderStacking,
    packet_source_literal,
)
from .views import ViewTag
from .events import PairEvent, RoutedEvent, payload_from_packet, riders_from_packet
from .identity import EventId, MechanicId, PairOrigin, PIdx
from .route import PairDefender, RouteContext, RoutePolicy, resolve_route


class Projection(Enum):
    """Which fields the compiler reads off a program.

    Two members, and the docstring is the contract: a projection selects
    *fields*, never *events*.  ``SCORE`` skips the per-event dict enrichment
    the optimizer never reads; ``RECEIPT`` keeps it.  Neither may decide that
    an event does not exist, which is why this enum is consumed by the
    compiler and not by the builder.
    """

    SCORE = "score"
    RECEIPT = "receipt"


@dataclass(frozen=True, slots=True)
class MechanicView:
    """The three facts ``program/`` may ask about one declared mechanic.

    ``view_tags`` is keyed by :class:`~..item_behavior.EngineLane` here and
    by ``trigger_stream.Engine`` on the declaration it projects.  The
    widening is this class's job and not the declaration's: a walk half is
    read by two lanes — the receipt walk and the compiled score walk — and
    the bus cannot name ``EngineLane`` at all, because that enum's home
    opens ``data/`` at import and the bus is a leaf that may not (D-35).
    Widening here is what makes D-62's "exactly one tag per
    ``(mechanic, EngineLane)``" a total function rather than a sentence.
    """

    compilability: Compilability
    view_tags: Mapping[EngineLane, ViewTag]
    holder_stacking: HolderStacking | None

    def tag_for(self, lane: EngineLane) -> ViewTag:
        """What this mechanic's number means in *lane*, or a named refusal.

        Raises rather than defaulting: a lane nobody declared a tag for is a
        lane whose numbers have no declared meaning, and answering
        ``APPLIED`` there is precisely how a pair-authored preview gets
        summed into a coupled total with no symptom (D-62).
        """
        try:
            return self.view_tags[lane]
        except KeyError:
            raise KeyError(
                f"no view tag is declared for {lane.value}; a number with no "
                "declared meaning may not be folded into a total"
            ) from None


@dataclass(frozen=True, slots=True)
class CapabilityView:
    """A frozen projection of the capability registry — values, never callables.

    Built once per request and read many times, so it is a mapping rather
    than a scan.  A mechanic the registry does not declare is *absent*, and
    :meth:`compilability_for` says so by raising: an undeclared mechanic that
    defaulted to compilable is exactly the silent success this campaign
    exists to remove.
    """

    mechanics: Mapping[MechanicId, MechanicView]

    def compilability_for(self, mechanic: MechanicId) -> Compilability:
        """One mechanic's compiled-kernel verdict, or a named refusal."""
        try:
            return self.mechanics[mechanic].compilability
        except KeyError:
            raise KeyError(
                f"{mechanic!r} declares no capability; the compiled lane may "
                "not assume a mechanic it has never heard of is representable"
            ) from None

    def compilable(self) -> bool:
        """Whether every declared mechanic in this view can be compiled."""
        return all(
            isinstance(view.compilability, Compilable)
            for view in self.mechanics.values()
        )

    def refusals(self) -> tuple[tuple[MechanicId, str], ...]:
        """Every mechanic that cannot compile, with the reason it gives.

        The reason is the fallback receipt's own sentence, so a rung can name
        the declaration that forced it rather than reporting a slow path with
        no cause.
        """
        return tuple(
            (mechanic, view.compilability.reason)
            for mechanic, view in sorted(self.mechanics.items())
            if not isinstance(view.compilability, Compilable)
        )

    def lanes_declaring(
        self, tag: ViewTag
    ) -> tuple[tuple[MechanicId, EngineLane], ...]:
        """Every ``(mechanic, lane)`` whose numbers carry *tag*.

        The question a view asks before folding anything: a
        ``THEORETICAL`` pair-authored preview may never be summed into a
        coupled total, and asking the declaration is what makes that a
        lookup rather than a convention.
        """
        return tuple(
            (mechanic, lane)
            for mechanic, view in sorted(self.mechanics.items())
            for lane, declared in sorted(
                view.view_tags.items(), key=lambda e: e[0].value
            )
            if declared is tag
        )


@cache
def pair_preview_mechanics() -> frozenset[str]:
    """Mechanics whose pair-engine number is a preview, never a delivery.

    A ``THEORETICAL`` pair half is what one attacker-versus-one-defender
    fight *would* have produced.  The coupled walk owns the real number, so
    summing the preview into a roster total is a double count with no
    symptom — the exact shape D-62 exists to forbid.

    Both spellings of the mechanic are in the set: the pair half's own id and
    the walk half that names it through ``pair_of``.  The pair engine stamps
    its rows with whichever id its declared rule carries, and a join that
    only knew one of the two would silently stop excluding the day a rule was
    renamed to the other.
    """
    previewed: set[str] = set()
    for capability in CAPABILITIES.values():
        if capability.view_tags.get(Engine.PAIR) is not ViewTag.THEORETICAL:
            continue
        previewed.add(capability.mechanic)
        previewed.update(
            walk.mechanic
            for walk in CAPABILITIES.values()
            if walk.pair_of == capability.mechanic
        )
    return frozenset(previewed)


def pair_preview_sources(result_breakdown: Mapping[str, Any]) -> frozenset[str]:
    """Which of one pair fight's breakdown rows are previews, not deliveries.

    The join has two declared halves and this is where they meet: the pair
    engine stamps each row it authors with the mechanic that rule belongs to
    (``pair_preview_of``), and the capability registry says whether that
    mechanic's pair-lane number is ``THEORETICAL``.  Neither half can decide
    it alone, which is the point — a row that simply stopped being summed
    would be an engine quietly demoting its own number.

    One home, because a roster composes a pair fight in **two** places: the
    receipt path enriches it into event dicts and the score path compiles it
    straight from the engine rows.  Two copies of this question would answer
    it identically until the day one of them was not updated, and the surface
    that picks the optimizer's winner is the one that would go on summing a
    preview with nothing saying so.
    """
    previews = pair_preview_mechanics()
    if not previews:
        return frozenset()
    return frozenset(
        source
        for source, entry in result_breakdown.items()
        if isinstance(entry, Mapping) and entry.get("pair_preview_of") in previews
    )


@cache
def arming_stacking() -> Mapping[str, tuple[MechanicId, HolderStacking]]:
    """Packet source -> the mechanic it arms, and how a second holder stacks.

    Derived from the declaration rather than tabulated beside it: a walk
    half's ``packet_source`` is the literal its packets carry, so a mechanic
    that renames its packet stops resolving here instead of quietly arming
    under a key nothing recognises.  Only dual-sided halves appear, because
    only they declare a :class:`~..trigger_stream.HolderStacking`, and a
    packet whose source is absent from this mapping is admitted without a
    dedupe key ever being built.  The key is read through
    ``packet_source_literal``, so a rider-delivered half — which arms nothing
    and carries a stamp rather than a packet source — stays out by the shape
    of its declaration instead of by a coincidence of dict typing.

    Cached because the composition asks once per support packet and the
    registry is frozen at import.
    """
    return MappingProxyType(
        {
            source: (
                MechanicId(capability.mechanic),
                capability.holder_stacking,
            )
            for capability in CAPABILITIES.values()
            if capability.holder_stacking is not None
            and (source := packet_source_literal(capability)) is not None
        }
    )


@dataclass(frozen=True, slots=True)
class ParamPatch:
    """The per-pass parameter overrides a cross-pass dependency feeds pass 2.

    Frozen, and the **only** way a later pass differs from its predecessor.
    Anything else would make "the program is rebuilt per pass" a claim about
    intent rather than a property: two passes that could differ by an
    un-declared mutation are two programs nobody can diff.
    """

    overrides: Mapping[str, Any]
    reason: str

    def applied_to(self, params: Any) -> dict[str, Any]:
        """The patched parameter fields, as a plain mapping of overrides.

        Returns the overrides rather than a mutated ``params`` object on
        purpose: the caller owns its parameters and a patch that rewrote
        them in place would make pass 1's inputs unrecoverable.
        """
        return {
            field: self.overrides.get(field, getattr(params, field, None))
            for field in self.overrides
        }


@dataclass(frozen=True, slots=True)
class PairProgram:
    """One attacker-versus-one-defender fight, as immutable events."""

    origin: PairOrigin
    events: tuple[PairEvent, ...]


@dataclass(frozen=True, slots=True)
class Program:
    """The whole fight, frozen, routed and ranked.

    ``pass_index`` is a field rather than context because a cross-pass
    dependency rebuilds the program: two passes are two programs, and a
    cache that could not tell them apart would serve pass 1's compiled
    actions for pass 2 and discard the patch that caused it.
    """

    participants: tuple[str, ...]
    events: tuple[RoutedEvent, ...]
    pass_index: int = 0
    patch: ParamPatch | None = None

    def roster_size(self) -> int:
        """How many participants the program's roster indices are bounded by."""
        return len(self.participants)


class DerivationCycle(ValueError):
    """Two mechanics each declared to be priced after the other.

    A cycle is a declaration defect, not a runtime condition: producer order
    is *derived* from the capability graph rather than hand-declared, and a
    hand-declared tier would be a fourth writer on a registry three phases
    already share.  Naming the cycle is what makes deriving it safe.
    """

    def __init__(self, cycle: Sequence[MechanicId]) -> None:
        super().__init__(
            "the capability graph declares a producer cycle: "
            + " -> ".join(str(member) for member in cycle)
        )
        self.cycle = tuple(cycle)


def derivation_order(
    caps: CapabilityView,
    *,
    depends_on: Mapping[MechanicId, Sequence[MechanicId]] | None = None,
) -> tuple[MechanicId, ...]:
    """Producer order, derived from the capability graph rather than declared.

    A stable topological order: mechanics are visited in sorted name order so
    two runs over one registry produce one order, and a cycle raises
    :class:`DerivationCycle` naming its members rather than silently
    dropping one of them.  ``depends_on`` defaults to the empty graph, which
    is what the registry declares today — every mechanic is independent, and
    the sorted order is the whole answer.
    """
    graph: Mapping[MechanicId, Sequence[MechanicId]] = depends_on or {}
    order: list[MechanicId] = []
    state: dict[MechanicId, int] = {}

    def visit(mechanic: MechanicId, path: tuple[MechanicId, ...]) -> None:
        mark = state.get(mechanic, 0)
        if mark == 2:
            return
        if mark == 1:
            raise DerivationCycle((*path, mechanic))
        state[mechanic] = 1
        for parent in sorted(graph.get(mechanic, ())):
            visit(parent, (*path, mechanic))
        state[mechanic] = 2
        order.append(mechanic)

    for mechanic in sorted(caps.mechanics):
        visit(mechanic, ())
    return tuple(order)


def pair_program(
    result: Mapping[str, Any], origin: PairOrigin, caps: CapabilityView
) -> PairProgram:
    """One attacker x defender fight as immutable events.

    ``result`` is one engine result — the same object the trigger bus reads
    authored triggers from, not a new name for it.  Every damage row becomes
    a :class:`~.events.PairEvent` at the damage rank whose id is positional
    (the engine numbers its ledger by position, which is why ``sequence`` is
    required and why the row is rejected without one) and whose route is the
    pair defender, because a pair fight has exactly one.

    ``caps`` is taken and not yet read: the capability-driven fan-out —
    which declared mechanic arms what beside a hit — is Phase 4 S7's, and a
    signature that gained the parameter later would make every call site
    S7's problem too.
    """
    _ = caps
    events: list[PairEvent] = []
    for index, row in enumerate(result.get("damage_events", ())):
        if "sequence" not in row:
            raise ValueError(
                f"{origin.attacker} damage event "
                f"{row.get('source_key', '')!r} has no sequence; the walk's "
                "tie-break order would depend on event-id numbering"
            )
        events.append(
            PairEvent(
                id=EventId(origin, index),
                time=float(row["time"]),
                sequence=int(row["sequence"]),
                rank=TransitionRank.DAMAGE,
                payload=payload_from_packet(row, origin=origin),
                route=PairDefender(),
                riders=riders_from_packet(row),
            )
        )
    return PairProgram(origin=origin, events=tuple(events))


def build_program(
    participants: Sequence[str],
    pairs: Sequence[tuple[PairProgram, PIdx, PIdx]],
    caps: CapabilityView,
    *,
    pass_index: int = 0,
    patch: ParamPatch | None = None,
) -> Program:
    """Every pair fight's events, routed against the roster, as one program.

    ``pairs`` carries each fight beside the roster slots of its attacker and
    defender, because routing is the step that turns "the defender of this
    fight" into an index and the pair program deliberately does not know one.

    ``caps`` is **taken and not yet read**, exactly as :func:`pair_program`
    takes it: this builder routes and ranks authored events, and the
    capability-driven work — the fan-out of what a declared mechanic arms
    beside a hit, and the refusal of a mechanic nobody declared — is S7's.
    Saying so here rather than only at the discard: this module's own header
    calls :class:`CapabilityView` the package's only reader of the registry
    and describes what it refuses, which reads as if the entry point
    consulted it.  It does not, and an inert check that reads as a live one
    is worth one sentence.  The parameter stays because a signature that
    grew it later would make every call site S7's problem too, and
    ``caches.CACHES['program']`` declares it inert with a test that varies it
    and asserts the program does not move — so the day it starts reaching
    the value, the declaration goes red rather than this docstring going
    quietly stale.

    The events come out in authored order and are **not** sorted here: the
    walk's total order is the eight-element sort key the compiler builds, and
    sorting twice by two rules is how two engines end up disagreeing about
    simultaneous events.
    """
    _ = caps
    roster = tuple(str(pid) for pid in participants)
    routed: list[RoutedEvent] = []
    for pair, attacker, defender in pairs:
        ctx = RouteContext(
            author=attacker,
            holder=attacker,
            pair_defender=defender,
            opponents=(defender,),
        )
        for event in pair.events:
            for subject in resolve_route(event.route, ctx, roster_size=len(roster)):
                routed.append(
                    RoutedEvent(
                        id=event.id,
                        subject=subject,
                        source=attacker,
                        time=event.time,
                        sequence=event.sequence,
                        rank=event.rank,
                        payload=event.payload,
                        riders=event.riders,
                    )
                )
    return Program(
        participants=roster,
        events=tuple(routed),
        pass_index=pass_index,
        patch=patch,
    )


def route_policy_of(event: PairEvent) -> RoutePolicy:
    """One authored event's delivery policy — the field, named as a reader.

    Trivial by design: it exists so a consumer asks the program a question
    instead of reaching into the dataclass, which is what keeps the policy
    field from acquiring a second, later reader that disagrees.
    """
    return event.route


__all__ = [
    "CapabilityView",
    "DerivationCycle",
    "MechanicView",
    "PairProgram",
    "ParamPatch",
    "Program",
    "Projection",
    "build_program",
    "derivation_order",
    "pair_program",
    "route_policy_of",
]
