"""The fight-result streams a support packet is priced from, and the refusal when the
view is starved."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import replace
from typing import Any

from .ally_packet_shape import _MISSING, _item_names, _option, _producer, _teammates
from .interpreters.ally_packet import resolve_slots
from .item_behavior import AllyProducer, PacketKind
from .program import route as program_route
from .program.identity import PIdx
from .program.scope import scope_policy
from .roster_composition import Combatant
from .trigger_stream import (
    RAW_STREAMS,
    Trigger,
    TriggerKind,
    authored_triggers,
    streams_for,
    tuple_incapable_items,
)


def _support_triggers(
    trigger_effects: Iterable[Mapping[str, Any]], attacker: Combatant
) -> list[Mapping[str, Any]]:
    """Return ally heal/shield packets that can trigger item passives."""
    return [
        event
        for event in trigger_effects
        if str(event.get("kind", "")) in {"heal", "shield"}
        and str(event.get("target", "")) != attacker.participant_id
    ]


def _cc_event_stream(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The deduplicated damage + control-only event stream.

    Damage-attached control rides ``damage_events``; control-ONLY packets
    (Darius E, Elise E, ...) ride ``control_events``.  The coupled pair
    enrichment merges control-only rows INTO the per-event view, so a
    ``(time, source_key, cc_kind)`` dedupe keeps exactly one copy of every
    packet and never double-fires the same control packet.
    """
    seen: set[tuple[float, str, str]] = set()
    out: list[Mapping[str, Any]] = []
    for stream in (
        result.get("damage_events", ()),
        result.get("control_events", ()),
    ):
        for event in stream:
            if not isinstance(event, Mapping):
                continue
            try:
                event_time = float(event.get("time", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            key = (
                round(event_time, 9),
                str(event.get("source_key", "")),
                str(event.get("cc_kind", "") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(event)
    return out


def _mana_input(
    raw: object,
    *,
    missing_reason: str,
    invalid_reason: str,
) -> tuple[float | None, str | None]:
    """Validate one explicit mana value without inventing a fallback."""
    if raw is _MISSING:
        return None, missing_reason
    if raw is None or isinstance(raw, bool):
        return None, invalid_reason
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, invalid_reason
    if not math.isfinite(value) or value < 0.0:
        return None, invalid_reason
    return value, None


def _stack_triggers(triggers: Iterable[Trigger]) -> Iterator[Trigger]:
    """Non-reactive champion damage that landed on a named target.

    The bus triggers on every authored row; this is the stack ledgers' side.
    """
    for trigger in triggers:
        if trigger.damage <= 0.0 or trigger.reactive or not trigger.target_id:
            continue
        yield trigger


def _current_mana_at(
    result: Mapping[str, Any], event_time: float, initial_current_mana: object
) -> tuple[float | None, str | None]:
    """Resolve current mana from explicit state and ordered cast receipts."""
    current, initial_reason = _mana_input(
        initial_current_mana,
        missing_reason="missing_current_mana",
        invalid_reason="invalid_current_mana",
    )
    casts = result.get("cast_timeline", ())
    if not isinstance(casts, Iterable):
        return current, initial_reason
    ordered = []
    for cast in casts:
        if not isinstance(cast, Mapping):
            continue
        try:
            cast_time = float(cast.get("time", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(cast_time) or cast_time > event_time + 1e-9:
            continue
        ordered.append((cast_time, cast))
    for _, cast in sorted(ordered, key=lambda row: row[0]):
        if "resource_after" not in cast:
            continue
        parsed, reason = _mana_input(
            cast["resource_after"],
            missing_reason="missing_current_mana",
            invalid_reason="invalid_current_mana",
        )
        if reason is not None:
            return None, reason
        current = parsed
        initial_reason = None
    return current, initial_reason


def _target_by_id(all_actors: Iterable[Any], participant_id: str) -> Any | None:
    return next(
        (actor for actor in all_actors if actor.participant_id == participant_id), None
    )


def _cc_ability_label(cc: Trigger, all_actors: Iterable[Any]) -> str:
    """The ability an unreviewed crowd-control scope belongs to, named.

    "Syndra E", not "E": the disclosure exists so a reader can go and take
    the wiki reading H2 is waiting on, and a bare slot letter names no cast.
    The caster is the control row's own ``attacker_id`` — never the packet
    holder, who may be a different participant entirely.
    """
    caster = _target_by_id(all_actors, cc.attacker_id)
    champion = str(
        (getattr(caster, "champion_data", None) or {}).get("name", "")
    ).strip()
    slot = (
        cc.source_key or cc.cc_kind or cc.ability_instance or "an unnamed cast"
    ).strip()
    return f"{champion} {slot}".strip() if champion else slot


def _cc_mark_subjects(
    attacker: Any, cc: Trigger, all_actors: list[Any], scope: Any
) -> tuple[Any, ...]:
    """Who a crowd-control mark reaches — routed, never scanned.

    Two resolutions, in the order the decision is actually made.  The
    ability's reviewed :mod:`program.scope` says how wide the control is and
    therefore *who the trigger reached*; the mark then rides that trigger
    through :class:`program.route.TriggerTarget`, which is what makes a mark
    that hit one enemy route to one and a mark that hit two route to two,
    instead of both routing to roster slot zero.

    An empty tuple is the one data condition: the control row named a
    participant this roster does not hold, so there is nobody to mark.
    Everything else is a programming error and :func:`resolve_route` raises.
    """
    slots = {
        actor.participant_id: PIdx(index) for index, actor in enumerate(all_actors)
    }
    defender = slots.get(cc.target_id)
    author = slots.get(attacker.participant_id)
    if defender is None or author is None:
        return ()
    context = program_route.RouteContext(
        author=author,
        holder=author,
        pair_defender=defender,
        opponents=tuple(
            slots[actor.participant_id]
            for actor in all_actors
            if actor.team != attacker.team
        ),
    )
    reached = program_route.resolve_route(
        scope_policy(scope), context, roster_size=len(all_actors)
    )
    marked = program_route.resolve_route(
        program_route.TriggerTarget(),
        replace(context, trigger_subjects=reached),
        roster_size=len(all_actors),
    )
    return tuple(all_actors[int(subject)] for subject in marked)


def _selected_teammate(attacker: Any, teammates: list[Any], owner: str) -> Any | None:
    """The teammate the holder's scenario tethered, under *owner*'s options."""
    if not teammates:
        return None
    raw_index = _option(attacker, owner, "worthy_target_index", -1.0)
    if float(raw_index) < 0.0:
        # Pledge is unit-targeted: a MISSING authored index means no
        # designation - fail closed instead of inventing the first
        # teammate as Worthy (P3 package 3S).
        return None
    index = max(0, min(len(teammates) - 1, int(raw_index)))
    return teammates[index]


def resolve_knights_vow_tether(
    holder: Combatant, all_actors: Iterable[Combatant]
) -> dict[str, Any] | None:
    """Resolve one Knight's Vow holder's Worthy tether.

    Returns the authored target, the option gates, and the typed Sacrifice
    values, or ``None`` when the holder declares no Sacrifice producer, has
    no eligible teammate, or the authored Worthy index is the no-selection
    sentinel.  Both the receipt scheduler and the compiled score staging
    consume this one resolution so the walks cannot disagree about the
    tether; every number comes back through the declaration's own
    references, so the item is never spelled here.
    """
    sacrifice = _producer(resolve_slots(_item_names(holder)), AllyProducer.SACRIFICE)
    if sacrifice is None:
        return None
    sacrifice.declared(PacketKind.HEAL)
    target = _selected_teammate(
        holder, _teammates(holder, list(all_actors)), sacrifice.owner
    )
    if target is None:
        return None
    return {
        "holder": holder,
        "target": target,
        "redirect_fraction": sacrifice.value("redirect_fraction"),
        "heal_fraction": sacrifice.value("holder_heal_fraction"),
        "within_range": _option(holder, sacrifice.owner, "worthy_within_range", 1.0),
        "holder_health_ready": _option(
            holder, sacrifice.owner, "holder_above_30_percent", 1.0
        ),
        "range_units": sacrifice.value("worthy_range_units"),
        "threshold": sacrifice.value("holder_health_threshold_ratio"),
        "source_revision_id": int(sacrifice.value("source_revision_id")),
    }


def _starved_streams(names: Collection[str]) -> list[tuple[str, str]]:
    """Each held holder that reads a raw stream, paired with that stream.

    A projection of every mechanic's declared ``reads`` in
    ``trigger_stream.CAPABILITIES``.  The label is the raw ledger key.
    """
    return sorted(
        (item, f"{stream.value}_events")
        for item in frozenset(names) & tuple_incapable_items()
        for stream in streams_for(frozenset({item})) & RAW_STREAMS
    )


class EventViewStarvationError(ValueError):
    """A declared event-view holder was handed the light tuple ledger.

    The tuple rows are positional, so every scan below reads them as an
    empty stream and prices the item at zero without failing.  That is a
    projection a consumer cannot answer from — a programming error, not a
    data condition — so it is raised rather than absorbed.
    """


def require_event_view(result: Mapping[str, Any], names: Collection[str]) -> None:
    """Raise when a declared event-view holder is handed tuple rows.

    The score-only tuple ledger (``damage_events_tuple``) carries positional
    rows that no scan below can read.  After the pipeline's tuple gate
    consults ``tuple_incapable_items()`` no public request can reach this
    state, so the raise is a programming-error tripwire rather than a
    user-facing outcome.
    """
    if not result.get("damage_events_tuple"):
        return
    starved = _starved_streams(names)
    if not starved:
        return
    read = "; ".join(f"{item} reads {stream}" for item, stream in starved)
    raise EventViewStarvationError(
        "STARVED: the score-only tuple ledger cannot answer the item support "
        f"scan — {read}.  The pipeline's tuple gate must keep dict rows for "
        "every event-view holder."
    )


def _bus_streams(
    result: Mapping[str, Any], names: Collection[str]
) -> tuple[list[Trigger], list[Trigger], list[Trigger]]:
    """One engine result as the control, damage and takedown views of it.

    The compiler reads each stream once and the bus builds only the streams
    the held holders declare, so a holder reading none pays nothing — that
    laziness is the whole reason the migration is performance-neutral
    (D-30).  ``tuple_incapable_items()`` is exactly the set of holders that
    read a raw stream, so intersecting first also bounds the projection's
    cache key to those names rather than to every build the optimizer
    explores.
    """
    scanning = frozenset(names) & tuple_incapable_items()
    by_kind: dict[TriggerKind, list[Trigger]] = {kind: [] for kind in TriggerKind}
    for trigger in authored_triggers(
        result, streams=streams_for(scanning), holder=", ".join(sorted(scanning))
    ):
        by_kind[trigger.kind].append(trigger)
    return (
        by_kind[TriggerKind.CC],
        by_kind[TriggerKind.DAMAGE],
        by_kind[TriggerKind.TAKEDOWN],
    )
