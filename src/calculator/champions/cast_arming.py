"""A cast the fight cannot make until a counter fills.

Ashe's Ranger's Focus is the shape: her basic attacks bank a stack of Focus
while the ability is inactive, and the ability "can only be activated at 4
stacks". That is not a level a cast is PRICED against (Case 6) and not a
ramp the level re-rates. It decides WHEN the first cast may happen at all,
which is the cast schedule's question and nobody else's.

A rule here answers one thing: the earliest instant the count stands, over
the stream that banks it. The scheduler seeds the slot's readiness with it,
so a fight too short to bank the stacks makes no cast, and a fight that
banks them late makes its first cast late.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CastArmingRule:
    """What a slot needs banked before its first cast."""

    stacks_required: int
    stack_seconds: float
    max_stacks: int

    def __post_init__(self) -> None:
        if self.stacks_required < 1:
            raise ValueError(
                "cast_requires_stacks needs at least one stack; a cast gated "
                "on nothing is a cast with no gate"
            )
        if self.stacks_required > self.max_stacks:
            raise ValueError(
                f"cast_requires_stacks needs {self.stacks_required} stacks but "
                f"holds at most {self.max_stacks}, so the cast never arms"
            )
        if self.stack_seconds <= 0.0:
            raise ValueError(
                "cast_requires_stacks declares no positive stack_seconds; a "
                "stack with no life cannot be banked"
            )


def declared_rules(
    ability_damages: Mapping[str, Any],
) -> dict[str, CastArmingRule]:
    """Every slot whose first cast waits on a counter, by slot key."""
    rules: dict[str, CastArmingRule] = {}
    for key, info in ability_damages.items():
        if not isinstance(info, Mapping):
            continue
        payload = info.get("cast_requires_stacks")
        if not payload:
            continue
        for required in ("stacks_required", "stack_seconds", "max_stacks"):
            if payload.get(required) is None:
                raise ValueError(
                    f"{key}: cast_requires_stacks declares no {required!r}; "
                    "every number of the rule is sourced by the module"
                )
        rules[key] = CastArmingRule(
            stacks_required=int(payload["stacks_required"]),
            stack_seconds=float(payload["stack_seconds"]),
            max_stacks=int(payload["max_stacks"]),
        )
    return rules


def banking_swings(
    attack_speed: float, uptime: float, duration_seconds: float
) -> tuple[float, ...]:
    """Even swing times at a fight's own rate, for a counter the swings bank."""
    rate = attack_speed * uptime
    if rate <= 0.0 or duration_seconds <= 0.0:
        return ()
    times: list[float] = []
    time = 0.0
    while time < duration_seconds:
        times.append(time)
        time += 1.0 / rate
    return tuple(times)


def ready_at(rule: CastArmingRule, banking_times: Sequence[float]) -> float:
    """When the count first stands, or ``inf`` if this stream never fills it.

    Each banking event holds its stack for the declared seconds and the cap
    drops the oldest, so a stream slower than the decay never arrives. The
    instant returned is the banking event that completes the count, because
    that is when the cast becomes available and not before.
    """
    live: list[float] = []
    for time in sorted(float(banked) for banked in banking_times):
        live = [expiry for expiry in live if expiry > time]
        if len(live) >= rule.max_stacks:
            live.pop(0)
        live.append(time + rule.stack_seconds)
        if len(live) >= rule.stacks_required:
            return time
    return float("inf")
