"""Integrate accepted temporary attack-speed windows on one actor's clock."""

from dataclasses import dataclass, replace
import math

from .stats import ATTACK_SPEED_CAP, calculate_attack_speed


@dataclass(frozen=True, slots=True)
class AttackSpeedWindow:
    """One accepted support buff, with its source cast and recipient."""

    event_id: str
    recipient_id: str
    start: float
    end: float
    bonus_percent: float
    stack_group: str = "whimsy"


def attack_times_for_windows(  # pylint: disable=too-many-locals
    windows: tuple[AttackSpeedWindow, ...],
    *,
    attack_speed: float,
    ratio: float,
    duration: float,
    uptime: float,
    reset_at: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Keep attack progress through each rate change and floor total swings.

    Repeated grants in one group use the strongest active grant. Separate
    groups add their bonus attack speed. Each window ends before an attack
    at that instant reads the rate. Explicit reset boundaries preserve the
    existing champion schedule's per-phase count and starting attack.
    """
    if uptime <= 0 or duration <= 0 or attack_speed <= 0:
        return ()
    if reset_at:
        phases = sorted(
            {0.0, duration, *(point for point in reset_at if 0 < point < duration)}
        )
        return tuple(
            start + time
            for start, end in zip(phases, phases[1:])
            for time in attack_times_for_windows(
                tuple(
                    replace(window, start=window.start - start, end=window.end - start)
                    for window in windows
                ),
                attack_speed=attack_speed,
                ratio=ratio,
                duration=end - start,
                uptime=uptime,
            )
        )
    boundaries = sorted(
        {
            0.0,
            duration,
            *(
                max(0.0, min(duration, point))
                for window in windows
                for point in (window.start, window.end)
            ),
        }
    )
    segments = []
    progress = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        active_groups: dict[str, float] = {}
        for window in windows:
            if window.start <= start < window.end:
                active_groups[window.stack_group] = max(
                    active_groups.get(window.stack_group, 0.0), window.bonus_percent
                )
        bonus = sum(active_groups.values())
        rate = (
            min(ATTACK_SPEED_CAP, calculate_attack_speed(attack_speed, ratio, bonus))
            * uptime
        )
        next_progress = progress + (end - start) * rate
        segments.append((start, progress, next_progress, rate))
        progress = next_progress
    count = math.floor(progress + 1e-10)
    times = []
    index = 0
    for swing in range(count):
        while index + 1 < len(segments) and swing >= segments[index][2] - 1e-10:
            index += 1
        start, beginning, _, rate = segments[index]
        times.append(start + (swing - beginning) / rate)
    return tuple(times)
