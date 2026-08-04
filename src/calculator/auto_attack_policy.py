"""Source-backed policy for the fight engine's auto-attack uptime.

The calculator cannot observe movement, target access, or player execution.  It
therefore does not pretend to know real combat uptime.  The calculated mode is
the narrower, reproducible quantity the engine can support: the fraction of a
standard five-second rotation left available after sourced spell cast lockouts.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .champions.slotlib import extract_cast_time

AUTO_ATTACK_UPTIME_MODE_LEGACY = "legacy"
AUTO_ATTACK_UPTIME_MODE_EXPLICIT = "explicit"
AUTO_ATTACK_UPTIME_MODE_CALCULATED = "calculated"
AUTO_ATTACK_UPTIME_MODES = frozenset(
    {
        AUTO_ATTACK_UPTIME_MODE_LEGACY,
        AUTO_ATTACK_UPTIME_MODE_EXPLICIT,
        AUTO_ATTACK_UPTIME_MODE_CALCULATED,
    }
)
AUTO_ATTACK_UPTIME_POLICY_WINDOW_SECONDS = 5.0


def _source_cast_time(
    champion_data: Mapping[str, Any],
    ability_damages: Mapping[str, Mapping[str, Any]],
    slot: str,
) -> tuple[float | None, str]:
    """Return one cast lockout and its provenance, or ``None`` if unavailable."""
    entry = ability_damages.get(slot)
    if isinstance(entry, Mapping) and "cast_time" in entry:
        try:
            value = float(entry["cast_time"])
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value) and value >= 0.0:
            return value, "reviewed module or cached ability parser"

    raw_abilities = champion_data.get("abilities", {})
    raw_slot = raw_abilities.get(slot) if isinstance(raw_abilities, Mapping) else None
    if (
        not isinstance(raw_slot, list)
        or not raw_slot
        or not isinstance(raw_slot[0], Mapping)
    ):
        return None, "cached ability castTime unavailable"
    try:
        value = float(extract_cast_time(dict(raw_slot[0])))
    except (TypeError, ValueError):
        return None, "cached ability castTime unavailable"
    if not math.isfinite(value) or value < 0.0:
        return None, "cached ability castTime unavailable"
    return value, "cached ability castTime"


def resolve_auto_attack_policy(
    champion_data: Mapping[str, Any],
    ability_damages: Mapping[str, Mapping[str, Any]],
    *,
    cast_order: list[str] | None,
    duration_seconds: float,
    requested_uptime: float,
    mode: str,
    one_rotation: bool,
) -> tuple[float, dict[str, Any]]:
    """Resolve uptime and return the public receipt used by every consumer."""
    if mode == AUTO_ATTACK_UPTIME_MODE_LEGACY:
        return requested_uptime, {
            "mode": mode,
            "status": "explicit_off" if requested_uptime == 0.0 else "legacy_numeric",
            "uptime": round(requested_uptime, 6),
            "window_seconds": round(duration_seconds, 3),
            "source": "legacy request semantics",
            "assumptions": [
                "No inferred player uptime; caller supplied the numeric value."
            ],
        }
    if mode == AUTO_ATTACK_UPTIME_MODE_EXPLICIT:
        return requested_uptime, {
            "mode": mode,
            "status": "explicit",
            "uptime": round(requested_uptime, 6),
            "window_seconds": round(duration_seconds, 3),
            "source": "user supplied auto_attack_uptime",
            "assumptions": [
                "Movement, target access, and execution are outside this input."
            ],
        }
    if mode != AUTO_ATTACK_UPTIME_MODE_CALCULATED:
        raise ValueError(f"unsupported auto_attack_uptime_mode: {mode}")

    order = list(cast_order or ["Q", "W", "E", "R"])
    components: list[dict[str, Any]] = []
    lockout = 0.0
    unknown: list[str] = []
    for slot in order:
        if slot not in ability_damages:
            # An unranked spell is not part of this rotation.  Do not turn a
            # level-one champion into an "unknown" fight merely because its
            # later-rank slots are absent from the parsed package.
            continue
        value, source = _source_cast_time(champion_data, ability_damages, slot)
        if value is None:
            unknown.append(f"{slot}: {source}")
            continue
        lockout += value
        components.append(
            {"slot": slot, "cast_time_seconds": round(value, 6), "source": source}
        )

    if unknown:
        return 0.0, {
            "mode": mode,
            "status": "unknown",
            "uptime": None,
            "window_seconds": round(duration_seconds, 3),
            "source": "cached champion ability data",
            "components": components,
            "unknown_reasons": unknown,
            "assumptions": [
                "Real movement and target access are not inferred.",
                "The engine withholds auto damage when the cast-time receipt is incomplete.",
            ],
        }

    window = max(0.001, float(duration_seconds))
    # Treat the sourced Q/W/E/R lockout as a repeatable rotation cadence.  This
    # keeps one and six rotations on the same policy instead of turning a
    # longer window into an arbitrary extra uptime assumption.
    rotations = max(1.0, window / AUTO_ATTACK_UPTIME_POLICY_WINDOW_SECONDS)
    occupied = min(window, lockout * rotations)
    uptime = max(0.0, min(1.0, (window - occupied) / window))
    return uptime, {
        "mode": mode,
        "status": "calculated",
        "uptime": round(uptime, 6),
        "window_seconds": round(window, 3),
        "policy_window_seconds": AUTO_ATTACK_UPTIME_POLICY_WINDOW_SECONDS,
        "occupied_cast_seconds": round(occupied, 6),
        "components": components,
        "source": "reviewed module or cached ability castTime",
        "assumptions": [
            "One sourced Q/W/E/R cast sequence repeats at the policy cadence.",
            "Movement, target access, attack windup, and player execution are not inferred.",
            "This is action-window availability, not observed in-game uptime.",
        ],
        "rotation_mode": "one_rotation" if one_rotation else "time_based",
    }
