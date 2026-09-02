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

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import MappingProxyType
from typing import Any

from ..ability_spec import Quantity
from ..item_behavior import Compilability, Compilable, EngineLane
from ..survival.actions import TransitionRank
from ..trigger_stream import (
    CAPABILITIES,
    SELF_SCOPED_DELIVERIES,
    Engine,
    HolderPacket,
    HolderStacking,
    packet_source_literal,
)
from .events import PairEvent, RoutedEvent, payload_from_packet, riders_from_packet
from .identity import EventId, MechanicId, PairOrigin, PIdx
from .route import PairDefender, RouteContext, resolve_route
from .views import UnrankableNumber, ViewTag


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


class MixedViewFold(TypeError):
    """Two numbers meaning different things were added together.

    A ``TypeError`` and not a ``ValueError``, because the operands are not
    the same *kind* of number: one is what the coupled walk delivered and the
    other is what a single pair fight would have produced.  Their sum is not
    a wrong total, it is not a total.
    """

    def __init__(self, left: ViewTag, right: ViewTag) -> None:
        """Name both meanings, because the fix depends on which is wrong."""
        super().__init__(
            f"a {left.value} quantity may not be folded with a {right.value} "
            "one; a sum may never mix views (D-62)"
        )
        self.left = left
        self.right = right


@dataclass(frozen=True, slots=True)
class Tagged:
    """A quantity and what it means — the only thing a fold may add.

    ``Quantity.__add__`` (D-72) propagates *dispositions* through a sum: a
    withheld member makes the total withheld, a structural zero folds as
    zero.  It says nothing about views, because a disposition answers "did a
    rule produce this" and a tag answers "which engine's answer is it".  Both
    have to survive a sum, and the second is the one Imperial Mandate got
    wrong: the pair engine's preview and the coupled walk's delivery are both
    ``MEASURED``, both real, and adding them counts the mechanic twice.

    So the tag rides the quantity through the algebra, and a fold of two
    different tags raises rather than producing a number.  That is what
    "folding differently-tagged sources is a construction error" means:
    unrepresentable, not merely tested for.
    """

    quantity: Quantity
    tag: ViewTag

    def __add__(self, other: object) -> Tagged:
        """Fold two quantities that mean the same thing, or refuse."""
        if not isinstance(other, Tagged):
            return NotImplemented
        if other.tag is not self.tag:
            raise MixedViewFold(self.tag, other.tag)
        return Tagged(quantity=self.quantity + other.quantity, tag=self.tag)


def fold_tagged(parts: Iterable[Tagged]) -> Tagged:
    """Add every part, propagating both the disposition and the view.

    Raises:
        MixedViewFold: two parts carry different tags.
        ValueError: there are no parts.  An empty fold has no view to carry,
            and answering ``Measured(0.0)`` would invent one -- which is the
            zero-versus-absent confusion the whole campaign is about, at the
            aggregate.
    """
    total: Tagged | None = None
    for part in parts:
        total = part if total is None else total + part
    if total is None:
        raise ValueError(
            "an empty fold has no view tag to carry; a total over nothing is "
            "not a measured zero"
        )
    return total


def ranked_total(parts: Iterable[Tagged], *, surface: str) -> float:
    """Fold parts into the number a ranking reads, or refuse to produce one.

    A total folded entirely from previews is well-typed and still not a score.
    """
    total = fold_tagged(parts)
    if total.tag is not ViewTag.APPLIED:
        raise UnrankableNumber(surface, f"a {total.tag.value} total", ["<fold>"])
    return total.quantity.read()


def tag_for(view_tags: Mapping[EngineLane, ViewTag], lane: EngineLane) -> ViewTag:
    """What a declared mechanic's number means in *lane*, or a named refusal.

    Raises rather than defaulting: a lane nobody declared a tag for has no
    declared meaning, and answering ``APPLIED`` there is how a pair-authored
    preview gets summed into a coupled total with no symptom.  Both readers go
    through it, so "what does this number mean" has one implementation.
    """
    try:
        return view_tags[lane]
    except KeyError:
        raise KeyError(
            f"no view tag is declared for {lane.value}; a number with no "
            "declared meaning may not be folded into a total"
        ) from None


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
        """What this mechanic's number means in *lane*, or a named refusal."""
        return tag_for(self.view_tags, lane)


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

        The reason is the fallback receipt's own sentence, so a rung can name the
        declaration that forced it rather than reporting a slow path with no cause.
        """
        return tuple(
            (mechanic, view.compilability.reason)
            for mechanic, view in sorted(self.mechanics.items())
            if not isinstance(view.compilability, Compilable)
        )


#: How one declared engine half widens into the lanes that read its numbers.
#: A pair half is read by the pair engine; a walk half is read by both walks,
#: which is the widening ``program/`` owns -- the bus may not name
#: ``EngineLane`` at all, because that enum's home opens ``data/`` at import
#: and the bus is a leaf that may not (D-35).
_LANES_OF: Mapping[Engine, tuple[EngineLane, ...]] = MappingProxyType(
    {
        Engine.PAIR: (EngineLane.PAIR_ENGINE,),
        Engine.WALK: (EngineLane.RECEIPT_WALK, EngineLane.COMPILED_SCORE_WALK),
    }
)


@cache
def declared_view_tags() -> Mapping[MechanicId, Mapping[EngineLane, ViewTag]]:
    """The live registry's tags, per mechanic, widened to the reading lanes.

    A mechanic's two engine halves are two capability rows and one answer:
    the tags merge into a single ``(lane -> tag)`` mapping, which is what
    makes :func:`tag_for` *total* over the lanes a mechanic is read by rather
    than a lookup into whichever half a caller happened to hold.  Two rows
    declaring the same ``(mechanic, lane)`` differently raise here, at the
    first read, instead of resolving to whichever was iterated last.

    Cached because the registry is frozen at import.
    """
    tags: dict[MechanicId, dict[EngineLane, ViewTag]] = {}
    for capability in CAPABILITIES.values():
        declared = tags.setdefault(MechanicId(capability.mechanic), {})
        for engine, tag in capability.view_tags.items():
            for lane in _LANES_OF[engine]:
                if declared.setdefault(lane, tag) is not tag:
                    raise ValueError(
                        f"{capability.mechanic!r} declares two tags for "
                        f"{lane.value}: {declared[lane].value} and "
                        f"{tag.value}; a number with two declared meanings "
                        "may not be folded into a total"
                    )
    return MappingProxyType(
        {mechanic: MappingProxyType(declared) for mechanic, declared in tags.items()}
    )


@cache
def pair_preview_mechanics() -> frozenset[str]:
    """Mechanics whose pair-engine number is a preview, never a delivery.

    A ``THEORETICAL`` pair half is what one attacker-versus-one-defender fight
    *would* have produced.  The coupled walk owns the real number, so summing
    the preview into a roster total is a double count with no symptom.

    Both spellings of the mechanic are in the set: the pair half's own id and
    the walk half that names it through ``pair_of``.  The pair engine stamps its
    rows with whichever id its declared rule carries, and a join that knew only
    one would silently stop excluding the day a rule was renamed to the other.
    """
    previewed: set[str] = set()
    for mechanic, declared in declared_view_tags().items():
        if EngineLane.PAIR_ENGINE not in declared:
            continue
        if tag_for(declared, EngineLane.PAIR_ENGINE) is not ViewTag.THEORETICAL:
            continue
        previewed.add(str(mechanic))
        previewed.update(
            walk.mechanic for walk in CAPABILITIES.values() if walk.pair_of == mechanic
        )
    return frozenset(previewed)


def pair_preview_sources(result_breakdown: Mapping[str, Any]) -> frozenset[str]:
    """Which of one pair fight's breakdown rows are previews, not deliveries.

    The join has two declared halves: the pair engine stamps each row it authors
    with the mechanic that rule belongs to (``pair_preview_of``), and the
    capability registry says whether that mechanic's pair-lane number is
    ``THEORETICAL``.  One home, because a roster composes a pair fight in two
    places and two copies would answer identically until one was not updated.
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
def walk_repriced_mechanics() -> frozenset[str]:
    """Previewed mechanics whose packet the walk re-prices instead of dropping.

    A ``THEORETICAL`` pair row says the coupled walk owns the number, not *how*
    the walk gets one, and the two answers need opposite treatment of the pair
    engine's own event.  A **rider-delivered** walk half amplifies an event the
    walk already carries, so the preview's event is a second copy and is dropped
    (Shadowflame's Cinderbloom).  A :class:`~..trigger_stream.HolderPacket` half
    prices *this* packet, so the engine's event survives as the packet being
    re-priced and only its **number** leaves the roster total.

    The delivery shape is the whole rule, read off the declaration.  Cached
    because the registry is frozen at import.
    """
    previews = pair_preview_mechanics()
    if not previews:
        return frozenset()
    repriced: set[str] = set()
    for capability in CAPABILITIES.values():
        if capability.engine is not Engine.WALK:
            continue
        if not isinstance(capability.packet_source, HolderPacket):
            continue
        repriced.add(capability.mechanic)
        if capability.pair_of is not None:
            repriced.add(capability.pair_of)
    return frozenset(repriced) & previews


@cache
def dropped_preview_mechanics() -> frozenset[str]:
    """Every previewed mechanic minus the ones the walk re-prices."""
    return pair_preview_mechanics() - walk_repriced_mechanics()


def dropped_pair_previews(result_breakdown: Mapping[str, Any]) -> frozenset[str]:
    """The preview rows of one pair fight a roster composition leaves out."""
    dropped = dropped_preview_mechanics()
    if not dropped:
        return frozenset()
    return frozenset(
        source
        for source, entry in result_breakdown.items()
        if isinstance(entry, Mapping) and entry.get("pair_preview_of") in dropped
    )


@cache
def arming_stacking() -> Mapping[str, tuple[MechanicId, HolderStacking]]:
    """Packet source -> the mechanic it arms, and how a second holder stacks.

    Derived from the declaration rather than tabulated beside it: a walk half's
    ``packet_source`` is the literal its packets carry, so a mechanic that
    renames its packet stops resolving here instead of quietly arming under a
    key nothing recognises.  Only dual-sided halves appear, because only they
    declare a :class:`~..trigger_stream.HolderStacking`, and a packet whose
    source is absent is admitted without a dedupe key ever being built.  A
    **self-scoped** delivery stays out by the shape of its declaration: it arms
    no modifier on a subject a second holder could collide with.  Cached because
    the registry is frozen at import.
    """
    return MappingProxyType(
        {
            source: (
                MechanicId(capability.mechanic),
                capability.holder_stacking,
            )
            for capability in CAPABILITIES.values()
            if capability.holder_stacking is not None
            and not isinstance(capability.packet_source, SELF_SCOPED_DELIVERIES)
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

    ``actors`` is the roster those participant ids stand for, index-aligned
    with ``participants`` and validated as such.  It exists because S9's five
    views take exactly ``(Program, WalkResult)``: what happened and to whom is
    the program's question, and "whom" is a champion at a level holding items,
    not only a string.  Two id lists that could disagree would be the same
    kept-in-step-by-hand arrangement one layer down, so there is one list and
    the other is derived from it at construction.  It defaults to empty for
    the compile-time programs :func:`build_program` produces, which route by
    index and never publish a row.
    """

    participants: tuple[str, ...]
    events: tuple[RoutedEvent, ...]
    pass_index: int = 0
    patch: ParamPatch | None = None
    actors: tuple[Any, ...] = ()
    focus: str = ""

    def __post_init__(self) -> None:
        """A roster that disagrees with its own id list is not one."""
        if self.actors and len(self.actors) != len(self.participants):
            raise ValueError(
                "program actors and participants must be index-aligned: "
                f"{len(self.actors)} actors against {len(self.participants)} ids"
            )
        for index, actor in enumerate(self.actors):
            if actor.participant_id != self.participants[index]:
                raise ValueError(
                    "program actor "
                    f"{actor.participant_id!r} sits at slot {index}, which the "
                    f"participant list calls {self.participants[index]!r}"
                )

    def roster_size(self) -> int:
        """How many participants the program's roster indices are bounded by."""
        return len(self.participants)


def roster_program(
    actors: Sequence[Any],
    *,
    pass_index: int = 0,
    patch: ParamPatch | None = None,
    focus: str = "",
) -> Program:
    """The program one composition pass walks, named by its roster.

    The events are empty and that emptiness is a **statement**: the composition
    authors its transitions as engine packets and compiles them straight to
    ``SurvivalAction`` through ``WalkCompiler``, so no logical event list exists
    for those passes.  A reconstructed list would be a second authoring of the
    fight.  The views read the roster and the walk result, pinned by a test.
    """
    return Program(
        participants=tuple(str(actor.participant_id) for actor in actors),
        events=(),
        pass_index=pass_index,
        patch=patch,
        actors=tuple(actors),
        focus=focus,
    )


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
            routed.extend(
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
                for subject in resolve_route(event.route, ctx, roster_size=len(roster))
            )
    return Program(
        participants=roster,
        events=tuple(routed),
        pass_index=pass_index,
        patch=patch,
    )


__all__ = [
    "CapabilityView",
    "DerivationCycle",
    "MechanicView",
    "MixedViewFold",
    "PairProgram",
    "ParamPatch",
    "Program",
    "Projection",
    "Tagged",
    "build_program",
    "declared_view_tags",
    "derivation_order",
    "dropped_pair_previews",
    "dropped_preview_mechanics",
    "fold_tagged",
    "pair_preview_mechanics",
    "pair_preview_sources",
    "pair_program",
    "ranked_total",
    "roster_program",
    "tag_for",
    "walk_repriced_mechanics",
]
