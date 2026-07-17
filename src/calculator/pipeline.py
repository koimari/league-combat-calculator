"""Shared entry point for a complete champion fight calculation.

Consumers provide already-loaded champion and item data. This module owns the
cross-domain orchestration from stats through champion ability parsing into the
champion-agnostic fight engine; data fetching remains with each consumer.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from .champions import parse_champion_abilities
from .damage import calculate_fight_damage
from .stats import calculate_total_stats

DEFAULT_TARGET: dict[str, float] = {
    "health": 1000.0,
    "bonus_health": 0.0,
    "armor": 100.0,
    "mr": 100.0,
}
DEFAULT_FIGHT_DURATION = 8.0
DEFAULT_AUTO_ATTACK_UPTIME = 0.8
DEFAULT_FIGHT_MODE = "one_rotation"
ONE_ROTATION_DURATION = 5.0


@dataclass(frozen=True)
class FightParams:
    """Resolved configuration shared by every complete fight-pipeline caller."""

    target_health: float
    target_bonus_health: float
    target_armor: float
    target_magic_resistance: float
    fight_duration_seconds: float
    auto_attack_uptime: float
    one_rotation: bool
    include_actives: bool
    cast_order: list[str] | None
    auto_attacks_only: bool
    ability_ranks: dict[str, int] | None
    champion_options: dict[str, Any] | None
    deterministic: bool = False

    @classmethod
    def from_request(
        cls,
        data: Mapping[str, Any],
        *,
        deterministic: bool = False,
    ) -> "FightParams":
        """Parse request-shaped values and resolve fight-mode semantics once."""
        fight_mode = data.get("fight_mode", DEFAULT_FIGHT_MODE)
        one_rotation = fight_mode == "one_rotation"
        auto_attacks_only = bool(data.get("auto_attacks_only", False))
        requested_duration = float(data.get("fight_duration", DEFAULT_FIGHT_DURATION))
        requested_uptime = float(
            data.get("auto_attack_uptime", DEFAULT_AUTO_ATTACK_UPTIME)
        )

        if one_rotation:
            duration = ONE_ROTATION_DURATION
            uptime = 0.0
        else:
            duration = requested_duration
            include_autos = bool(data.get("include_auto_attacks", False))
            uptime = requested_uptime if include_autos or auto_attacks_only else 0.0

        params = cls(
            target_health=float(data.get("target_health", DEFAULT_TARGET["health"])),
            target_bonus_health=float(
                data.get("target_bonus_health", DEFAULT_TARGET["bonus_health"])
            ),
            target_armor=float(data.get("target_armor", DEFAULT_TARGET["armor"])),
            target_magic_resistance=float(data.get("target_mr", DEFAULT_TARGET["mr"])),
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            include_actives=bool(data.get("include_actives", True)),
            cast_order=data.get("cast_order"),
            auto_attacks_only=auto_attacks_only,
            ability_ranks=data.get("ability_ranks"),
            champion_options=data.get("champion_options"),
            deterministic=deterministic,
        )
        params._validate_request_values()
        return params

    def _validate_request_values(self) -> None:
        """Reject malformed cast orders and ability ranks for every consumer."""
        if self.cast_order is not None and sorted(self.cast_order) != [
            "E",
            "Q",
            "R",
            "W",
        ]:
            raise ValueError("Cast order must be a permutation of Q, W, E, R")

        if not self.ability_ranks:
            return
        for key in ("Q", "W", "E"):
            value = self.ability_ranks.get(key, 0)
            if value < 0 or value > 5:
                raise ValueError(f"{key} rank must be 0-5")
        ultimate_rank = self.ability_ranks.get("R", 0)
        if ultimate_rank < 0 or ultimate_rank > 3:
            raise ValueError("R rank must be 0-3")

    def target_stats(self) -> dict[str, float]:
        """Build the champion-parser target context for a full-health target."""
        return {
            "target_max_health": self.target_health,
            "target_current_health": self.target_health,
            "target_missing_health": 0.0,
        }


def run_fight(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
) -> dict[str, Any]:
    """Run stats, champion ability parsing, and fight damage as one pipeline."""
    champion_stats = calculate_total_stats(champion_data, level, items)
    ability_damages = parse_champion_abilities(
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=params.ability_ranks,
        champion_stats=champion_stats,
        target_stats=params.target_stats(),
        champion_options=params.champion_options,
    )

    result = calculate_fight_damage(
        champion_stats=dict(champion_stats),
        ability_damages=ability_damages,
        target_health=params.target_health,
        target_bonus_health=params.target_bonus_health,
        target_armor=params.target_armor,
        target_magic_resistance=params.target_magic_resistance,
        fight_duration_seconds=params.fight_duration_seconds,
        auto_attack_uptime=params.auto_attack_uptime,
        ability_haste=champion_stats.get("ability_haste", 0.0),
        items=items,
        one_rotation=params.one_rotation,
        include_actives=params.include_actives,
        cast_order=params.cast_order,
        auto_attacks_only=params.auto_attacks_only,
        deterministic=params.deterministic,
    )
    result["champion_stats"] = champion_stats
    return result
