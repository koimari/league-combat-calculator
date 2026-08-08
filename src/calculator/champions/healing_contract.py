"""Typed declarations for champion-owned healing behavior."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any


@dataclass(frozen=True, slots=True)
class ChampionHealingRule:
    """One champion module's self-healing declaration."""

    champion_name: str
    resolver: Callable[..., list[dict[str, Any]]] | None = None

    def derive(
        self,
        champion_data: dict[str, Any],
        champion_stats: dict[str, float],
        ability_damages: dict[str, dict[str, Any]],
        damage_events: list[dict[str, Any]],
        cast_timeline: list[dict[str, Any]] | None = None,
        fight_duration_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve this declaration through the shared rule interface."""
        if self.resolver is not None:
            return self.resolver(
                champion_data,
                champion_stats,
                ability_damages,
                damage_events,
                cast_timeline,
                fight_duration_seconds,
            )

        from .healing_rules import derive_rule

        return derive_rule(
            self.champion_name,
            champion_data,
            champion_stats,
            ability_damages,
            damage_events,
            cast_timeline,
            fight_duration_seconds,
        )


def declare_healing_rule(
    champion_name: str,
    resolver: Callable[..., list[dict[str, Any]]] | None = None,
) -> ChampionHealingRule:
    """Declare the self-healing rule owned by a champion module."""
    return ChampionHealingRule(champion_name=champion_name, resolver=resolver)
