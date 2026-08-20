"""Typed declarations for champion-owned healing behavior."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from ..healing_legacy import HEALING_RULE_CHAMPIONS, _legacy_derive_self_healing


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

        return _legacy_derive_self_healing(
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
    """Declare the self-healing rule owned by a champion module.

    ``healing._load_declarations`` walks the registry and demands a
    declaration from every named champion; this is the other direction.  A
    module that declares a rule the registry does not know would otherwise
    import clean and never heal, so the declaration fails closed here.
    """
    if champion_name not in HEALING_RULE_CHAMPIONS:
        raise RuntimeError(
            f"{champion_name!r} declares SELF_HEALING_RULE but is absent from "
            "healing_legacy.HEALING_RULE_CHAMPIONS"
        )
    return ChampionHealingRule(champion_name=champion_name, resolver=resolver)
