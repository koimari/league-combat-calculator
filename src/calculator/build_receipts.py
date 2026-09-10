"""What an evaluated build publishes."""

from collections.abc import Iterable, Mapping
from typing import Any


def _public_build_receipt(
    items: Iterable[dict[str, Any]],
    coverage: dict[str, Any],
    reason: str,
    *,
    exclusion_type: str | None = None,
) -> dict[str, Any]:
    """Serialize one candidate withheld before ranking as an audit row."""
    boots = next(
        (
            str(item.get("name", ""))
            for item in items
            if "BOOTS" in item.get("rank", [])
        ),
        None,
    )
    receipt = {
        "items": [
            str(item.get("name", ""))
            for item in items
            if "BOOTS" not in item.get("rank", [])
        ],
        "boots": boots,
        "timeline_coverage": dict(coverage),
        "reason": str(reason),
    }
    if exclusion_type is not None:
        receipt["exclusion_type"] = str(exclusion_type)
    return receipt


def public_search_timeline_coverage(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize precision across every candidate evaluation in this search."""
    evaluations = int(audit["evaluations"])
    partial_evaluations = int(audit["partial_evaluations"])
    excluded_evaluations = int(audit.get("excluded_evaluations", 0))
    coarse_sources = sorted(audit["coarse_sources"])
    exact_sources = sorted(set(audit["exact_sources"]) - set(coarse_sources))
    scored_evaluations = max(0, evaluations - excluded_evaluations)
    excluded_sources = sorted(audit.get("excluded_sources", set()))
    complete = scored_evaluations > 0 and partial_evaluations == 0
    if complete:
        note = f"All {scored_evaluations:,} scored candidate evaluations are event-ordered."
        if excluded_evaluations:
            names = ", ".join(excluded_sources) or "audited item timing"
            note += (
                f" {excluded_evaluations:,} candidate evaluations were excluded "
                f"before ranking ({names})."
            )
    elif coarse_sources:
        note = (
            f"{partial_evaluations:,} of {evaluations:,} candidate evaluations use "
            "coarse phase ordering."
        )
    else:
        note = "Timeline coverage is unavailable for at least one candidate evaluation."
    return {
        "complete": complete,
        "certification": (
            (
                "candidate_event_order_certified_with_exclusions"
                if excluded_evaluations
                else "candidate_event_order_certified"
            )
            if complete
            else "partial_candidate_event_order"
        ),
        "evaluations": evaluations,
        "scored_evaluations": scored_evaluations,
        "excluded_evaluations": excluded_evaluations,
        "partial_evaluations": partial_evaluations,
        "exact_sources": exact_sources,
        "coarse_sources": coarse_sources,
        "excluded_sources": excluded_sources,
        "note": note,
    }
