"""The fight event stream a rune declares it watches."""

from collections.abc import Mapping
from typing import TypeVar

from ... import rune_effects
from ...trigger_stream import applies_control
from ..autos.swing_schedule import _auto_attack_timestamps
from ..cast_control_marker import _declared_cc_marker
from ..cast_slots import _damaging_cast_times
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState, _damage_inputs


def _rune_instance_times(state: FightState, rotation: RotationResult) -> list[float]:
    """Chronological damage-instance times the keystone stack counter sees.
    One per accepted damaging ability cast (wiki: up to one stack per cast
    instance) plus one per simulated auto swing."""
    times = _damaging_cast_times(state, rotation)
    times.extend(_auto_attack_timestamps(state))
    return sorted(times)


def _record_rune_proc_row(
    state: FightState,
    effect: (
        "rune_effects.RuneProcEffect"
        " | rune_effects.RuneProcAmpEffect"
        " | rune_effects.RuneAbilityProcEffect"
        " | rune_effects.KeystoneAeryEffect"
    ),
    proc_times: list[float],
) -> None:
    """Price one keystone's proc damage and record its breakdown row.

    Every proc-class keystone row looks alike — leveled adaptive damage
    priced once, mitigated, one timestamped event per proc — so the
    shape lives here, shared by every stack-walking keystone.
    """
    raw_per_proc = effect.raw_damage(_damage_inputs(state))
    damage_type = effect.damage_type(state.champion_stats)
    mitigated_per_proc = _mitigate(
        raw_per_proc, damage_type, state.resists, state.magic_amp
    )
    total = mitigated_per_proc * len(proc_times)
    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "total_damage": total,
        "damage_type": damage_type,
        "count": len(proc_times),
        "event_phase": "effect",
        "damage_events": [
            {
                "time": proc_time,
                "damage": mitigated_per_proc,
                "damage_type": damage_type,
            }
            for proc_time in proc_times
        ],
    }
    state.total_damage += total


def _impaired_instance_times(
    state: FightState, rotation: RotationResult
) -> list[float]:
    """Damaging cast times whose own parts put the target under crowd control.

    The marker is the reviewed ``cc_kind`` a champion module authors on the
    part that applies it, and whether that marker *is* control is asked of the
    bus rather than answered here: comparing a kind against a string is the
    divergence ``trigger_stream`` exists to prevent, and this rune's
    vocabulary is every control class rather than the immobilizing subset.

    A cast whose slot nobody reviewed contributes nothing, and the engine
    carries no control duration, so damage landing *inside* a control the
    previous cast applied is not in this stream: the count is a floor."""
    impairing = {
        slot
        for slot, entry in state.ability_damages.items()
        if float(entry.get("total_raw", 0.0)) > 0
        and applies_control(
            _declared_cc_marker(entry, roster_target_index=state.roster_target_index)
        )
    }
    return sorted(
        float(event["time"])
        for event in rotation.cast_events
        if event.get("slot") in impairing
    )


def _self_shield_times(state: FightState) -> list[float]:
    """When a self-shield lands on the holder, from the fight's own rows.

    Champion modules and the Eclipse item family publish the same shape: a
    ``self_shield_events`` list on a breakdown row, aligned by ordinal with
    that row's own damage events, which ``_ordered_damage_events`` later
    copies onto each event as ``self_shield``. It is read here rather than
    off the reconstructed ledger because every rune stream is read before
    reconstruction — and a shield entry with no damage event to align with
    has no timestamp, so it contributes nothing rather than a guessed one.
    """
    times: list[float] = []
    for entry in state.breakdown.values():
        shields = entry.get("self_shield_events")
        events = entry.get("damage_events")
        if not isinstance(shields, list) or not isinstance(events, list):
            continue
        for index, shield in enumerate(shields):
            if index < len(events) and isinstance(shield, Mapping):
                times.append(float(events[index].get("time", 0.0)))
    return sorted(times)


def _shield_armed_attack_times(state: FightState) -> list[float]:
    """The first swing at or after each self-shield the fight publishes.

    A shield empowers the *next* attack, so the instance the rune counts is
    that swing and not the shield: pricing it at the shield's own timestamp
    would book damage no swing delivered.  Two shields inside one swing gap
    empower that swing once."""
    swings = sorted(_auto_attack_timestamps(state))
    armed = {
        next((swing for swing in swings if swing >= shield_time), None)
        for shield_time in _self_shield_times(state)
    }
    return sorted(time for time in armed if time is not None)


def _rune_trigger_times(
    state: FightState, rotation: RotationResult, trigger: "rune_effects.RuneTrigger"
) -> list[float]:
    """The fight event stream one rune declares it watches.

    The rune names the stream; the engine owns what is in it. Nothing here
    interprets a rune — each member is a stream the fight already publishes.
    """
    if trigger is rune_effects.RuneTrigger.BASIC_ATTACKS:
        return sorted(_auto_attack_timestamps(state))
    if trigger is rune_effects.RuneTrigger.DAMAGING_CASTS:
        return _damaging_cast_times(state, rotation)
    if trigger is rune_effects.RuneTrigger.IMPAIRED_INSTANCES:
        return _impaired_instance_times(state, rotation)
    if trigger is rune_effects.RuneTrigger.SELF_SHIELD_EVENTS:
        return _shield_armed_attack_times(state)
    return _rune_instance_times(state, rotation)


_RuneEffectT = TypeVar("_RuneEffectT")


def _page_effects(
    state: FightState,
    kind: "type[_RuneEffectT] | tuple[type[_RuneEffectT], ...]",
) -> "list[_RuneEffectT]":
    """The selected runes of one effect kind, in page order (keystone first)."""
    return [effect for effect in state.runes if isinstance(effect, kind)]
