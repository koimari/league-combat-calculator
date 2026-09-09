"""An ability that empowers the next auto, and the swings its casts consumed."""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from ..cast_control_marker import _declared_cc_marker
from ..empower_declaration import _empower_hits
from ..ledger.event_rows import _ledger_total, _row_damage_parts
from ..state import FightState


class _EmpoweredSwings(NamedTuple):
    """One ``empowers_next_auto`` entry and the swings its casts consumed."""

    info: dict[str, Any]
    row: dict[str, Any]
    count: int
    # When those swings land. A kit that rates its own burst declares the
    # impacts (``BurstSwingSchedule.by_ability``); one that declares
    # ``rides_scheduled_auto`` lands on the stream swings it claimed
    # (``FightState.empowered_ride_times``); every other empower is timed
    # at the cast that forced it — where a timer-resetting one (Darius W,
    # Jax W, Fiora E) genuinely swings.  A multi-hit empower that resets
    # nothing (Cho'Gath E's three spiked attacks) therefore stacks its
    # hits on the cast until its kit declares a rate or a ride.
    times: tuple[float, ...]


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
        swings = min(landed or row.get("casts", 0) * hits, available)
        if swings <= 0:
            continue
        declared = burst.by_ability.get(ability_key, ()) if burst is not None else ()
        declared = declared or state.empowered_ride_times.get(ability_key, ())
        times = declared or tuple(
            float(event["time"])
            for event in cast_events
            if str(event.get("slot", "")) == ability_key
            for _ in range(hits)
        )
        consumers.append(_EmpoweredSwings(info, row, swings, times[:swings]))
        available -= swings
    return consumers


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

    A swing is priced from the ledger slice the reattribution removes
    (wave 1E) and timed from :attr:`_EmpoweredSwings.times`.  Those name
    the same attack in a stream whose swings are alike; where they are
    not, taking a different swing's damage would re-price the row and the
    auto row's crit split with it, which this wave may not do.

    A row that already authors its own ledger is left alone.  Its events
    are its parts', and appending the swings to them adds damage the fight
    ledger has never carried (Vayne Q's and Camille Q's moved swings are
    missing from it today) — a re-pricing, not this plumbing.
    """
    row = consumer.row
    if isinstance(row.get("damage_events"), list) or not swing_events:
        return
    if len(consumer.times) != len(swing_events):
        # No time for every swing (a cast the timeline never published):
        # authoring part of the row would leave its events short of it.
        return
    own = _row_damage_parts(row)
    if not math.isclose(
        sum(amount for _, amount in own),
        float(row.get("total_damage", 0.0)),
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
                "damage_type": str(swing.get("damage_type", "physical")),
                "damage": float(swing.get("damage", 0.0)),
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

    **The move is priced at the swings it removes.** Which swings a cast
    consumed is not tracked, so the ledger names them: it keeps its
    leading block and the consumed ones are its trailing swings, at the
    damage those swings actually dealt.  Pricing the move at the row's
    blended per-hit average instead made the row's total and its own
    ledger describe different things whenever the stream's swings differ
    from each other — which a rolled critical strike does at random, so
    one request certified and the next went coarse.  The kept swings'
    crit split is recounted from those swings for the same reason.
    """
    auto_row = state.breakdown.get("auto_attacks")
    if not auto_row:
        return
    original_count = auto_row.get("count", 0)
    per_hit = auto_row.get("damage_per_hit", 0.0)
    if original_count <= 0 or per_hit <= 0:
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

    cursor = remaining
    for consumer in consumers:
        count = consumer.count
        swings = ledger[cursor : cursor + count] if ledger is not None else ()
        moved = _ledger_total(swings) if ledger is not None else count * per_hit
        cursor += count
        _author_empowered_swing_events(consumer, swings)
        row = consumer.row
        row["total_damage"] += moved
        auto_row["total_damage"] -= moved
        # ``detail`` always wins over the UI's derived "N casts" text, so
        # spell out that the row now includes the attack it consumed.
        casts = row.get("casts", 0)
        base = row.get("detail") or f"{casts} cast{'' if casts == 1 else 's'}"
        row["detail"] = f"{base}, incl. basic attack"

    auto_row["count"] = remaining
    if ledger is not None:
        auto_row["damage_events"] = ledger[:remaining]
        auto_row["damage_per_hit"] = (
            auto_row["total_damage"] / remaining if remaining else 0.0
        )
    elif isinstance(auto_row.get("damage_events"), list):
        auto_row["damage_events"] = auto_row["damage_events"][:remaining]
    _recount_kept_crit_split(auto_row, ledger, remaining, original_count)


def _recount_kept_crit_split(
    auto_row: dict[str, Any],
    ledger: list[dict[str, Any]] | None,
    remaining: int,
    original_count: int,
) -> None:
    """Publish the crit split of the swings the auto row kept.

    Counted off those swings' own rolls, not rescaled by their share of
    the stream: a row could otherwise publish one critical strike while
    every crit sat in the moved tail.  Only a row with no per-swing ledger
    falls back to the proportion.
    """
    if auto_row.get("num_crits") is None:
        return
    crits = (
        sum(1 for event in ledger[:remaining] if event.get("critical_strike"))
        if ledger is not None
        else round(auto_row["num_crits"] * remaining / original_count)
    )
    auto_row["num_crits"] = crits
    auto_row["num_non_crits"] = remaining - crits
    if crits == 0:
        auto_row["crit_damage_per_hit"] = None
    if crits == remaining:
        auto_row["non_crit_damage_per_hit"] = None
