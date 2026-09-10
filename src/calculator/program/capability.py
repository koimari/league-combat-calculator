"""What each declared mechanic's engine lanes say a view may show."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType
from typing import Any

from ..item_behavior import Compilability, Compilable, EngineLane
from ..trigger_stream import (
    CAPABILITIES,
    SELF_SCOPED_DELIVERIES,
    Engine,
    HolderPacket,
    HolderStacking,
    packet_source_literal,
)
from .identity import MechanicId
from .tagged import tag_for
from .views.view_tag import ViewTag


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


def _rows_previewing(
    result_breakdown: Mapping[str, Any], mechanics: frozenset[str]
) -> frozenset[str]:
    """The breakdown rows stamped as previews of one of *mechanics*."""
    if not mechanics:
        return frozenset()
    return frozenset(
        source
        for source, entry in result_breakdown.items()
        if isinstance(entry, Mapping) and entry.get("pair_preview_of") in mechanics
    )


def pair_preview_sources(result_breakdown: Mapping[str, Any]) -> frozenset[str]:
    """Which of one pair fight's breakdown rows are previews, not deliveries."""
    return _rows_previewing(result_breakdown, pair_preview_mechanics())


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
    return _rows_previewing(result_breakdown, dropped_preview_mechanics())


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
