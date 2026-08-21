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
        if self.resolver is None:
            raise RuntimeError(
                f"{self.champion_name} has no champion-local healing resolver"
            )
        return self.resolver(
            champion_data,
            champion_stats,
            ability_damages,
            damage_events,
            cast_timeline,
            fight_duration_seconds,
        )


def declare_healing_rule(
    champion_name: str,
    resolver: Callable[..., list[dict[str, Any]]],
) -> ChampionHealingRule:
    """Declare the self-healing rule owned by a champion module.

    The resolver is the declaration: there is no shared body left to fall
    back to, so a module that declares a rule without one would import
    clean and never heal.  ``healing._load_declarations`` derives
    ``HEALING_RULE_CHAMPIONS`` from these declarations, so the champion
    set has no second home to drift from.
    """
    if resolver is None:
        raise RuntimeError(
            f"{champion_name!r} declares SELF_HEALING_RULE without a resolver"
        )
    return ChampionHealingRule(champion_name=champion_name, resolver=resolver)
