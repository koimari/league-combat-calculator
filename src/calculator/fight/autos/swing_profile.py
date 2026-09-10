"""What one swing carries, as opposed to when it lands."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ...ability_atoms import ability_field
from ..resists import _mitigate, _resistance_met_fields
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


def _basic_attack_rider(
    ability_damages: Mapping[str, dict[str, Any]], key: str
) -> tuple[float, str]:
    """A champion's share of a swing's PRE-MITIGATION damage dealt again.
    ``basic_attack_true_ratio`` rides every attack (Corki's Hextech Munitions:
    20% again as true damage, crit-multiplied exactly as the wiki describes,
    "affected by critical strike modifiers"); ``critical_strike_magic_ratio``
    rides the critical strikes only (Yunara's Vow of the First Lands)."""
    for info in ability_damages.values():
        ratio = ability_field(info, key)
        if ratio > 0:
            return ratio, ability_field(info, "name")
    return 0.0, ""


def _critical_share(
    outcomes: Sequence[tuple[float, float, bool]] | None,
    raw_phys: float,
    *,
    rolled_crit: bool,
) -> float:
    """The critical part of one swing's raw: expected over the outcomes, or the roll."""
    if outcomes is not None:
        return sum(weight * raw for weight, raw, critical in outcomes if critical)
    return raw_phys if rolled_crit else 0.0


class _CriticalStrikeRider:
    """A share of each critical strike's raw, dealt again as magic (Yunara P)."""

    def __init__(self, ability_damages: Mapping[str, dict[str, Any]]) -> None:
        self.ratio, self.name = _basic_attack_rider(
            ability_damages, "critical_strike_magic_ratio"
        )
        self.total = 0.0
        self.events: list[dict[str, Any]] = []

    def pay(self, crit_raw: float, time: float, state: FightState) -> None:
        """Price one swing's critical share against the target's magic resist."""
        if crit_raw <= 0.0 or self.ratio <= 0.0:
            return
        raw = crit_raw * self.ratio
        damage = _mitigate(raw, "magic", state.resists, state.magic_amp)
        self.total += damage
        self.events.append(
            {
                "time": time,
                "damage_type": "magic",
                "damage": damage,
                "raw_damage": raw,
                **_resistance_met_fields("magic", state.resists),
            }
        )

    def row(self) -> dict[str, Any]:
        """The breakdown row, one event per critical strike paid."""
        return {
            "name": f"{self.name} (critical strike magic)",
            "count": len(self.events),
            "damage_per_hit": self.total / len(self.events),
            "total_damage": self.total,
            "damage_type": "magic",
            "damage_events": self.events,
            "event_phase": "auto",
        }


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
