"""Typed declarations for champion-owned healing behavior."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


def heal_receipt_order(event: dict[str, Any]) -> tuple[float, str]:
    """The order a self-heal ledger is read in: by time, then by source."""
    return (event["time"], event["source"])


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

    The resolver is the declaration, so a module declaring one without it would
    import clean and never heal.  ``HEALING_RULE_CHAMPIONS`` derives from these.
    """
    if resolver is None:
        raise RuntimeError(
            f"{champion_name!r} declares SELF_HEALING_RULE without a resolver"
        )
    return ChampionHealingRule(champion_name=champion_name, resolver=resolver)


def self_healing_rule(
    champion_name: str,
) -> Callable[[Callable[..., list[dict[str, Any]]]], ChampionHealingRule]:
    """Declare a champion module's self-heal rule from its own resolver.

    The declaration owns the receipt order, so a module writes only the
    formula its kit needs and every rule hands back one ordered ledger:

        SELF_HEALING_RULE = self_healing_rule("Nami")(derive_self_healing)
    """

    def declare(resolver: Callable[..., list[dict[str, Any]]]) -> ChampionHealingRule:
        @functools.wraps(resolver)
        def ordered(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return sorted(resolver(*args, **kwargs), key=heal_receipt_order)

        return declare_healing_rule(champion_name, ordered)

    return declare
