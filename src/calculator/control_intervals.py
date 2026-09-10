"""Span algebra over control and downtime intervals."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .crowd_control_eligibility import KNOWN_CONTROL_KINDS

_EPS = 1e-9


def _interval_bounds(interval: Mapping[str, Any]) -> tuple[float, float]:
    start = float(interval.get("start", 0.0) or 0.0)
    end = float(interval.get("end", 0.0) or 0.0)
    return start, end


def _interval_kind(interval: Mapping[str, Any]) -> str:
    return str(interval.get("kind", "") or "").strip().lower()


def interval_active(interval: Mapping[str, Any], at: float) -> bool:
    """Whether one interval is ACTIVE at a time (start inclusive, end
    exclusive — the walk's DefenseWindow convention)."""
    start, end = _interval_bounds(interval)
    return start <= at + _EPS and end > at + _EPS


def merged_spans(
    spans: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Sort ``[start, end)`` spans and fuse any that touch or overlap.

    The ONE interval fold: the union length below is its total length, and
    the engine's empowered-burst blocks are the same spans read as blocks.
    """
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def merged_interval_duration(intervals: Sequence[Mapping[str, Any]]) -> float:
    """The union length of authored inactive intervals, which both the
    truncation below and the survival row's published downtime call.

    Union rather than sum: two controls overlapping in time cost the actor one
    window of downtime and not two, so a total that added them would publish
    more downtime than the fight is long.
    """
    # The overwhelmingly common answer, taken without allocating: almost no
    # participant of almost any fight is ever inactive, and the survival row
    # runs this once per participant per walk on the optimizer's hot path.
    if not intervals:
        return 0.0
    spans = merged_spans(
        bounds
        for bounds in (_interval_bounds(interval) for interval in intervals)
        if bounds[1] > bounds[0]
    )
    # A window opening before the fight clock is measured from zero, and the
    # blocks are added one at a time: ``sum()`` compensates and this walk's
    # published downtime is the uncompensated total.
    total = 0.0
    for start, end in spans:
        if end > 0.0:
            total += end - max(0.0, start)
    return max(0.0, total)


def movement_entry(declaration: Mapping[str, Any]) -> dict[str, Any] | None:
    """The movement utility entry of a cleanse declaration (Mercurial's 50%
    bonus total movement speed for 2 s, own atoms) — the ONE builder both
    the authoring layer and the walk use, so the receipt shape cannot
    drift."""
    movement = declaration.get("movement")
    if movement is None:
        return None
    return {
        "amount": max(0.0, float(movement.get("amount", 0.0) or 0.0)),
        "duration": max(0.0, float(movement.get("duration", 0.0) or 0.0)),
        "source": str(movement.get("source", "") or ""),
        "source_atoms": [dict(atom) for atom in movement.get("source_atoms", ())],
    }


def truncate_intervals(
    intervals: Iterable[Mapping[str, Any]],
    activation_time: float,
    eligible_kinds: Iterable[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One pure interval-truncation operation.

    Returns ``(kept, removed)`` for the intervals passed at the activation
    instant:

    - an interval whose kind is outside :data:`KNOWN_CONTROL_KINDS` is
      NEVER truncated (unknown kinds fail closed — R15);
    - an interval whose kind is not in ``eligible_kinds`` is untouched
      (rejected by the caller, never truncated);
    - an interval that ended at/before activation (historical) is kept;
    - an interval ACTIVE at activation (start < time < end) is clamped:
      ``[start, time)`` kept, ``[time, end)`` removed;
    - an interval STARTING at activation (``start == time`` — the
      same-time control packet, which the walk's total order applies
      before the cleanse) is removed entirely;
    - an interval starting after activation (future control) is untouched
      (a cleanse creates NO immunity).

    Removed entries are the input dicts with ``start``/``end`` adjusted
    (the tail or the whole interval), so receipts can attribute them.
    """
    activation = float(activation_time)
    eligible = frozenset(str(kind) for kind in eligible_kinds)
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for interval in intervals:
        row = dict(interval)
        kind = _interval_kind(row)
        if kind not in KNOWN_CONTROL_KINDS or kind not in eligible:
            kept.append(row)
            continue
        start, end = _interval_bounds(row)
        if end <= activation + _EPS:
            # Historical downtime: remains counted.
            kept.append(row)
            continue
        if start >= activation - _EPS:
            # Same-timestamp control (already applied by the walk's total
            # order): removed entirely.  A control landing later is not in
            # this list yet and stays untouched.
            removed.append({**row, "start": start, "end": end})
            continue
        # Active interval: ends at activation; the future tail is removed.
        kept.append({**row, "end": activation})
        removed.append({**row, "start": activation, "end": end})
    return kept, removed
