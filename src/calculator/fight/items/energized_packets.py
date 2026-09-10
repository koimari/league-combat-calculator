"""Packets authored before the event that triggered them."""

from collections.abc import Mapping, Sequence
from typing import Any

from ... import item_effects
from ..autos.decaying_health_walk import DecayingTarget
from ..ledger.event_rows import _finite_numeric_receipt, _row_time
from ..resists import _mitigate
from ..results import RotationResult
from ..rotation.shaped_charge import _strike_declaration
from ..state import FightState, _damage_inputs


def _first_damaging_ability_event(
    state: FightState, rotation: RotationResult
) -> tuple[float, str] | None:
    """Return the first authored damaging ability event, if one exists.

    Voltaic's current Galvanize branch can consume a ready Energized effect
    from an ability. Prefer a module-authored packet timestamp; when a
    generated module has only an authored damaging cast total, use the
    sourced ability-cast instance as the trigger boundary. That boundary is
    distinct from an uncertified packet timestamp: Galvanize is defined by
    the ability cast instance, not by an invented sub-event order.
    """
    for cast_event in rotation.cast_events:
        if not isinstance(cast_event, Mapping):
            continue
        slot = cast_event.get("slot")
        if not isinstance(slot, str):
            continue
        cast_time = _finite_numeric_receipt(cast_event.get("time"))
        if cast_time is None:
            continue
        row = state.breakdown.get(slot)
        if isinstance(row, Mapping):
            events = row.get("damage_events")
            if isinstance(events, list):
                positive = [
                    event
                    for event in events
                    if isinstance(event, Mapping)
                    and _finite_numeric_receipt(event.get("damage")) not in (None, 0.0)
                ]
                if positive:
                    first = min(
                        positive,
                        key=_row_time,
                    )
                    event_time = _finite_numeric_receipt(first.get("time"))
                    if event_time is not None:
                        event_precision = str(
                            first.get("event_precision", "cast_boundary")
                        )
                        return event_time, event_precision
            if float(row.get("total_damage", 0.0) or 0.0) > 0.0:
                return cast_time, "ability_cast_instance"
    return None


def _author_energized_ability_proc(
    state: FightState,
    rotation: RotationResult,
    effect: item_effects.FirstAutoEffect,
    effectiveness: float,
) -> bool:
    """Author one Galvanize packet before its triggering ability.

    The return value tells the auto scheduler that the opening charge was
    consumed.  A missing authored damaging ability is not an error: the item
    remains ready for the ordinary explicit auto schedule.
    """
    if not effect.energized_ability_trigger or effect.energized_max_stacks <= 0:
        return False
    ability_event = _first_damaging_ability_event(state, rotation)
    if ability_event is None:
        return False
    ability_proc_time, ability_proc_precision = ability_event
    source = effect.source
    ability_raw = source.raw_damage(_damage_inputs(state)) * effectiveness
    ability_mitigated = _mitigate(
        ability_raw, source.damage_type, state.resists, state.magic_amp
    )
    if ability_mitigated <= 0.0:
        return False
    ability_key = f"{source.breakdown_key}_ability"
    mechanic = source.previewed_mechanic()
    ability_row: dict[str, Any] = {
        "name": f"{source.display_name} (Galvanize)",
        "count": 1,
        "damage_per_hit": ability_mitigated,
        "unit": "procs",
        "total_damage": ability_mitigated,
        "damage_type": source.damage_type,
        "event_phase": "ability",
        # A ``charged_strike`` preview: the pair engine's figure leaves every
        # roster total and the walk prices the declaration below.  This is
        # the one strike whose own window re-prices it — Firmament's extra
        # lethality applies to its own packet — so
        # ``_apply_temporary_lethality_windows`` restates the resistance on
        # this declaration afterwards (umbrella Amendment N, Ruling 1).
        "pair_preview_of": mechanic,
        "declared": _strike_declaration(mechanic, ability_raw),
        "damage_events": [
            {
                "time": ability_proc_time,
                "damage": ability_mitigated,
                "damage_type": source.damage_type,
                # Firmament is an ordered pre-packet effect, so it sorts
                # before the triggering ability packet at the same time.
                "timeline_order": -1.0,
                "event_precision": ability_proc_precision,
                "declared": _strike_declaration(mechanic, ability_raw),
            }
        ],
    }
    ability_row["energized_schedule"] = effect.schedule_receipt()
    temporary_lethality = (
        effect.temporary_lethality_melee
        if state.is_melee
        else effect.temporary_lethality_ranged
    )
    if temporary_lethality > 0 and effect.temporary_lethality_duration > 0:
        ability_row["temporary_lethality"] = {
            "amount": temporary_lethality,
            "duration": effect.temporary_lethality_duration,
            "applies_before_event": True,
            "applied_to_triggering_event": True,
            "applied_to_later_events": False,
            "note": (
                "Galvanize Firmament is applied before the triggering ability, "
                "per the sourced Wiki entry."
            ),
        }
    state.breakdown[ability_key] = ability_row
    state.total_damage += ability_mitigated
    return True


def _first_auto_damage_by_auto_for_health_walk(
    state: FightState,
    rotation: RotationResult,
    num_auto_attacks: int,
    swing_times: Sequence[float],
    *,
    effectiveness: float,
) -> list[float]:
    """Price first-auto packets as HP inputs without authoring them twice.

    ``_layer_on_hit_effects`` runs before ``_add_first_auto_strikes``.  The
    latter owns the output rows/total, while this helper supplies only the
    packets' mitigated damage to the BoRK HP walk.  Keeping the two concerns
    separate prevents the first-auto packet from being added to fight damage
    twice.
    """
    if num_auto_attacks <= 0:
        return []

    packets = [0.0] * num_auto_attacks
    for effect in state.declared.charged_strikes.first_autos:
        source = effect.source
        if not effect.state_ready(state.items, state.item_options):
            continue
        # Galvanize consumes an energized charge on the first damaging ability;
        # that packet is not also an auto packet.  The authoring pass handles
        # the actual ability row; this HP-only pass just omits its auto index.
        ability_consumed = (
            effect.energized_ability_trigger
            and effect.energized_max_stacks > 0
            and _first_damaging_ability_event(state, rotation) is not None
        )
        if effect.chain_targets_max > 0:
            chain_target_count = effect.chain_target_count(state.level)
            allocated_targets = min(
                max(1, state.roster_target_count), chain_target_count
            )
            if state.roster_target_index >= allocated_targets:
                continue
        initial_stacks = 0.0 if ability_consumed else float(effect.energized_max_stacks)
        if effect.energized_max_stacks > 0:
            proc_indices = effect.proc_indices(
                num_auto_attacks, initial_stacks=initial_stacks
            )
        else:
            proc_indices = tuple(range(min(effect.max_procs, num_auto_attacks)))
        for proc_index in proc_indices:
            if proc_index >= num_auto_attacks:
                continue
            if proc_index < len(swing_times):
                target_current_health = DecayingTarget.ledger_health(
                    state, float(swing_times[proc_index])
                )
            else:
                target_current_health = float(state.target_health)
            raw = (
                source.raw_damage(
                    _damage_inputs(state, target_current_health=target_current_health)
                )
                * effectiveness
            )
            mitigated = _mitigate(
                raw, source.damage_type, state.resists, state.magic_amp
            )
            if source.basic_damage and source.damage_type != "true":
                mitigated *= state.target_basic_damage_multiplier
            packets[proc_index] += max(0.0, mitigated)
    return packets
