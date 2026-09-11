"""Splitting a damage-over-time total into sourced ticks."""

import math
from collections.abc import Callable, Sequence
from typing import Any

from ...ability_atoms import ability_field, ability_payload
from ..ledger.event_rows import _finite_numeric_receipt, _row_damage_parts, _row_time
from ..resists import Resists, _mitigate, _resistance_met_fields
from ..results import RotationResult, StackTimeline
from ..state import FightState


def _ability_dot_tick_events(
    entry: dict[str, Any],
    info: dict[str, Any],
    cast_times: Sequence[float],
    resists: Resists,
    cutoff: float | None = None,
) -> list[dict[str, float | str]] | None:
    """One DoT ability row's per-tick events, or None to stay coarse.

    A row qualifies when its ability declares both ``dot_duration`` and a
    wiki-sourced ``dot_tick_interval``. Each accepted cast spreads its even
    share of the row's typed damage across the DoT window from its cast
    time, using the same full-tick/remainder split as item burns. Rows
    without a sourced cadence author nothing (fail-closed — a cadence is
    never invented), as do rows whose totals a later step may move
    (``empowers_next_auto`` swings) or whose typed parts do not reproduce
    the row total. A malformed cadence (non-finite or non-numeric
    ``dot_duration``/``dot_tick_interval``) is treated the same as a missing
    one — fail-closed, never coerced or invented.
    """
    dot_duration = _finite_numeric_receipt(ability_field(info, "dot_duration")) or 0.0
    tick_interval = (
        _finite_numeric_receipt(ability_field(info, "dot_tick_interval")) or 0.0
    )
    if dot_duration <= 0 or tick_interval <= 0:
        return None
    if info.get("empowers_next_auto"):
        return None  # the reattributed swing would break the event sum
    casts = max(0, int(entry.get("casts", 0)))
    if casts <= 0:
        return None
    parts = _row_damage_parts(entry)
    if not parts or not math.isclose(
        sum(amount for _, amount in parts),
        float(entry.get("total_damage", 0.0)),
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        return None
    events: list[dict[str, float | str]] = []
    for cast_index in range(casts):
        cast_time = cast_times[cast_index] if cast_index < len(cast_times) else 0.0
        for dtype, amount in parts:
            ticks = [
                {**tick, "time": cast_time + float(tick["time"])}
                for tick in _periodic_damage_events(
                    amount / casts,
                    dtype,
                    dot_duration,
                    tick_interval,
                    resists=resists,
                )
            ]
            if cutoff is not None:
                # The row's total already holds only the ticks inside the
                # window (cast_parts priced them); the ticks kept here carry
                # that total between them so the events still sum to the row.
                kept = [tick for tick in ticks if float(tick["time"]) <= cutoff + 1e-9]
                kept_sum = sum(float(tick["damage"]) for tick in kept)
                if kept and kept_sum > 0:
                    scale = (amount / casts) / kept_sum
                    ticks = [
                        {**tick, "damage": float(tick["damage"]) * scale}
                        for tick in kept
                    ]
                else:
                    ticks = []
            events.extend(ticks)
    events.sort(key=_row_time)
    return events or None


def _author_ability_dot_events(state: FightState, rotation: RotationResult) -> None:
    """Author per-tick damage events for DoT ability rows with sourced cadence.

    Ticks let the coverage classifier certify a ``dot_duration`` row
    instead of downgrading it at the cast boundary; rows that stay
    unsourced keep coarse ordering. Rows that already authored their own
    event ledger are left alone.
    """
    times_by_slot: dict[str, list[float]] = {}
    for event in rotation.cast_events:
        slot = str(event.get("slot", ""))
        times_by_slot.setdefault(slot, []).append(float(event["time"]))
    for key in state.cast_order:
        entry = state.breakdown.get(key)
        info = ability_payload(state.ability_damages, key)
        if not entry or entry.get("damage_events") is not None:
            continue
        events = _ability_dot_tick_events(
            entry,
            info,
            times_by_slot.get(key, []),
            state.resists,
            cutoff=state.fight_duration_seconds if state.clip_to_window else None,
        )
        if events is not None:
            entry["damage_events"] = events
            entry["event_phase"] = "ability"


class _DotTickLedger:
    """Buckets a stacking DoT's continuous integral into sourced ticks.

    Constructed with the spec's ``tick_interval`` (0 disables authoring —
    an unsourced cadence is never invented) and the fight's rate integral.
    ``accumulate`` integrates one constant-stack span, cutting it at the
    tick boundaries riding the current chain's clock; ``open_chain``
    anchors that clock at the application that opened a chain;
    ``close_chain`` flushes the last partial tick where a chain's bleed
    actually stopped. ``events`` scales the raw buckets to the mitigated
    total, since mitigation is one linear factor.
    """

    def __init__(
        self,
        interval: float,
        integrate: Callable[[float, float, int], float],
    ) -> None:
        self.interval = interval
        self.authoring = interval > 0
        self._integrate = integrate
        self._raw_ticks: list[list[float]] = []  # [time, raw damage]
        self._pending_raw = 0.0
        self._next_tick: float | None = None

    def open_chain(self, time: float) -> None:
        """Anchor the tick clock when no chain is running."""
        if self.authoring and self._next_tick is None:
            self._next_tick = time + self.interval

    def close_chain(self, time: float) -> None:
        """Flush the chain's last partial tick and drop its clock."""
        if self.authoring:
            self._flush(time)
            self._next_tick = None

    def accumulate(self, start: float, end: float, stacks: int) -> float:
        """Integrate [start, end), bucketing the raw damage into ticks."""
        if not self.authoring:
            return self._integrate(start, end, stacks)
        raw = 0.0
        cursor = start
        while self._next_tick is not None and self._next_tick <= end:
            raw += self._bucket(cursor, self._next_tick, stacks)
            cursor = self._next_tick
            self._flush(self._next_tick)
            self._next_tick += self.interval
        raw += self._bucket(cursor, end, stacks)
        return raw

    def _bucket(self, start: float, end: float, stacks: int) -> float:
        segment = self._integrate(start, end, stacks)
        self._pending_raw += segment
        return segment

    def _flush(self, time: float) -> None:
        if self._pending_raw > 0:
            self._raw_ticks.append([time, self._pending_raw])
            self._pending_raw = 0.0

    def events(
        self, damage_type: str, total: float, raw_total: float, resists: Resists
    ) -> list[dict[str, Any]] | None:
        """The mitigated per-tick event list, or None when not authoring.

        ``resists`` is what the aggregate was mitigated against, so each
        tick states the resistance the whole cadence met.
        """
        if not (self.authoring and self._raw_ticks and raw_total > 0 and total > 0):
            return None
        scale = total / raw_total
        met = _resistance_met_fields(damage_type, resists)
        events: list[dict[str, Any]] = [
            {
                "time": time,
                "damage_type": damage_type,
                "damage": raw * scale,
                "event_precision": "exact",
                **met,
            }
            for time, raw in self._raw_ticks
        ]
        # Eliminate floating-point drift while preserving every tick's timing.
        events[-1]["damage"] += total - sum(event["damage"] for event in events)
        return events


def _integrate_stack_chains(
    timeline: StackTimeline,
    duration: float,
    ledger: _DotTickLedger,
    cutoff: float | None = None,
) -> float:
    """Walk the stack applications, integrating every chain's raw damage.

    Each span between applications ticks at the running stack count;
    ticks stop ``duration`` after the last application even if the next
    one comes later (the chain expired meanwhile), and the final
    application commits its full window of ticks past the fight cutoff.
    The ledger buckets the same integral into tick events as it goes.
    """
    raw_total = 0.0
    stacks = timeline.starting_stacks
    previous_hit = 0.0
    if stacks > 0:
        ledger.open_chain(0.0)  # the pre-fight chain is already running
    for application in timeline.applications:
        if cutoff is not None and application.time > cutoff:
            break
        if stacks > 0:
            chain_end = min(application.time, previous_hit + duration)
            raw_total += ledger.accumulate(previous_hit, chain_end, stacks)
            if application.stacks_before == 0:
                # The chain expired before this hit: close its last
                # (partial) tick where the bleed actually stopped.
                ledger.close_chain(chain_end)
        # A fresh chain's ticks ride this application's clock; a running
        # chain keeps its anchor (open_chain is a no-op then).
        ledger.open_chain(application.time)
        stacks = application.stacks_after
        previous_hit = application.time
    # Committed tail: the last application's full window of ticks, or only
    # what ticks before the fight's end when the request clips to the window.
    tail_end = previous_hit + duration
    if cutoff is not None:
        tail_end = max(previous_hit, min(tail_end, cutoff))
    raw_total += ledger.accumulate(previous_hit, tail_end, stacks)
    ledger.close_chain(tail_end)
    return raw_total


def _add_stacking_dot_damage(state: FightState) -> None:
    """Add hit-timeline stacking DoT damage (Case 4, e.g. Briar's bleed).

    Integrates the DoT's tick rate at the running stack count over the
    fight's :class:`StackTimeline` — the SAME applications the rotation
    priced its casts against. Every application refreshes the shared
    duration (in-game: reapplying refreshes the whole bleed); a gap
    longer than ``duration`` expires the chain. Committed accounting:
    the final ``duration`` of ticks after the last hit counts in full,
    even past the fight cutoff. A stack-triggered bonus-AD window
    (Case 5) raises the tick rate for exactly the part of each gap that
    falls inside it, so a window opening mid-gap splits that gap. The
    DoT cannot crit and triggers nothing; it is mitigated once as its
    declared type.

    A spec with a sourced ``tick_interval`` also authors per-tick damage
    events: the same integral is bucketed at tick boundaries riding each
    chain's clock (anchored at the application that opened the chain; a
    gap of ``duration`` closes the chain's last partial tick where the
    bleed stopped and the next application re-anchors the grid). Without
    a sourced cadence no events are invented and the row stays coarse.
    """
    timeline = state.stack_timeline
    if timeline is None:
        return
    # Pre-fight stacks tick on their own, so a fight that lands no
    # applications still bleeds when the target arrives stacked.
    if not timeline.applications and timeline.starting_stacks <= 0:
        return
    dot_key, spec = timeline.dot_key, timeline.spec

    duration = float(spec["duration"])
    extra_effectiveness = float(spec["extra_stack_effectiveness"])
    single_stack_dps = float(spec["single_stack_raw"]) / duration
    # A mid-fight bonus-AD steroid raises every stack's rate by the
    # DoT's own declared derivative in bonus AD (Darius' bleed: 30% of
    # bonus AD per stack).
    buffed_bonus_dps = (
        float(ability_field(spec, "single_stack_bonus_ad_ratio", form="stacking_dot"))
        * timeline.buff_bonus_ad
        / duration
    )

    def tick_rate(stacks: int, buffed: bool) -> float:
        """Raw DPS at a stack count; extra stacks may tick reduced."""
        single = single_stack_dps + (buffed_bonus_dps if buffed else 0.0)
        return single * (1.0 + extra_effectiveness * (stacks - 1))

    def integrate(start: float, end: float, stacks: int) -> float:
        """Raw damage ticked over [start, end), split at buff windows."""
        total_raw = 0.0
        cursor = start
        for window_start, window_end in timeline.buff_windows:
            if window_end <= cursor:
                continue
            if window_start >= end:
                break
            if window_start > cursor:
                total_raw += tick_rate(stacks, False) * (window_start - cursor)
                cursor = window_start
            segment_end = min(window_end, end)
            total_raw += tick_rate(stacks, True) * (segment_end - cursor)
            cursor = segment_end
        if cursor < end:
            total_raw += tick_rate(stacks, False) * (end - cursor)
        return total_raw

    ledger = _DotTickLedger(
        float(ability_field(spec, "tick_interval", form="stacking_dot")), integrate
    )
    raw_total = _integrate_stack_chains(
        timeline,
        duration,
        ledger,
        cutoff=state.fight_duration_seconds if state.clip_to_window else None,
    )

    damage_type = ability_field(spec, "damage_type", form="stacking_dot")
    total = _mitigate(raw_total, damage_type, state.resists, state.magic_amp)
    # A seeded-only fight lands no applications; the pre-fight stacks are
    # what the row is reporting, so they are its count.
    applications = len(timeline.applications) or timeline.starting_stacks
    row: dict[str, Any] = {
        "name": spec["name"],
        "count": applications,
        "damage_per_hit": total / applications,
        "unit": "stacks",
        "total_damage": total,
        "damage_type": damage_type,
        "detail": (
            f"{applications} stack application(s); each refresh commits "
            f"the full {duration:g}s of ticks"
        ),
    }
    events = ledger.events(damage_type, total, raw_total, state.resists)
    if events is not None:
        row["damage_events"] = events
        row["event_phase"] = "effect"
    state.breakdown[f"stacking_dot_{dot_key}"] = row
    state.total_damage += total


def _periodic_damage_events(
    total_damage: float,
    damage_type: str,
    duration: float,
    interval: float,
    *,
    resists: Resists | None = None,
) -> list[dict[str, float | str]]:
    """Split an aggregate periodic total into timestamped full/partial ticks.

    ``resists`` is what the caller mitigated the aggregate against; one
    cadence is one damage class, so every tick met the same resistance.
    """
    if total_damage <= 0 or duration <= 0 or interval <= 0:
        return []
    met = {} if resists is None else _resistance_met_fields(damage_type, resists)
    events: list[dict[str, float | str]] = []
    full_ticks = int(duration / interval + 1e-9)
    damage_rate = total_damage / duration
    events.extend(
        {
            "time": (index + 1) * interval,
            "damage_type": damage_type,
            "damage": damage_rate * interval,
            **met,
        }
        for index in range(full_ticks)
    )
    remainder = duration - full_ticks * interval
    if remainder > 1e-9:
        events.append(
            {
                "time": duration,
                "damage_type": damage_type,
                "damage": damage_rate * remainder,
                **met,
            }
        )
    if events:
        # Eliminate floating-point drift while preserving every tick's timing.
        emitted = sum(float(event["damage"]) for event in events)
        events[-1]["damage"] = float(events[-1]["damage"]) + total_damage - emitted
    return events
