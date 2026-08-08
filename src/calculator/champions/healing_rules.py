"""Registered champion healing rules.

The declarations live in each champion module. The compatibility resolver
keeps the reviewed formula implementation stable while the formulas move
into their owning modules in small, tested slices.
"""

from __future__ import annotations

from typing import Any

from ..healing_legacy import _legacy_derive_self_healing


def derive_rule(
    champion_name: str,
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Apply the registered rule for one declared champion."""
    del champion_name
    return _legacy_derive_self_healing(
        champion_data,
        champion_stats,
        ability_damages,
        damage_events,
        cast_timeline,
        fight_duration_seconds,
    )
