"""Retired compatibility entrypoint for champion healing formulas."""

from __future__ import annotations

from typing import Any


def derive_rule(
    champion_name: str,
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Fail closed when a caller asks for the retired global dispatcher."""
    del (
        champion_name,
        champion_data,
        champion_stats,
        ability_damages,
        damage_events,
        cast_timeline,
        fight_duration_seconds,
    )
    raise RuntimeError("champion healing must be owned by a champion module")
