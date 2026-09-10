"""Grasp, Hail of Blades, Lethal Tempo and Fleet: keystones that own or ride the swing schedule."""

from collections.abc import Mapping
from typing import Any

from ... import rune_effects
from ...item_behavior import PacketKind
from ...survival.phases import TransitionRank
from ..autos.swing_schedule import (
    _auto_attack_timestamps,
    _HailStacks,
    _lethal_tempo_attack_schedule,
)
from ..config import declared_option_default
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState, _damage_inputs
from .streams import _rune_instance_times


def _grasp_proc_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, float | int]]:
    """Walk Grasp's timed combat stacks over the authored attack timeline.

    A combat entry starts one stack cycle. The first stack arrives after the
    sourced cadence, four stacks complete the cycle, and the next basic
    attack consumes them inside the sourced ready window. After a consume,
    the next cycle starts from that attack while combat continues.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneGraspEffect):
        return []
    attack_times = _auto_attack_timestamps(state)
    if not attack_times:
        return []
    combat_times = _rune_instance_times(state, rotation)
    if not combat_times:
        return []
    cadence = effect.stack_cadence_seconds
    generation = effect.stack_generation_seconds
    if cadence <= 0.0 or generation < 0.0 or effect.max_stacks <= 0:
        return []

    stack_count = 0
    next_stack_time = combat_times[0] + cadence
    last_combat_time = combat_times[0]
    ready_until = float("-inf")
    proc_events: list[dict[str, float | int]] = []
    for attack_time in attack_times:
        combat_at_attack = [
            combat_time for combat_time in combat_times if combat_time <= attack_time
        ]
        if combat_at_attack:
            latest_combat_time = combat_at_attack[-1]
            if latest_combat_time - last_combat_time > generation:
                stack_count = 0
                next_stack_time = latest_combat_time + cadence
            last_combat_time = latest_combat_time
        if stack_count >= effect.max_stacks and attack_time > ready_until + 1e-9:
            stack_count = 0
            next_stack_time = attack_time + cadence
        while (
            next_stack_time <= attack_time + 1e-9
            and next_stack_time <= last_combat_time + generation + 1e-9
            and stack_count < effect.max_stacks
        ):
            stack_count += 1
            if stack_count >= effect.max_stacks:
                ready_until = next_stack_time + effect.ready_window_seconds
            next_stack_time += cadence
        if stack_count >= effect.max_stacks and attack_time <= ready_until + 1e-9:
            proc_events.append(
                {
                    "time": attack_time,
                    "trigger_time": attack_time,
                    "stacks": effect.max_stacks,
                }
            )
            stack_count = 0
            next_stack_time = attack_time + cadence
            ready_until = float("-inf")
    return proc_events


def _add_keystone_grasp_damage(state: FightState, rotation: RotationResult) -> None:
    """Add Grasp's empowered basic attacks and sourced self-heal receipts."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneGraspEffect):
        return
    proc_events = _grasp_proc_events(state, rotation)
    if not proc_events:
        state.notes.append(
            f"{effect.rune_name} never procced: the authored basic-attack "
            f"timeline did not reach {effect.max_stacks} combat stacks."
        )
        return

    stats = state.champion_stats
    damage_type = "magic"
    raw_health = float(stats["health"])
    raw_damage_events: list[dict[str, float | int | str]] = []
    heal_events: list[dict[str, float | str | bool]] = []
    bonus_health_events: list[dict[str, float | str]] = []
    total_damage = 0.0
    total_healing = 0.0
    total_bonus_health = 0.0
    for event in proc_events:
        raw_damage = effect.raw_damage({"health": raw_health}, state.is_melee)
        mitigated = _mitigate(raw_damage, damage_type, state.resists, state.magic_amp)
        heal_amount = effect.heal_amount({"health": raw_health}, state.is_melee)
        bonus_health = effect.bonus_health(state.is_melee)
        raw_damage_events.append(
            {
                "time": float(event["time"]),
                "trigger_time": float(event["trigger_time"]),
                "damage": mitigated,
                "raw_damage": raw_damage,
                "damage_type": damage_type,
                "stacks": int(event["stacks"]),
            }
        )
        heal_events.append(
            {
                "time": float(event["time"]),
                "amount": heal_amount,
                "trigger_source": "auto_attacks",
                "actor_wide": True,
            }
        )
        bonus_health_events.append(
            {
                "time": float(event["time"]),
                "amount": bonus_health,
                "source": effect.display_name,
                "kind": "permanent_bonus_health",
            }
        )
        total_damage += mitigated
        total_healing += heal_amount
        total_bonus_health += bonus_health
        raw_health += bonus_health

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(raw_damage_events),
        "event_phase": "effect",
        "damage_events": raw_damage_events,
        "permanent_health_gained": total_bonus_health,
        "permanent_health_events": bonus_health_events,
    }
    state.breakdown[f"heal_{effect.rune_name}"] = {
        "name": f"{effect.display_name} (self-heal)",
        "count": len(heal_events),
        "amount_per_proc": total_healing / len(heal_events),
        "total_amount": total_healing,
        "unit": "health",
        "heal_events": heal_events,
        "event_phase": "heal",
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.rune_name} procced {len(proc_events)} time(s) from "
        f"{effect.max_stacks} stacks, with a {effect.ready_window_seconds:g}-second "
        "ready window. Permanent health gains are applied in the ordered "
        "participant receipt."
    )


def _forced_basic_attack_times(
    state: FightState, rotation: RotationResult
) -> list[float]:
    """Return authored forced basic-attack times when no ambient stream exists."""
    if state.num_auto_attacks > 0 or rotation.forced_basic_attacks <= 0:
        return []
    times: list[float] = []
    for cast_event in rotation.cast_events:
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            continue
        row = state.breakdown.get(slot)
        if not isinstance(row, Mapping):
            continue
        authored = row.get("damage_events")
        if not isinstance(authored, list):
            continue
        for event in authored:
            if not isinstance(event, Mapping) or not event.get("basic_attack"):
                continue
            damage = float(event["damage"])
            if damage > 0.0:
                times.append(float(event["time"]))
    return sorted(times)


def _hail_active_for_forced_attacks(
    effect: "rune_effects.KeystoneHailOfBladesEffect", attack_times: list[float]
) -> tuple[list[int], list[float]]:
    """Walk Hail stacks over authored forced attacks."""
    active_indexes: list[int] = []
    hail = _HailStacks(effect)
    for index, attack_time in enumerate(attack_times):
        hail.expire(attack_time)
        hail.arm(attack_time)
        if hail.spend(attack_time):
            active_indexes.append(index)
    return active_indexes, hail.activation_times


def _add_keystone_hail_of_blades(state: FightState, rotation: RotationResult) -> None:
    """Add Hail's true-damage rider from the shared basic-attack stream."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.hail_attack_times:
        attack_times = _auto_attack_timestamps(state)
        active_indexes = list(state.hail_active_attack_indices)
        activation_times = list(state.hail_activation_times)
        carrier = "ambient basic attacks"
    elif forced_times:
        attack_times = forced_times
        active_indexes, activation_times = _hail_active_for_forced_attacks(
            effect, attack_times
        )
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.rune_name} never procced: the fight had no "
            "authored basic-attack landing."
        )
        return

    if not active_indexes:
        state.notes.append(
            f"{effect.rune_name} never procced: all authored basic attacks "
            f"landed outside its {effect.stack_duration_seconds:g}-second stack window."
        )
        return

    raw_damage = effect.raw_damage(_damage_inputs(state))
    if raw_damage <= 0.0:
        return
    damage_events = [
        {
            "time": attack_times[index],
            "damage": raw_damage,
            "raw_damage": raw_damage,
            "damage_type": "true",
            "basic_attack": True,
            "trigger_source": carrier,
        }
        for index in active_indexes
        if index < len(attack_times)
    ]
    if not damage_events:
        return
    total_damage = sum(float(event["damage"]) for event in damage_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": "true",
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "active_attack_indices": active_indexes,
        "activation_times": activation_times,
        "bonus_attack_speed_percent": effect.bonus_attack_speed_percent(state.is_melee),
        "initial_stacks": effect.initial_stacks,
        "reset_stack_limit": effect.reset_stack_limit,
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.rune_name} used {len(damage_events)} active basic attack(s) "
        f"from {carrier}. The sourced {effect.bonus_attack_speed_percent(state.is_melee):g}% "
        "attack-speed window is included in the shared swing schedule. "
        f"Basic-attack reset stacks remain available up to {effect.reset_stack_limit} "
        "times when a carrier publishes a reset receipt."
    )


def _add_keystone_lethal_tempo(state: FightState, rotation: RotationResult) -> None:
    """Add Lethal Tempo's max-stack adaptive bolt events."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.lethal_attack_times:
        attack_times = _auto_attack_timestamps(state)
        bolt_indexes = list(state.lethal_bolt_attack_indices)
        stack_counts = list(state.lethal_stack_counts)
        activation_times = list(state.lethal_activation_times)
        carrier = "ambient basic attacks"
    elif forced_times:
        (
            attack_times,
            bolt_indexes,
            stack_counts,
            activation_times,
        ) = _lethal_tempo_attack_schedule(state, effect, forced_times)
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.rune_name} never reached maximum stacks: the fight "
            "had no authored basic-attack landing."
        )
        return

    if not bolt_indexes:
        state.notes.append(
            f"{effect.rune_name} never reached its {effect.max_stacks} "
            "stack bolt threshold."
        )
        return

    inputs = _damage_inputs(state)
    damage_type = effect.damage_type(state.champion_stats)
    damage_events = []
    for index in bolt_indexes:
        if index >= len(attack_times) or index >= len(stack_counts):
            continue
        stacks = stack_counts[index]
        raw_damage = effect.bolt_raw_damage(inputs, state.is_melee, stacks)
        if raw_damage <= 0.0:
            continue
        damage_events.append(
            {
                "time": attack_times[index],
                "damage": raw_damage,
                "raw_damage": raw_damage,
                "damage_type": damage_type,
                "basic_attack": True,
                "trigger_source": carrier,
                "stack_count": stacks,
                "bonus_attack_speed_percent": effect.attack_speed_percent(
                    state.is_melee, stacks
                ),
            }
        )
    if not damage_events:
        return

    total_damage = sum(float(event["damage"]) for event in damage_events)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total_damage,
        "damage_type": damage_type,
        "count": len(damage_events),
        "event_phase": "effect",
        "damage_events": damage_events,
        "bolt_attack_indices": bolt_indexes,
        "stack_counts": stack_counts,
        "activation_times": activation_times,
        "max_stacks": effect.max_stacks,
        "stack_duration_seconds": effect.stack_duration_seconds,
        "expiry_step_seconds": effect.expiry_step_seconds,
        "attack_speed_percent_per_stack": effect.attack_speed_percent(
            state.is_melee, 1
        ),
    }
    state.total_damage += total_damage
    state.notes.append(
        f"{effect.rune_name} fired {len(damage_events)} max-stack bolt(s) "
        f"from {carrier}. Each stack adds "
        f"{effect.attack_speed_percent(state.is_melee, 1):g}% bonus attack speed; "
        f"stacks expire one at a time every {effect.expiry_step_seconds:g}s "
        f"after {effect.stack_duration_seconds:g}s without an attack."
    )


def _add_keystone_fleet_footwork(state: FightState, rotation: RotationResult) -> None:
    """Add Fleet's charged heal and one-second movement-speed window."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneFleetEffect):
        return

    options = state.keystone_options
    unset = declared_option_default("keystone", "Fleet Footwork", "starting_charges")
    starting_charges = int(options.get("starting_charges", unset) or unset)
    movement_events: list[dict[str, Any]] = []
    heal_events: list[dict[str, Any]] = []
    base_row: dict[str, Any] = {
        "name": effect.display_name,
        "informational": True,
        "event_phase": "effect",
        "count": 0,
        "starting_charges": starting_charges,
        "charge_cap": effect.charge_cap,
        "movement_events": movement_events,
    }
    state.breakdown[effect.breakdown_key] = base_row

    if starting_charges < effect.charge_cap:
        state.notes.append(
            f"{effect.rune_name} is withheld: the fight starts with "
            f"{starting_charges} of {effect.charge_cap} sourced charges, and "
            "the charge gain rate is not authored in the cached rune source."
        )
        return

    forced_times = _forced_basic_attack_times(state, rotation)
    if state.num_auto_attacks > 0:
        attack_times = _auto_attack_timestamps(state)
        carrier = "ambient basic attacks"
    elif forced_times:
        attack_times = forced_times
        carrier = "forced basic attacks"
    else:
        state.notes.append(
            f"{effect.rune_name} never procced: the fight had no "
            "authored basic-attack landing."
        )
        return
    if not attack_times:
        state.notes.append(
            f"{effect.rune_name} never procced: the shared attack schedule "
            "did not publish a landing."
        )
        return

    event_time = float(attack_times[0])
    heal_amount = effect.heal_amount(
        state.level,
        state.champion_stats,
        state.is_melee,
    )
    move_speed = effect.bonus_move_speed_percent(state.is_melee)
    movement_event = {
        "time": event_time,
        "kind": PacketKind.MOVEMENT.value,
        "amount": move_speed,
        "bonus_move_speed_percent": move_speed,
        "duration": effect.move_speed_duration_seconds,
        "source": "Fleet Footwork · Energized movement speed",
        "source_key": effect.breakdown_key,
        "target_scope": "self",
        "target_policy": "self",
        "fleet_starting_charges": starting_charges,
        "fleet_charge_cap": effect.charge_cap,
        "fleet_move_speed_duration_seconds": effect.move_speed_duration_seconds,
        "event_precision": "exact",
        "_event_id": "main:fleet-footwork:movement:0",
        "_rank": TransitionRank.BARRIER_GRANT,
    }
    movement_events.append(movement_event)
    heal_event = {
        "time": event_time,
        "amount": heal_amount,
        "trigger_source": "auto_attacks",
        "actor_wide": True,
        "kind": "keystone",
        "healing_category": "direct",
        "_event_id": "main:fleet-footwork:heal:0",
    }
    heal_events.append(heal_event)
    state.breakdown[f"heal_{effect.rune_name}"] = {
        "name": f"{effect.display_name} (self-heal)",
        "owner": "keystone",
        "count": 1,
        "amount_per_proc": heal_amount,
        "total_amount": heal_amount,
        "unit": "health",
        "heal_events": heal_events,
        "event_phase": "heal",
    }
    base_row.update(
        {
            "count": 1,
            "movement_speed_percent": move_speed,
            "move_speed_duration_seconds": effect.move_speed_duration_seconds,
        }
    )
    state.notes.append(
        f"{effect.rune_name} used one Energized basic attack from {carrier}. "
        f"The sourced {move_speed:g}% movement-speed window lasts "
        f"{effect.move_speed_duration_seconds:g}s."
    )
