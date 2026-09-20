"""Typed declarations for champion-owned healing behavior."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import healing_helpers as _healing


def heal_receipt_order(event: dict[str, Any]) -> tuple[float, str]:
    """The order a self-heal ledger is read in: by time, then by source."""
    return (event["time"], event["source"])


@dataclass(frozen=True, slots=True)
class SelfHealCtx:
    """Everything a champion's self-heal resolver is handed.

    The record is the rule interface, so a resolver names the fields its kit
    reads instead of restating six positional parameters.
    """

    champion_data: dict[str, Any]
    champion_stats: dict[str, float]
    ability_damages: dict[str, dict[str, Any]]
    damage_events: list[dict[str, Any]]
    cast_timeline: list[dict[str, Any]] | None = None
    fight_duration_seconds: float | None = None

    def payments(
        self, anchor: _healing.HealAnchor, source: _healing.HealSource
    ) -> list[_healing.Payment]:
        """The occasions a rule over this ledger pays on."""
        return _healing.payments(anchor, source, self.damage_events, self.cast_timeline)

    def ranked_rows(self, slot: str, *attributes: str) -> tuple[float, ...]:
        """One slot's named rows at the rank this parse used."""
        return _healing.ranked_rows(
            self.champion_data,
            self.ability_damages,
            self.champion_stats,
            slot,
            *attributes,
        )


SelfHealResolver = Callable[[SelfHealCtx], list[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ChampionHealingRule:
    """One champion module's self-healing declaration."""

    champion_name: str
    resolver: SelfHealResolver | None = None

    def derive(self, ctx: SelfHealCtx) -> list[dict[str, Any]]:
        """Resolve this declaration through the shared rule interface."""
        if self.resolver is None:
            raise RuntimeError(
                f"{self.champion_name} has no champion-local healing resolver"
            )
        return self.resolver(ctx)


def declare_healing_rule(
    champion_name: str,
    resolver: SelfHealResolver,
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
) -> Callable[[SelfHealResolver], ChampionHealingRule]:
    """Declare a champion module's self-heal rule from its own resolver.

    The declaration owns the receipt order, so a module writes only the
    formula its kit needs and every rule hands back one ordered ledger:

        SELF_HEALING_RULE = self_healing_rule("Nami")(derive_self_healing)
    """

    def declare(resolver: SelfHealResolver) -> ChampionHealingRule:
        @functools.wraps(resolver)
        def ordered(ctx: SelfHealCtx) -> list[dict[str, Any]]:
            return sorted(resolver(ctx), key=heal_receipt_order)

        return declare_healing_rule(champion_name, ordered)

    return declare
