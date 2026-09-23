"""When a basic-attack stream's impacts land, counted from the attack command at t=0.

League Wiki, *Attack speed*: "Starting a windup also starts counting the attack
timer", and an attack lands when its windup ends.  Counted in attack cycles,
impact ``k`` lands once the timer has run ``k + phase`` cycles, where ``phase``
is the windup's share of one cycle.  Every stream the fight builds (one rate, a
window, a ramp, a keystone's) places its impacts by that one rule.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .binary_roots import basic_attack_value

# League Wiki, *Attack speed*: "The original way of calculating the windup
# percent is 0.3+attackOffset"; the updated way is attackCastTime/attackTotalTime.
ORIGINAL_WINDUP_BASE = 0.3

# The cast/total pair vendor/lolstaticdata/lolstaticdata/champions/
# pull_champions_wiki.py writes when the wiki states neither, so a row holding
# it is read as the original method (TRAPS.md: Skarner's real pair is the same).
_SCRAPER_CAST_TOTAL_PLACEHOLDER = (0.3, 1.6)

# League Wiki, *Attack speed*: a windup modifier is "a value different from the
# default 1"; the binary's basicAttack record leaves the default unstated.
_DEFAULT_WINDUP_MODIFIER = 1.0
_WINDUP_MODIFIER_FIELD = "mAttackDelayCastOffsetPercentAttackSpeedRatio"

_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class Windup:
    """One champion's attack windup: its share of the base attack timer, and how
    far bonus attack speed shortens it."""

    percent: float
    modifier: float
    base_attack_speed: float

    def seconds(self, attack_speed: float) -> float:
        """The windup at *attack_speed*, by the wiki's general form."""
        base = self.percent / self.base_attack_speed
        return base + self.modifier * (self.percent / attack_speed - base)

    def phase(self, attack_speed: float) -> float:
        """The windup as a share of one attack cycle at *attack_speed*."""
        return self.seconds(attack_speed) * attack_speed


def _flat(stats: Mapping[str, Any], name: str) -> float:
    try:
        return float(stats[name]["flat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"cached champion stats carry no usable {name}") from exc


def champion_windup(champion: Mapping[str, Any]) -> Windup:
    """The windup a cached champion row states, with the binary's modifier."""
    stats = champion["stats"]
    cast, total = _flat(stats, "attackCastTime"), _flat(stats, "attackTotalTime")
    if (cast, total) == _SCRAPER_CAST_TOTAL_PLACEHOLDER:
        percent = ORIGINAL_WINDUP_BASE + _flat(stats, "attackDelayOffset")
    else:
        percent = cast / total
    modifier = basic_attack_value(str(champion["key"]), _WINDUP_MODIFIER_FIELD)
    return Windup(
        percent=percent,
        modifier=_DEFAULT_WINDUP_MODIFIER if modifier is None else modifier,
        base_attack_speed=_flat(stats, "attackSpeed"),
    )


def impact_times(
    spans: Iterable[tuple[float, float, float]], phase: float
) -> tuple[float, ...]:
    """The impacts of one stream over consecutive ``(start, end, rate)`` spans.

    A rate is attacks per second (attack speed times uptime) and a span of rate
    0 holds the timer.  Impact ``k`` lands where the stream's cycle count
    reaches ``k + phase``; an impact at or past a span's end falls in the next
    span, and past the last span it is outside the window.
    """
    times: list[float] = []
    progress = 0.0
    for start, end, rate in spans:
        if end <= start or rate <= 0.0:
            continue
        reach = progress + (end - start) * rate
        while len(times) + phase < reach - _EPSILON:
            times.append(start + (len(times) + phase - progress) / rate)
        progress = reach
    return tuple(times)


def counted_impacts(
    count: int, rate: float, phase: float, start: float = 0.0
) -> list[float]:
    """:func:`impact_times` for the first *count* impacts of one rate."""
    return [start + (index + phase) / rate for index in range(count)]


def opener_spans(
    opening_rate: float, opening_impacts: int, rate: float, seconds: float
) -> tuple[tuple[float, float, float], ...]:
    """A stream whose first *opening_impacts* cycles run at *opening_rate* and
    the rest at *rate* (Fiendhunter Bolts' empowered opener)."""
    switch = opening_impacts / opening_rate if opening_impacts > 0 else 0.0
    return ((0.0, switch, opening_rate), (switch, seconds, rate))


def stream_impacts(
    rate: float, seconds: float, phase: float, start: float = 0.0
) -> tuple[float, ...]:
    """A one-rate stream opened at *start*, over the *seconds* after it."""
    return impact_times(((start, start + seconds, rate),), phase)


def impact_count(rate: float, seconds: float, phase: float) -> int:
    """How many impacts a one-rate stream lands inside *seconds*."""
    if rate <= 0.0 or seconds <= 0.0:
        return 0
    return max(0, math.ceil(seconds * rate - phase - _EPSILON))
