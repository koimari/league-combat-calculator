"""Shared spatial primitives (roadmap P5).

One dependency-light leaf owns the small typed spatial contracts:
position extraction, Euclidean distance, holder-centered range
counting, and fail-closed spatial-input receipts.

Design rules (HANDOVER §11):

- Numeric range values come from the data cache through the consumer's
  typed accessors; this module never invents a unit or radius.
- Position is extracted from an actor's ``stats.position`` tuple.
- Fail-closed: missing, non-finite, or malformed positions produce a
  named ``spatial_input_unavailable`` receipt; the consumer applies
  its own base or fallback semantics.
- Euclidean distance uses standard float arithmetic (1e-9 tolerance
  shared with the damage/survival walks).
- Range boundary is inclusive (≤) by convention, matching the
  sourced wiki prose for Everlasting's "within 1200 units".
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

# Floating-point tolerance shared with the damage/survival walks.
_EPS = 1e-9

# Public label for the spatial-input-unavailable receipt reason.
SPATIAL_UNAVAILABLE = "nearby_enemy_spatial_input_unavailable"

# Missing/invalid position sentinel reason strings.
MISSING_HOLDER_POSITION = "missing_holder_position"
MALFORMED_HOLDER_POSITION = "malformed_holder_position"


def _position_of(actor: Any) -> tuple[float, float] | None:
    """Extract an (x, y) position from an actor's stats, returning *None*
    when the position is missing or non-finite."""
    stats = getattr(actor, "stats", None)
    if not isinstance(stats, Mapping):
        return None
    raw = stats.get("position")
    if raw is None:
        return None
    if not isinstance(raw, tuple) or len(raw) != 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two (x, y) positions."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def enemies_within_range(
    holder: Any,
    all_actors: Iterable[Any],
    range_units: float,
) -> tuple[int, str | None]:
    """Count enemies whose position is within *range_units* of the holder.

    Returns ``(count, spatial_failure_reason)`` where *spatial_failure_reason*
    is *None* on success or a named string when spatial input is unavailable
    (missing holder position, malformed values, or holder identity absent).
    A count of zero with a *None* reason means the holder has no enemies in
    range — a valid spatial result, not a failure.
    """
    holder_position = _position_of(holder)
    if holder_position is None:
        return 0, MISSING_HOLDER_POSITION
    holder_id = getattr(holder, "participant_id", None)
    if not isinstance(holder_id, str) or not holder_id.strip():
        return 0, "missing_holder_identity"

    count = 0
    any_enemy_missing_position = False
    for actor in all_actors:
        # Skip the holder itself.
        actor_id = getattr(actor, "participant_id", None)
        if isinstance(actor_id, str) and actor_id == holder_id:
            continue
        # Only count enemies (different team).
        if getattr(actor, "team", None) == getattr(holder, "team", None):
            continue
        position = _position_of(actor)
        if position is None:
            # An enemy with an unreadable position means the spatial
            # evaluation cannot be certified — one invisible enemy
            # could be inside the radius.  The consumer keeps the
            # base shield and emits a named denial receipt.
            any_enemy_missing_position = True
            continue
        if euclidean(holder_position, position) <= range_units + _EPS:
            count += 1
    if any_enemy_missing_position:
        return 0, SPATIAL_UNAVAILABLE
    return count, None
