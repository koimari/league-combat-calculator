"""An ability that empowers the next auto, and the swings its casts consumed."""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from ...cast_event_row import cast_slot
from ...damage_event_row import event_damage, event_damage_type
from ..cast_control_marker import _declared_cc_marker
from ..empower_declaration import _empower_hits
from ..ledger.breakdown import (
    source_casts,
    source_damage_per_hit,
    source_hit_count,
    source_total_damage,
)
from ..ledger.event_rows import _ledger_total, _row_damage_parts, _row_time
from ..state import FightState

# A swing at a declared impact is that impact, give or take float order.
_TIME_EPSILON = 1e-9


class _EmpoweredSwings(NamedTuple):
    """One ``empowers_next_auto`` entry and the swings its casts consumed."""

    info: dict[str, Any]
    row: dict[str, Any]
    count: int
    # Where those swings are claimed. A kit that rates its own burst declares
    # the impacts (``BurstSwingSchedule.by_ability``) and one that declares
    # ``rides_scheduled_auto`` the stream swings it rides
    # (``FightState.empowered_ride_times``); every other empower names the
    # casts that forced it, each claiming the stream swings that follow it.
    times: tuple[float, ...]
    # Whether ``times`` are the swings' own impacts rather than casts.
    declared: bool


def _empowered_swing_consumers(
    state: FightState, available: int, cast_events: Iterable[dict[str, Any]]
) -> list[_EmpoweredSwings]:
    """Each ``empowers_next_auto`` entry, its row, and the swings it consumes.

    Cast order decides who gets scarce swings, and the stream can never
    give out more than it has. A self-rated burst claims what it actually
    landed rather than ``casts x hits``: its last cast may have started
    with room for only some of its attacks.
    """
    consumers: list[_EmpoweredSwings] = []
    for ability_key in state.cast_order:
        info = state.ability_damages.get(ability_key)
        row = state.breakdown.get(ability_key)
        if info is None or row is None:
            continue
        empower = info.get("empowers_next_auto")
        if not empower:
            continue
        burst = state.burst_swings
        landed = burst.landed(ability_key) if burst is not None else 0
        hits = _empower_hits(empower)
        casts = source_casts(row)
        if not landed and casts is None:
            # No burst schedule and no cast count: nothing empowers a swing.
            continue
        swings = min(landed or casts * hits, available)
        if swings <= 0:
            continue
        declared = burst.by_ability.get(ability_key, ()) if burst is not None else ()
        declared = declared or state.empowered_ride_times.get(ability_key, ())
        times = declared or tuple(
            float(event["time"])
            for event in cast_events
            if cast_slot(event) == ability_key
            for _ in range(hits)
        )
        consumers.append(
            _EmpoweredSwings(info, row, swings, times[:swings], bool(declared))
        )
        available -= swings
    return consumers


def _claim_swings(
    ledger: list[dict[str, Any]], consumers: Sequence[_EmpoweredSwings]
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """The swings each consumer took, and the ones the auto row keeps.

    Declared impacts name their own swings, so they claim first; a cast then
    takes the first free swing at or after it.  Casts are capped by the
    stream's count, not its times, so a cast with no free swing after it, or
    one no timeline published, takes the latest free swing.
    """
    swing_times = [float(event["time"]) for event in ledger]
    free = sorted(range(len(ledger)), key=swing_times.__getitem__)
    claims: list[list[dict[str, Any]]] = [[] for _ in consumers]
    for index in sorted(range(len(consumers)), key=lambda i: not consumers[i].declared):
        consumer = consumers[index]
        for hit in range(consumer.count):
            at = consumer.times[hit] if hit < len(consumer.times) else math.inf
            position = next(
                (
                    position
                    for position, swing in enumerate(free)
                    if swing_times[swing] >= at - _TIME_EPSILON
                ),
                len(free) - 1,
            )
            claims[index].append(ledger[free.pop(position)])
    return claims, [ledger[swing] for swing in sorted(free)]


def _author_empowered_swing_events(
    consumer: "_EmpoweredSwings", swing_events: Sequence[Mapping[str, Any]]
) -> None:
    """Land an empowering row's damage on the swings its casts consumed.

    ``empowers_next_auto`` means the ability is delivered BY those
    attacks, so each consumed swing is one event carrying its own attack
    damage plus an equal share of the ability's own priced total — whose
    parts are one per empowered hit, which is what those swings are.
    Without this the row authors nothing at all, the reconstruction falls
    back to one lump per cast, and a reviewed crowd-control marker has no
    event to ride — which is what keeps Leona Q, Cho'Gath E, Fiora E and
    Jax W coarse for a control-armed holder shield.

    Each swing lands at :attr:`_EmpoweredSwings.times`, which the
    reattribution sets to the claimed swings' own impacts.

    A row that already authors its own ledger (Darius W, Wukong Q) keeps its
    parts' events, and the swings its casts claimed land beside them, so the
    fight ledger carries every swing the reattribution moved onto the row.
    """
    row = consumer.row
    if not swing_events:
        return
    authored = row.get("damage_events")
    if isinstance(authored, list):
        marker = _declared_cc_marker(consumer.info)
        authored.extend({**swing, **marker} for swing in swing_events)
        authored.sort(key=_row_time)
        return
    if len(consumer.times) != len(swing_events):
        # No time for every swing (a cast the timeline never published):
        # authoring part of the row would leave its events short of it.
        return
    own = _row_damage_parts(row)
    priced = source_total_damage(row)
    if priced is None or not math.isclose(
        sum(amount for _, amount in own),
        priced,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        # The row's typed parts do not describe its own total, so an event
        # list built from them would not sum to the row.  Fail closed.
        return
    marker = _declared_cc_marker(consumer.info)
    events: list[dict[str, Any]] = []
    for time, swing in zip(consumer.times, swing_events, strict=False):
        for damage_type, amount in own:
            events.append(
                {
                    "time": time,
                    "damage_type": damage_type,
                    "damage": amount / len(swing_events),
                    **marker,
                }
            )
        events.append(
            {
                "time": time,
                "damage_type": event_damage_type(swing),
                "damage": event_damage(swing),
                **marker,
            }
        )
    row["damage_events"] = events


def _reattribute_empowered_swings(
    state: FightState, cast_events: list[dict[str, Any]]
) -> None:
    """Show an empowered auto's swing on the ability that forced it.

    An ``empowers_next_auto`` ability (Mundo E, Camille Q, Darius W,
    Cho'Gath E) consumes a basic attack, so in-game the player sees ONE
    hit worth ``attack + bonus``. With no auto stream the ability row
    already carries that swing (``_compute_ability_rotation``); with a
    stream it was left in the auto row, so the same ability read as
    bonus-only in timed fights and attack+bonus in one-rotation — two
    meanings for one row. Moving the consumed swings here reconciles the
    modes.

    Damage only moves BETWEEN rows: the fight total is untouched, and so
    is every on-hit row, which the empowered attack genuinely still
    triggers.

    **The move is the swings the consumers claimed** (:func:`_claim_swings`),
    at the time they landed and the damage they dealt, so a swing a shred
    window or a crit roll set apart keeps its own price and its own place.
    The kept swings' crit split is recounted from those swings.
    """
    auto_row = state.breakdown.get("auto_attacks")
    if not auto_row:
        return
    original_count = source_hit_count(auto_row)
    per_hit = source_damage_per_hit(auto_row)
    if original_count is None or per_hit is None or original_count <= 0 or per_hit <= 0:
        return
    consumers = _empowered_swing_consumers(state, original_count, cast_events)
    if not consumers:
        return
    remaining = original_count - sum(consumer.count for consumer in consumers)
    # A row whose events were never authored one-per-swing has no ledger
    # to price from; it keeps the blended average (and stays coarse, as
    # it did before) rather than pricing off a list that is not the
    # stream.
    ledger = auto_row.get("damage_events")
    if not isinstance(ledger, list) or len(ledger) != original_count:
        ledger = None

    claims, kept = (
        _claim_swings(ledger, consumers) if ledger is not None else (None, None)
    )
    for index, consumer in enumerate(consumers):
        if claims is None:
            swings: list[dict[str, Any]] = []
            moved = consumer.count * per_hit
        else:
            swings = claims[index]
            moved = _ledger_total(swings)
            if len(consumer.times) == consumer.count:
                consumer = consumer._replace(
                    times=tuple(float(swing["time"]) for swing in swings)
                )
        _author_empowered_swing_events(consumer, swings)
        row = consumer.row
        row["total_damage"] += moved
        auto_row["total_damage"] -= moved
        # ``detail`` always wins over the UI's derived "N casts" text, so
        # spell out that the row now includes the attack it consumed.
        # A burst-scheduled consumer can reach here with no cast count at
        # all, and the derived text counts what it can prove: no casts.
        casts = source_casts(row) or 0
        base = row.get("detail") or f"{casts} cast{'' if casts == 1 else 's'}"
        row["detail"] = f"{base}, incl. basic attack"

    auto_row["count"] = remaining
    if kept is not None:
        auto_row["damage_events"] = kept
        auto_row["damage_per_hit"] = (
            auto_row["total_damage"] / remaining if remaining else 0.0
        )
    elif isinstance(auto_row.get("damage_events"), list):
        auto_row["damage_events"] = auto_row["damage_events"][:remaining]
    _recount_kept_crit_split(auto_row, kept, remaining, original_count)


def _recount_kept_crit_split(
    auto_row: dict[str, Any],
    kept: list[dict[str, Any]] | None,
    remaining: int,
    original_count: int,
) -> None:
    """Publish the crit split of the swings the auto row kept.

    Counted off those swings' own rolls, not rescaled by their share of
    the stream: a row could otherwise publish one critical strike while
    every crit sat in the moved swings.  Only a row with no per-swing ledger
    falls back to the proportion.
    """
    if auto_row.get("num_crits") is None:
        return
    crits = (
        sum(1 for event in kept if event.get("critical_strike"))
        if kept is not None
        else round(auto_row["num_crits"] * remaining / original_count)
    )
    auto_row["num_crits"] = crits
    auto_row["num_non_crits"] = remaining - crits
    if crits == 0:
        auto_row["crit_damage_per_hit"] = None
    if crits == remaining:
        auto_row["non_crit_damage_per_hit"] = None
