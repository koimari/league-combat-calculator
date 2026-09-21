"""The fight inputs every cross-participant packet block reads, resolved once."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .ally_packet_shape import _allies, _item_names, _producer
from .interpreters.ally_packet import AllyPacketSlot, resolve_slots
from .item_behavior import AllyProducer
from .roster_composition import Combatant
from .support_event_view import _bus_streams, _support_triggers, require_event_view
from .trigger_stream import Trigger


@dataclass(frozen=True)
class SupportCtx:
    """One fight's cross-participant inputs, resolved once for every block.

    Each bus stream is read once and every block is handed the same view, so
    two blocks cannot disagree about what the fight was.
    """

    attacker: Combatant
    result: Mapping[str, Any]
    all_actors: list[Combatant]
    names: set[str]
    allies: list[Combatant]
    triggers: list[Mapping[str, Any]]
    cc_events: list[Trigger]
    damage_events: list[Trigger]
    takedown_events: list[Trigger]
    slots: Mapping[AllyProducer, tuple[AllyPacketSlot, ...]]

    def producer(self, mechanic: AllyProducer) -> AllyPacketSlot | None:
        """This build's one holder of *mechanic*, or ``None``."""
        return _producer(self.slots, mechanic)


@dataclass(frozen=True)
class _TriggerMoment:
    """One authored heal or shield, and the ally it landed on."""

    ctx: SupportCtx
    trigger: Mapping[str, Any]
    target: Combatant
    time: float


@dataclass(frozen=True)
class _ControlMoment:
    """One authored crowd-control mark, and when it landed."""

    ctx: SupportCtx
    cc: Trigger
    time: float


def _context(
    attacker: Combatant,
    result: Mapping[str, Any],
    all_actors: list[Combatant],
    trigger_effects: Iterable[Mapping[str, Any]],
) -> SupportCtx:
    """Read the roster, the bus streams and the declarations, once."""
    names = _item_names(attacker)
    require_event_view(result, names)
    cc_events, damage_events, takedown_events = _bus_streams(result, names)
    return SupportCtx(
        attacker=attacker,
        result=result,
        all_actors=all_actors,
        names=names,
        allies=_allies(attacker, all_actors),
        triggers=_support_triggers(trigger_effects, attacker),
        cc_events=cc_events,
        damage_events=damage_events,
        takedown_events=takedown_events,
        slots=resolve_slots(names),
    )
