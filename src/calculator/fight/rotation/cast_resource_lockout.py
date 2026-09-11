"""A self-silencing resource the cast plan builds and then pays for.

Rumble's mech heats on every basic ability cast and locks him out of casting
when the bar fills. That is a property of the PLAN, not a number a player can
state: which casts land, and when, decides how often the bar fills, and each
lockout then decides which casts land after it. So this module walks the
plan. Everything it reads is cached prose the declaring module sources: the
gain per cast, the ceiling, the lockout and the decay with its delay. Nothing
here knows a champion.

The walk is the game's: a generating cast adds its gain, the bar decays once
the declared delay has passed since the last generating cast, and reaching
the ceiling empties the bar and silences every slot for the lockout's
seconds. A lockout occupies the middle of the fight, where it happens, rather
than being taken off the end of the horizon, which is what the declared axis
had to do.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..cast_slots import _base_slot


@dataclass(frozen=True)
class LockoutRule:
    """One kit's self-silencing resource, every number of it sourced."""

    slots: frozenset[str]
    per_cast: float
    ceiling: float
    seconds: float
    decay_per_second: float
    decay_delay_seconds: float
    ultimate_slot: str
    ultimate_delay_seconds: float
    name: str

    def generates(self, ability_key: str) -> bool:
        """Whether a cast of this key adds to the bar."""
        return _base_slot(ability_key) in self.slots


def _required(payload: Mapping[str, Any], key: str, owner: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise ValueError(
            f"{owner}: cast_resource_lockout declares no {key!r}; every number "
            "of the rule is sourced by the module, and a missing one cannot be "
            "guessed"
        )
    return value


def declared_rule(ability_damages: Mapping[str, Any]) -> LockoutRule | None:
    """The one lockout rule this kit declares, or ``None``.

    Two rules would be two bars over one set of hands, and the walk has no
    reading for that, so it is refused rather than resolved by order.
    """
    found: list[tuple[str, Mapping[str, Any]]] = []
    for key, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        payload = info.get("cast_resource_lockout")
        if payload:
            found.append((str(info.get("name", key)), payload))
    if not found:
        return None
    if len(found) > 1:
        raise ValueError(
            "Two slots declare a cast_resource_lockout ("
            + ", ".join(name for name, _ in found)
            + "); one set of hands has one bar"
        )
    owner, payload = found[0]
    return LockoutRule(
        slots=frozenset(_required(payload, "slots", owner)),
        per_cast=float(_required(payload, "per_cast", owner)),
        ceiling=float(_required(payload, "ceiling", owner)),
        seconds=float(_required(payload, "seconds", owner)),
        decay_per_second=float(_required(payload, "decay_per_second", owner)),
        decay_delay_seconds=float(_required(payload, "decay_delay_seconds", owner)),
        ultimate_slot=str(_required(payload, "ultimate_slot", owner)),
        ultimate_delay_seconds=float(
            _required(payload, "ultimate_delay_seconds", owner)
        ),
        name=owner,
    )


class LockoutWalk:
    """The bar, walked cast by cast in the order the plan casts them."""

    def __init__(self, rule: LockoutRule) -> None:
        self.rule = rule
        self.level = 0.0
        self.last_generating = 0.0
        self.last_ultimate = 0.0
        self.windows: list[tuple[float, float]] = []

    def _decayed(self, now: float) -> float:
        """The bar at *now*, after whatever decay the delay has allowed.

        Decay starts once the kit has gone its declared delay without a
        generating cast AND without its ultimate, which is the cached
        sentence read literally: the later of the two deadlines wins.
        """
        if self.level <= 0.0 or self.rule.decay_per_second <= 0.0:
            return max(0.0, self.level)
        starts = max(
            self.last_generating + self.rule.decay_delay_seconds,
            self.last_ultimate + self.rule.ultimate_delay_seconds,
        )
        if now <= starts:
            return self.level
        return max(0.0, self.level - (now - starts) * self.rule.decay_per_second)

    def blocked_until(self) -> float:
        """When the hands are free again, or 0.0 when nothing locked them."""
        return self.windows[-1][1] if self.windows else 0.0

    def cast(self, ability_key: str, now: float, cast_end: float) -> float:
        """Record one accepted cast; return when the hands are free again.

        The cast itself always lands: the game fills the bar with it and
        silences what comes after, so the cast that overheats is paid for,
        not refused.
        """
        self.level = self._decayed(now)
        if _base_slot(ability_key) == self.rule.ultimate_slot:
            self.last_ultimate = now
        if not self.rule.generates(ability_key):
            return 0.0
        self.level += self.rule.per_cast
        self.last_generating = now
        if self.level < self.rule.ceiling:
            return 0.0
        # The ceiling empties the bar and starts the lockout at the moment
        # the overheating cast finishes.
        self.level = 0.0
        self.last_generating = cast_end
        self.last_ultimate = cast_end
        window = (cast_end, cast_end + self.rule.seconds)
        self.windows.append(window)
        return window[1]


def lockout_seconds_within(
    windows: tuple[tuple[float, float], ...], duration: float
) -> float:
    """How many of a fight's seconds the derived windows actually cover."""
    if duration <= 0.0:
        return 0.0
    covered = 0.0
    for start, end in windows:
        covered += max(0.0, min(end, duration) - min(start, duration))
    return covered


def lockout_rule_for(state: Any) -> LockoutRule | None:
    """The kit's rule, read off the parsed entries the fight holds."""
    return declared_rule(state.ability_damages)


def declared_grant(ability_damages: Mapping[str, Any]) -> tuple[str, float] | None:
    """The slot and full attack-speed grant the lockout's owner declares."""
    for key, info in ability_damages.items():
        if not isinstance(info, Mapping) or not info.get("cast_resource_lockout"):
            continue
        buff = info.get("stat_buff")
        if not buff:
            return None
        granted = buff.get("bonus_attack_speed")
        if granted is None:
            raise ValueError(
                f"{info.get('name', key)} declares a cast_resource_lockout and a "
                "stat_buff with no bonus_attack_speed: the engine rates the "
                "grant by the derived window share and has nothing to rate"
            )
        return key, float(granted)
    return None


def _covered_share(state: Any) -> float:
    """The share of the fight the derived windows cover, in [0, 1]."""
    duration = float(state.fight_duration_seconds)
    if duration <= 0.0:
        return 0.0
    covered = lockout_seconds_within(tuple(state.lockout_windows), duration)
    return min(1.0, covered / duration)


def apply_lockout_attack_speed(state: Any) -> None:
    """Rate the lockout owner's attack-speed grant by the windows it earned.

    The grant is worth its full percent for the seconds the windows cover
    and nothing outside them, so the fight-averaged bonus is exact here:
    attack speed is linear in the bonus percent. The share is DERIVED from
    the plan, so a build that fills the bar more often is worth more attack
    speed with nobody saying so.
    """
    from ..setup.stat_buff_ultimates import _rate_attack_speed_grant

    grant = declared_grant(state.ability_damages)
    if grant is None:
        return
    key, granted = grant
    share = _covered_share(state)
    if share <= 0.0 or granted <= 0.0:
        return
    bonus = granted * share
    # The same bookkeeping every other kit grant gets: the stat sheet
    # carries the bonus percent, and the swing stream is re-rated from it.
    state.champion_stats["bonus_attack_speed"] = (
        float(state.champion_stats["bonus_attack_speed"]) + bonus
    )
    _rate_attack_speed_grant(state, key, bonus, None)
    state.champion_stats["attack_speed"] = state.attack_speed


def lockout_empowered_swings(state: Any, swing_times: tuple[float, ...]) -> int:
    """How many of the fight's swings land inside a derived window."""
    windows = tuple(state.lockout_windows)
    if not windows:
        return 0
    return sum(
        1 for time in swing_times if any(start <= time < end for start, end in windows)
    )
