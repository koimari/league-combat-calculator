"""What one swing carries, as opposed to when it lands."""

from collections.abc import Callable, Mapping
from typing import Any

from ...ability_atoms import ability_field
from ..state import FightState
from .swing_schedule import _auto_attack_timestamps


def _find_auto_attack_override(
    ability_damages: Mapping[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first champion ``auto_attack_override`` payload, if any.
    Keys: ``ad_ratio`` / ``crit_as_bonus`` (Ashe), ``replace_raw`` /
    ``damage_type`` / ``name`` (Azir), ``damage_ratio`` (Bel'Veth) and
    ``on_hit_effectiveness`` (Azir 0.5, Bel'Veth 0.75)."""
    for info in ability_damages.values():
        if "auto_attack_override" in info:
            return info["auto_attack_override"]
    return None


def _basic_attack_true_rider(
    ability_damages: Mapping[str, dict[str, Any]],
) -> tuple[float, str]:
    """A champion's bonus-true-damage share of every basic attack.
    Corki's Hextech Munitions deals 20% of each attack's PRE-MITIGATION damage
    again as true damage, declared as ``basic_attack_true_ratio``.  Riding the
    raw damage makes the true instance crit-multiplied, exactly as the wiki
    describes ("affected by critical strike modifiers")."""
    for info in ability_damages.values():
        ratio = ability_field(info, "basic_attack_true_ratio")
        if ratio > 0:
            return ratio, ability_field(info, "name")
    return 0.0, ""


def _on_hit_effectiveness(state: FightState) -> float:
    """Item-effect effectiveness on the auto stream (default 1.0).

    A champion ``auto_attack_override`` may carry ``on_hit_effectiveness``
    (Azir soldiers: 0.5); while one is active every per-attack and proc-style
    item effect applies at it.  Sundered Sky is the exception:
    ``_simulate_auto_attacks`` skips its branch on replaced autos."""
    override = _find_auto_attack_override(state.ability_damages)
    return (
        ability_field(override, "on_hit_effectiveness", form="auto_attack_override")
        if override
        else 1.0
    )


def _auto_swing_bonus_ad(
    state: FightState,
    damage_ratio: float,
) -> Callable[[int], float]:
    """Per-auto bonus AD from a stack-triggered steroid.

    A mid-fight buff (Darius' Noxian Might) covers only part of the fight, so
    an auto is priced at the AD its own timestamp saw, read from the fight's
    shared :class:`StackTimeline`, which already knows which auto opened the
    window and so is not itself buffed.  ``damage_ratio`` mirrors the flat
    basic-attack modifier the caller applied to the base AD (Bel'Veth's 75%).
    The returned function of the auto index is constantly 0.0 when no such
    buff exists."""
    timeline = state.stack_timeline
    if timeline is None or not timeline.buff_windows:
        return lambda auto_index: 0.0
    swing_times = _auto_attack_timestamps(state)

    def bonus_ad(auto_index: int) -> float:
        time = swing_times[auto_index] if auto_index < len(swing_times) else 0.0
        return timeline.auto_bonus_ad(auto_index, time) * damage_ratio

    return bonus_ad
