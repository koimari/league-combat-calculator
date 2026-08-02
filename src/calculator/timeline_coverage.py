"""Shared receipts for fight-event ordering precision."""

from collections.abc import Iterable, Mapping
from typing import Any


def combine_timeline_coverages(
    coverages: Iterable[Mapping[str, Any]],
    *,
    target_count: int,
) -> dict[str, Any]:
    """Combine target receipts without presenting partial order as exact."""
    rows = list(coverages)
    coarse_sources = sorted(
        {source for coverage in rows for source in coverage.get("coarse_sources", [])}
    )
    exact_sources = sorted(
        {source for coverage in rows for source in coverage.get("exact_sources", [])}
        - set(coarse_sources)
    )
    complete = bool(rows) and all(coverage.get("complete", False) for coverage in rows)
    if complete:
        note = (
            f"Every active damage source is event-ordered across {target_count} "
            f"selected {'target' if target_count == 1 else 'targets'}."
        )
    elif not coarse_sources:
        note = "Timeline coverage is unavailable for at least one selected target."
    else:
        note = (
            f"{len(coarse_sources)} active damage source"
            f"{' uses' if len(coarse_sources) == 1 else 's use'} coarse phase "
            "ordering on at least one selected target."
        )
    return {
        "complete": complete,
        "certification": (
            "event_order_certified" if complete else "partial_event_order"
        ),
        "exact_sources": exact_sources,
        "coarse_sources": coarse_sources,
        "note": note,
    }
