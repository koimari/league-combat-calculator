"""Typed roster composition primitives used by the participant timeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, replace
import math
from typing import TYPE_CHECKING, Any

from .item_effects import required_effect_value, sustain_effect_value
from .pipeline import FightParams, require_fight_mode_support

if TYPE_CHECKING:
    from .scenario import ResolvedLoadout


@dataclass(frozen=True, slots=True)
class Combatant:  # pylint: disable=too-many-instance-attributes
    """One participant with its resolved stats and build."""

    participant_id: str
    team: str
    champion_data: dict[str, Any]
    level: int
    items: tuple[dict[str, Any], ...]
    stats: dict[str, float]
    defenses: Any
    request: Any = None


def require_roster_fight_window_support(
    params: FightParams,
    *,
    enemies: Iterable[ResolvedLoadout] = (),
    allies: Iterable[ResolvedLoadout] = (),
) -> None:
    """Reject a fight window a selected roster member cannot join."""
    for side, roster in (("Enemy", enemies), ("Ally", allies)):
        for loadout in roster:
            name = str(loadout.champion_data.get("name", ""))
            try:
                require_fight_mode_support(params, name)
            except ValueError as exc:
                raise ValueError(
                    f"{side} {name} cannot join this fight window: {exc}"
                ) from exc


def coalesce_darius_q_heals(
    healing: MutableMapping[str, list[dict[str, Any]]],
) -> None:
    """Combine Darius Q pair receipts into one live heal per cast."""
    for events in healing.values():
        groups: dict[tuple[float, int], tuple[int, int]] = {}
        kept: list[dict[str, Any]] = []
        for event in events:
            marker = event.get("_darius_q_group")
            if not isinstance(marker, tuple) or len(marker) != 2:
                kept.append(event)
                continue
            key = (float(marker[0]), int(marker[1]))
            first = groups.get(key)
            if first is None:
                groups[key] = (len(kept), 1)
                kept.append(event)
            else:
                groups[key] = (first[0], first[1] + 1)
        for index, count in groups.values():
            kept[index] = {
                **kept[index],
                "amount_formula": (
                    lambda current_health, maximum_health, count=count: (
                        max(0.0, maximum_health - current_health)
                        * min(0.51, 0.17 * count)
                    )
                ),
            }
        events[:] = kept


def from_loadout(
    participant_id: str,
    team: str,
    loadout: ResolvedLoadout,
) -> Combatant:
    """Create a typed roster participant from one resolved loadout."""
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data=loadout.champion_data,
        level=loadout.request.level,
        items=loadout.item_data,
        stats=loadout.stats,
        defenses=loadout.defenses,
        request=loadout.request,
    )


def main_combatant(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    *,
    stats: dict[str, float],
    defenses: Any,
    params: FightParams,
) -> Combatant:
    """Create the selected main champion's roster participant."""
    return Combatant(
        participant_id="main",
        team="main",
        champion_data=champion_data,
        level=level,
        items=tuple(items),
        stats=stats,
        defenses=defenses,
        request=type(
            "MainRequest",
            (),
            {
                "role": params.role,
                "role_quest_complete": params.role_quest_complete,
                "ability_ranks": params.ability_ranks,
                "champion_options": params.champion_options,
                "cast_order": params.cast_order,
                "item_options": params.item_options,
            },
        )(),
    )


def actor_params(base: FightParams, actor: Combatant) -> FightParams:
    """Use a roster actor's role while preserving the selected fight window."""
    request = actor.request
    return replace(
        base,
        role=getattr(request, "role", "") or "",
        role_quest_complete=bool(getattr(request, "role_quest_complete", False)),
        ability_ranks=getattr(request, "ability_ranks", None) or None,
        champion_options=getattr(request, "champion_options", None),
        cast_order=getattr(request, "cast_order", None),
        item_options=getattr(request, "item_options", None),
        ally_stat_bonuses=None,
    )


def target_overrides(defender: Combatant) -> dict[str, float | str]:
    """Return every target field read by a one-pair fight."""
    defenses = defender.defenses
    attack_speed_multiplier = 1.0
    if any(item.get("name") == "Frozen Heart" for item in defender.items):
        attack_speed_multiplier = 1.0 - float(
            required_effect_value("Frozen Heart", "attack_speed_reduction")
        )
    return {
        "target_health": float(defender.stats.get("health", 0.0)),
        "target_bonus_health": float(defender.stats.get("bonus_health", 0.0)),
        "target_armor": float(defender.stats.get("armor", 0.0)),
        "target_magic_resistance": float(defender.stats.get("magic_resistance", 0.0)),
        "target_magic_shield": float(defenses.magic_shield),
        "target_physical_shield": float(defenses.physical_shield),
        "target_general_shield": float(defenses.general_shield),
        "target_basic_damage_multiplier": float(defenses.basic_damage_multiplier),
        "target_basic_damage_flat_reduction": float(
            defenses.basic_damage_flat_reduction
        ),
        "target_basic_damage_flat_reduction_cap": float(
            defenses.basic_damage_flat_reduction_cap
        ),
        "target_critical_strike_damage_multiplier": float(
            defenses.critical_strike_damage_multiplier
        ),
        "attacker_attack_speed_multiplier": attack_speed_multiplier,
        "target_threshold_shield_amount": float(defenses.threshold_shield_amount),
        "target_threshold_shield_health_ratio": float(
            defenses.threshold_shield_health_ratio
        ),
        "target_threshold_shield_duration": float(defenses.threshold_shield_duration),
        "target_threshold_shield_damage_type": str(
            defenses.threshold_shield_damage_type
        ),
        "target_threshold_health_bonus": float(defenses.threshold_health_bonus),
        "target_threshold_health_heal": float(defenses.threshold_health_heal),
        "target_threshold_health_ratio": float(defenses.threshold_health_ratio),
        "target_threshold_health_duration": float(defenses.threshold_health_duration),
        "target_revive_health_amount": float(defenses.revive_health_amount),
        "target_revive_delay": float(defenses.revive_delay),
        "target_revive_cooldown": float(defenses.revive_cooldown),
    }


def target_params(base: FightParams, defender: Combatant) -> FightParams:
    """Apply one defender's typed fields to a pair fight."""
    return replace(base, **target_overrides(defender))


def defensive_signature(defender: Combatant) -> tuple[Any, ...]:
    """Return a hashable signature for the target override fields."""
    return tuple(target_overrides(defender).values())


def has_catalyst(items: Iterable[Mapping[str, Any]]) -> bool:
    """Return whether a participant owns Catalyst's ordered resource passive."""
    return any(str(item.get("name", "")) == "Catalyst of Aeons" for item in items)


def catalyst_resource_restores(
    actor: Combatant,
    incoming: Mapping[str, Iterable[Mapping[str, Any]]],
    duration: float,
) -> tuple[tuple[tuple[float, float], ...], bool]:
    """Derive Catalyst restores from complete incoming champion packets."""
    if not has_catalyst(actor.items):
        return (), True
    ratio = sustain_effect_value("Catalyst of Aeons", "damage_taken_to_mana_ratio")
    restores: list[tuple[float, float]] = []
    for event in incoming.get(actor.participant_id, ()):
        if not isinstance(event, Mapping):
            continue
        source_id = str(event.get("attacker", ""))
        if not source_id or source_id == actor.participant_id:
            continue
        if event.get("_reactive") or event.get("_deferred"):
            continue
        try:
            event_time = float(event.get("time", 0.0))
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            return (), False
        if (
            not math.isfinite(event_time)
            or not math.isfinite(raw_damage)
            or event_time < 0.0
            or event_time > duration + 1e-9
        ):
            return (), False
        if raw_damage <= 0.0:
            continue
        amount = raw_damage * ratio
        if amount > 0.0:
            restores.append((event_time, amount))
    restores.sort(key=lambda row: row[0])
    return tuple(restores), True


def actor_params_with_resource_restores(
    base: FightParams,
    actor: Combatant,
    resource_restores: Mapping[str, tuple[tuple[float, float], ...]] | None,
) -> FightParams:
    """Attach one actor's typed external resource ledger to its fight params."""
    params = actor_params(base, actor)
    if resource_restores is None:
        return params
    return replace(
        params,
        resource_restore_events=tuple(resource_restores.get(actor.participant_id, ())),
    )
