"""An empowered basic attack the fight arms, counted by walking the plan.

A kit whose innate empowers a swing arms it in one of two ways, and both are
questions the fight already holds the answer to. Galio's Colossal Smash arms
on a timer, and every ability that hits a champion cuts three seconds off it.
Sylas' Petricite Burst arms on the cast itself, banking a stack per ability
and holding at most three for four seconds each.

Either way the count is a walk over two schedules the fight has: when the
casts land and when the swings do. A module states the rule with every number
sourced; nothing here knows a champion, and a rule that states neither an
arming timer nor a per-cast gain is refused rather than counted as zero.

The option a module keeps beside its rule stays an override, for the thing
neither schedule knows: whether the empowered swing actually reached the
target it was aimed at.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArmedProcRule:
    """One kit's rule for arming an empowered basic attack.

    ``cooldown`` arms one charge every so many seconds and ``per_cast``
    banks one on each arming cast; a rule carries at least one of the two.
    ``cooldown_reduction_per_cast`` is Galio's shape, where a cast brings
    the timer forward rather than banking anything. ``stack_seconds``
    expires a banked charge, and ``max_stacks`` caps what may be held.
    """

    arming_slots: frozenset[str]
    max_stacks: int
    # True when the request named the count itself, which the module can
    # see and the fight cannot: the swing the schedules count may not have
    # reached its target, and only the reader knows that.
    requested: bool = False
    cooldown: float = 0.0
    cooldown_reduction_per_cast: float = 0.0
    per_cast: int = 0
    stack_seconds: float = 0.0
    armed_at_start: bool = True

    def __post_init__(self) -> None:
        if self.max_stacks < 1:
            raise ValueError(
                f"ArmedProcRule max_stacks must be at least 1, got {self.max_stacks}"
            )
        if self.cooldown <= 0.0 and self.per_cast <= 0:
            raise ValueError(
                "ArmedProcRule states neither a cooldown nor a per_cast gain, so "
                "nothing would ever arm the swing; a rule that arms nothing is a "
                "rule with no referent"
            )


def _required(payload: Mapping[str, Any], key: str, owner: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise ValueError(
            f"{owner}: armed_procs declares no {key!r}; every number of the rule "
            "is sourced by the module, and a missing one cannot be guessed"
        )
    return value


def _optional(payload: Mapping[str, Any], key: str) -> float:
    """One number a rule may leave out, as the zero that means "no such arm"."""
    value = payload.get(key)
    return 0.0 if value is None else float(value)


def declared_rule(
    ability_damages: Mapping[str, Any],
) -> tuple[str, ArmedProcRule] | None:
    """The one armed-proc rule this kit declares, with its owner's name."""
    found: list[tuple[str, Mapping[str, Any]]] = []
    for key, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        payload = info.get("armed_procs")
        if payload:
            found.append((str(info.get("name", key)), payload))
    if not found:
        return None
    if len(found) > 1:
        raise ValueError(
            "Two slots declare armed_procs ("
            + ", ".join(name for name, _ in found)
            + "); one swing stream has one empowering innate"
        )
    owner, payload = found[0]
    return owner, ArmedProcRule(
        arming_slots=frozenset(_required(payload, "arming_slots", owner)),
        max_stacks=int(_required(payload, "max_stacks", owner)),
        requested=bool(_required(payload, "requested", owner)),
        cooldown=_optional(payload, "cooldown"),
        cooldown_reduction_per_cast=_optional(payload, "cooldown_reduction_per_cast"),
        per_cast=int(_optional(payload, "per_cast")),
        stack_seconds=_optional(payload, "stack_seconds"),
        armed_at_start=bool(_required(payload, "armed_at_start", owner)),
    )


def armed_swing_times(
    rule: ArmedProcRule,
    cast_times: Sequence[tuple[str, float]],
    swing_times: Sequence[float],
) -> tuple[float, ...]:
    """WHICH swings land empowered, walking the two schedules together.

    The walk is the game's order of events: a cast arms (or brings the timer
    forward) at the instant it lands, and a swing spends whatever is armed at
    the instant it swings. A tie goes to the cast, because a swing that
    lands with a cast is the swing the cast empowered.

    The timestamps are the answer, not their count: a row that authors an
    event per proc needs to know which swing carried it, and a row that only
    counts takes the length.
    """
    casts = sorted(((time, slot) for slot, time in cast_times), key=lambda row: row[0])
    stacks: deque[float] = deque()  # expiry times of banked charges
    ready_at = 0.0 if rule.armed_at_start else rule.cooldown
    cast_index = 0
    empowered: list[float] = []

    for swing in sorted(swing_times):
        while cast_index < len(casts) and casts[cast_index][0] <= swing:
            time, slot = casts[cast_index]
            cast_index += 1
            if slot not in rule.arming_slots:
                continue
            if rule.cooldown_reduction_per_cast > 0.0:
                # The timer comes forward, never behind the cast itself.
                ready_at = max(time, ready_at - rule.cooldown_reduction_per_cast)
            if rule.per_cast > 0:
                for _ in range(rule.per_cast):
                    if len(stacks) >= rule.max_stacks:
                        stacks.popleft()
                    stacks.append(
                        time + rule.stack_seconds
                        if rule.stack_seconds > 0.0
                        else float("inf")
                    )
        while stacks and stacks[0] < swing:
            stacks.popleft()
        if rule.cooldown > 0.0 and swing >= ready_at:
            empowered.append(swing)
            ready_at = swing + rule.cooldown
            continue
        if stacks:
            stacks.popleft()
            empowered.append(swing)
    return tuple(empowered)


def armed_swing_count(
    rule: ArmedProcRule,
    cast_times: Sequence[tuple[str, float]],
    swing_times: Sequence[float],
) -> int:
    """How many swings land empowered; the length of the walk's answer."""
    return len(armed_swing_times(rule, cast_times, swing_times))
