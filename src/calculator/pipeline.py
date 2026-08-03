"""Shared entry point for a complete champion fight calculation.

Consumers provide already-loaded champion and item data. This module owns the
cross-domain orchestration from stats through champion ability parsing into the
champion-agnostic fight engine; data fetching remains with each consumer.
"""

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .champions import (
    RESERVED_OPTION_KEYS,
    get_champion_cast_order,
    get_custom_cast_order_unavailable_reason,
    get_supported_fight_modes,
    get_unsupported_fight_mode_reason,
    parse_champion_abilities,
)
from .champions.skill_orders import get_ability_rank
from .damage import (
    FightConfig,
    calculate_fight_damage,
    split_auto_vs_ability,
    split_by_damage_type,
)
from .item_effects import resolve_damage_effects, validate_item_input_options
from .healing import derive_self_healing
from .role_quests import max_champion_level, validate_role
from .rune_effects import validate_keystone_request
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
PUBLIC_INPUT_LIMITS: dict[str, tuple[float, float]] = {
    "fight_duration": (1.0, 10.0),
    "auto_attack_uptime": (0.0, 1.0),
    "target_health": (1.0, 10_000.0),
    "target_bonus_health": (0.0, 10_000.0),
    "target_armor": (0.0, 500.0),
    "target_mr": (0.0, 500.0),
}
_PUBLIC_FIGHT_MODES = frozenset({"one_rotation", "time_based", "timed", "auto_only"})
_NONSTANDARD_RANK_CHAMPIONS = frozenset({"Elise", "Jayce", "Karma", "Nidalee", "Udyr"})


def _bounded_request_float(data: Mapping[str, Any], key: str, default: float) -> float:
    """Parse one finite public number inside its UI-supported range."""
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")

    minimum, maximum = PUBLIC_INPUT_LIMITS[key]
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
    return parsed


def _request_bool(data: Mapping[str, Any], key: str, default: bool) -> bool:
    """Parse a JSON boolean without treating non-empty strings as true."""
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


@dataclass(frozen=True)
class FightParams(FightConfig):
    """FightConfig plus the parse-layer inputs the engine never sees.

    The engine's typed contract is :class:`FightConfig`; ``run_fight``
    passes a ``FightParams`` straight through because it IS one.
    """

    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
    item_options: dict[str, dict[str, int]] | None = None
    role: str = ""
    role_quest_complete: bool = False
    ally_stat_bonuses: dict[str, float] | None = None

    @classmethod
    def from_request(
        cls,
        data: Mapping[str, Any],
        *,
        deterministic: bool = False,
    ) -> "FightParams":
        """Parse request-shaped values and resolve fight-mode semantics once."""
        fight_mode = data.get("fight_mode", DEFAULT_FIGHT_MODE)
        if not isinstance(fight_mode, str) or fight_mode not in _PUBLIC_FIGHT_MODES:
            raise ValueError(
                "fight_mode must be one_rotation, time_based, timed, or auto_only"
            )
        one_rotation = fight_mode == "one_rotation"
        auto_attacks_only = _request_bool(data, "auto_attacks_only", False)
        requested_duration = _bounded_request_float(
            data, "fight_duration", DEFAULT_FIGHT_DURATION
        )
        requested_uptime = _bounded_request_float(
            data, "auto_attack_uptime", DEFAULT_AUTO_ATTACK_UPTIME
        )

        if one_rotation:
            duration = ONE_ROTATION_DURATION
            uptime = 0.0
        else:
            duration = requested_duration
            include_autos = _request_bool(data, "include_auto_attacks", False)
            uptime = requested_uptime if include_autos or auto_attacks_only else 0.0

        ability_ranks = data.get("ability_ranks")
        if ability_ranks is not None and not isinstance(ability_ranks, Mapping):
            raise ValueError("ability_ranks must be an object")
        champion_options = data.get("champion_options")
        if champion_options is not None and not isinstance(champion_options, Mapping):
            raise ValueError("champion_options must be an object")
        item_options = validate_item_input_options(data.get("item_options"))
        keystone = validate_keystone_request(data.get("keystone"))
        role = validate_role(data.get("role", ""))
        role_quest_complete = _request_bool(data, "role_quest_complete", False)
        if role_quest_complete and not role:
            raise ValueError("role is required when role_quest_complete is true")

        params = cls(
            target_health=_bounded_request_float(
                data, "target_health", DEFAULT_TARGET["health"]
            ),
            target_bonus_health=_bounded_request_float(
                data, "target_bonus_health", DEFAULT_TARGET["bonus_health"]
            ),
            target_armor=_bounded_request_float(
                data, "target_armor", DEFAULT_TARGET["armor"]
            ),
            target_magic_resistance=_bounded_request_float(
                data, "target_mr", DEFAULT_TARGET["mr"]
            ),
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            include_actives=_request_bool(data, "include_actives", True),
            cast_order=data.get("cast_order"),
            auto_attacks_only=auto_attacks_only,
            ability_ranks=dict(ability_ranks) if ability_ranks is not None else None,
            champion_options=(
                dict(champion_options) if champion_options is not None else None
            ),
            item_options=item_options or None,
            keystone=keystone,
            role=role,
            role_quest_complete=role_quest_complete,
            deterministic=deterministic,
        )
        params._validate_request_values()
        return params

    def _validate_request_values(self) -> None:
        """Reject malformed cast orders and ability ranks for every consumer."""
        if self.cast_order is not None:
            if not isinstance(self.cast_order, list) or any(
                not isinstance(key, str) for key in self.cast_order
            ):
                raise ValueError("Cast order must be a permutation of Q, W, E, R")
            if sorted(self.cast_order) != ["E", "Q", "R", "W"]:
                raise ValueError("Cast order must be a permutation of Q, W, E, R")

        if not self.ability_ranks:
            return
        unknown_keys = set(self.ability_ranks) - {"Q", "W", "E", "R"}
        if unknown_keys:
            raise ValueError(
                f"Unknown ability rank keys: {', '.join(sorted(unknown_keys))}"
            )
        for key in ("Q", "W", "E"):
            value = self.ability_ranks.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} rank must be an integer")
            if value < 0 or value > 5:
                raise ValueError(f"{key} rank must be 0-5")
        ultimate_rank = self.ability_ranks.get("R", 0)
        if isinstance(ultimate_rank, bool) or not isinstance(ultimate_rank, int):
            raise ValueError("R rank must be an integer")
        if ultimate_rank < 0 or ultimate_rank > 3:
            raise ValueError("R rank must be 0-3")

    def target_stats(self) -> dict[str, float]:
        """Build the champion-parser target context for a full-health target."""
        return {
            "target_max_health": self.target_health,
            "target_current_health": self.target_health,
            "target_missing_health": 0.0,
            "roster_target_index": float(self.roster_target_index),
            "roster_target_count": float(self.roster_target_count),
        }

    def validate_for_champion(self, champion_name: str, level: int) -> None:
        """Reject a rank allocation that cannot exist at ``level``.

        Rank-free requests use the champion's sourced default order. Manual
        allocations are accepted only for the standard five-rank basic and
        three-rank ultimate layout. Transformation and auto-levelled kits fail
        closed until their individual allocation rules are represented.
        """
        if level > max_champion_level(self.role, self.role_quest_complete):
            raise ValueError(f"Level {level} requires the completed top role quest")
        require_fight_mode_support(self, champion_name)

        custom_order_reason = get_custom_cast_order_unavailable_reason(champion_name)
        if self.cast_order is not None and custom_order_reason is not None:
            raise ValueError(custom_order_reason)

        if self.ability_ranks is None:
            return
        if champion_name in _NONSTANDARD_RANK_CHAMPIONS:
            raise ValueError(
                f"Manual ability ranks are unavailable for {champion_name}; "
                "use the level-derived ranks"
            )

        effective = {
            key: self.ability_ranks.get(
                key, get_ability_rank(key, level, champion_name)
            )
            for key in ("Q", "W", "E", "R")
        }
        for key in ("Q", "W", "E"):
            rank = effective[key]
            minimum_level = max(1, 2 * rank - 1) if rank else 0
            if rank and level < minimum_level:
                raise ValueError(
                    f"{key} rank {rank} requires champion level {minimum_level}"
                )
        ultimate_rank = effective["R"]
        minimum_ultimate_level = (0, 6, 11, 16)[ultimate_rank]
        if ultimate_rank and level < minimum_ultimate_level:
            raise ValueError(
                f"R rank {ultimate_rank} requires champion level "
                f"{minimum_ultimate_level}"
            )
        if sum(effective.values()) > min(level, 18):
            raise ValueError(
                "Ability ranks spend more skill points than the champion level allows"
            )


def require_fight_mode_support(params: "FightParams", champion_name: str) -> None:
    """Reject a fight mode the champion's certified module cannot run.

    The one home for the mode rule: ``validate_for_champion`` applies it to
    the main attacker, and the participant timeline applies it to every
    roster member it will run as an attacker.
    """
    supported_modes = get_supported_fight_modes(champion_name)
    requested_mode = (
        "one_rotation"
        if params.one_rotation
        else ("auto_only" if params.auto_attacks_only else "time_based")
    )
    if supported_modes is not None and requested_mode not in supported_modes:
        reason = get_unsupported_fight_mode_reason(champion_name)
        raise ValueError(
            reason or f"{requested_mode} is not certified for {champion_name}"
        )


def run_fight(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    params: FightParams,
) -> dict[str, Any]:
    """Run stats, champion ability parsing, and fight damage as one pipeline."""
    params.validate_for_champion(champion_data.get("name", ""), level)
    champion_stats = calculate_total_stats(
        champion_data,
        level,
        items,
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )

    # Reserved option keys are pipeline-owned: strip whatever the caller
    # sent, then hand timed fights the fight window and auto uptime so
    # duration/timeline-driven champion mechanics (Aurelion Sol's
    # continuous Q channel, Braum's passive stack cycle) can scale with
    # them. One-rotation mode keeps the per-cast ability models.
    champion_options = dict(params.champion_options or {})
    for reserved_key in RESERVED_OPTION_KEYS:
        champion_options.pop(reserved_key, None)
    if not params.one_rotation:
        champion_options["fight_duration_seconds"] = params.fight_duration_seconds
        champion_options["auto_attack_uptime"] = params.auto_attack_uptime

    # Champion mechanics priced in crit at parse time (Caitlyn's Headshot
    # rider) need the build's bonus crit damage above the 2.0 base
    # (Infinity Edge's +0.3). It lives in the items' DamageEffects — the
    # same value the fight engine folds into its crit multiplier — so
    # surface it to the parse context only, keeping the reported
    # champion_stats panel item-stats-only.
    parse_stats = dict(champion_stats)
    parse_stats["crit_damage_bonus"] = resolve_damage_effects(items).crit_damage_bonus

    ability_damages = parse_champion_abilities(
        champion_data,
        level,
        champion_stats["ability_power"],
        ability_ranks=params.ability_ranks,
        champion_stats=parse_stats,
        target_stats=params.target_stats(),
        champion_options=champion_options,
    )
    if params.target_threshold_health_bonus > 0 and any(
        ability.get("target_max_health_sensitive", False)
        for ability in ability_damages.values()
    ):
        raise ValueError(
            "This damage package scales from target maximum health and cannot "
            "yet be certified against Protoplasm Harness's temporary maximum-"
            "health change. Remove Protoplasm or choose another attacker."
        )

    # The fight engine applies ability stat buffs (Mega Gnar's form
    # stats, Vayne/Aatrox R, ...) to this copy in place — report THESE
    # as the champion's stats so the UI panel shows the fight-effective
    # values, not the pre-buff base+items snapshot.
    fight_stats = dict(champion_stats)
    # A champion may declare its own rotation order (Jayce transforms
    # before he casts). An explicit caller-supplied order still wins.
    if params.cast_order is None:
        declared = get_champion_cast_order(champion_data.get("name", ""))
        if declared is not None:
            params = replace(params, cast_order=declared)
    result = calculate_fight_damage(
        fight_stats,
        ability_damages,
        items,
        replace(params, enforce_resource_limits=True),
    )
    result["champion_stats"] = fight_stats
    result["self_healing_events"] = derive_self_healing(
        champion_data,
        fight_stats,
        ability_damages,
        list(result.get("damage_events", [])),
        list(result.get("cast_timeline", [])),
        params.fight_duration_seconds,
    )
    result["self_healing"] = sum(
        float(event.get("amount", 0.0)) for event in result["self_healing_events"]
    )
    auto_damage, ability_damage = split_auto_vs_ability(result["breakdown"])
    result["auto_attack_damage"] = auto_damage
    result["ability_damage"] = ability_damage
    result["damage_by_type"] = split_by_damage_type(result["breakdown"])
    return result
