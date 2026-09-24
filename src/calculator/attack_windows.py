"""Integrate accepted temporary attack-speed windows on one actor's clock."""

from dataclasses import dataclass

from .attack_cadence import impact_times
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


def attack_times_for_windows(
    windows: tuple[AttackSpeedWindow, ...],
    *,
    attack_speed: float,
    ratio: float,
    duration: float,
    uptime: float,
    phase: float,
) -> tuple[float, ...]:
    """One attack timer carried through each rate change the windows make.

    Repeated grants in one group use the strongest active grant. Separate
    groups add their bonus attack speed. Each window ends before an attack
    at that instant reads the rate. Impacts land by ``attack_cadence``.
    """
    if uptime <= 0 or duration <= 0 or attack_speed <= 0:
        return ()
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
    spans = []
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
        spans.append((start, end, rate))
    return impact_times(spans, phase)
