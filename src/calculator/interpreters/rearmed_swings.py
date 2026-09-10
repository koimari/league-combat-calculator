"""When a rearmed swing lands, and the two re-ratings one attack stream merges."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import SwingScheduleRule
from ..stat_formulas import calculate_attack_speed
from ..value_ref import resolve


@dataclass(frozen=True, slots=True)
class DecayingStackRamp:
    """One declared ramp's resolved numbers."""

    per_stack: float
    max_stacks: int
    stack_duration: float

    def bonus_percent(self, live_stacks: int) -> float:
        """The bonus attack speed *live_stacks* stacks are worth, as a percent."""
        return 100.0 * self.per_stack * min(max(0, int(live_stacks)), self.max_stacks)


@dataclass(frozen=True, slots=True)
class RearmedWindow:
    """One declared re-armed window's resolved numbers."""

    bonus_percent: float
    duration: float
    cooldown: float
    refund_per_attack: float
    refund_per_crit: float

    def refund(self, critical_chance: float) -> float:
        """What one attack pays down this window's cooldown by.

        The critical share is weighted by the holder's chance, clamped to [0, 1].
        """
        return (
            self.refund_per_attack
            + max(0.0, min(1.0, float(critical_chance))) * self.refund_per_crit
        )


@dataclass(frozen=True, slots=True)
class ActiveWindow:
    """A champion's own attack-speed window on the stream: ``[start, end)``."""

    start: float
    end: float
    bonus_percent: float

    def bonus_at(self, time: float) -> float:
        """The bonus attack speed a swing landing at *time* rates the next one at."""
        return self.bonus_percent if self.start <= time < self.end else 0.0


@dataclass(frozen=True, slots=True)
class SwingSchedule:
    """Every re-rating of one build's own attack stream, resolved together.

    A build holds at most one of each shape today and the type says so, but
    the merge is the point: two items re-rating one stream is one schedule,
    and the walk below reads both records on every swing rather than running
    twice.

    ``opening_rate_bonus_percent`` is what the *panel* rate already carries
    and this schedule re-applies itself: a re-armed window is folded into the
    public stat block as assumed-active, and the authored fight starts before
    the holder has attacked, so the opening rate has to give it back.
    """

    ramp: DecayingStackRamp | None
    window: RearmedWindow | None
    schedules_single_rotation: bool

    @property
    def opening_rate_bonus_percent(self) -> float:
        """The conditional bonus the opening rate must not carry."""
        return 0.0 if self.window is None else self.window.bonus_percent

    def schedules(self, *, one_rotation: bool) -> bool:
        """Whether this fight's attack stream is walked rather than flat-rated."""
        return self.schedules_single_rotation or not one_rotation


def _merged_schedule(
    declared: Sequence[SwingScheduleRule], level: int
) -> SwingSchedule | None:
    """Every declared re-rating of one attack stream, resolved into one record.

    ``None`` is the answer for a build that declares none, and it is the
    engine's instruction to rate the stream flat — a different statement from
    a schedule whose numbers happen to resolve to zero.
    """
    if not declared:
        return None
    ramp: DecayingStackRamp | None = None
    window: RearmedWindow | None = None
    for rule in declared:
        if rule.decaying_stacks is not None:
            stacks = rule.decaying_stacks
            ramp = DecayingStackRamp(
                per_stack=resolve(stacks.per_stack, level),
                max_stacks=int(resolve(stacks.max_stacks, level)),
                stack_duration=resolve(stacks.stack_duration, level),
            )
        if rule.refunded_window is not None:
            declared_window = rule.refunded_window
            window = RearmedWindow(
                bonus_percent=resolve(
                    declared_window.bonus_attack_speed_percent, level
                ),
                duration=resolve(declared_window.duration, level),
                cooldown=resolve(declared_window.cooldown, level),
                refund_per_attack=resolve(declared_window.refund_per_attack, level),
                refund_per_crit=resolve(declared_window.refund_per_crit, level),
            )
    return SwingSchedule(
        ramp=ramp,
        window=window,
        schedules_single_rotation=any(
            rule.schedules_single_rotation for rule in declared
        ),
    )


# How close to the fight's end a swing has to fall to be dropped: the walk
# compares against the duration, and a float sum that lands on it exactly is
# the last swing rather than one past the end.
_SWING_EPSILON = 1e-12


def swing_times(  # pylint: disable=too-many-arguments,too-many-locals
    schedule: SwingSchedule,
    *,
    attack_speed: float,
    attack_speed_ratio: float,
    duration_seconds: float,
    uptime: float = 1.0,
    critical_chance: float = 0.0,
    active_window: ActiveWindow | None = None,
) -> tuple[float, ...]:
    """Walk *schedule*, one swing at a time, and return when each lands.

    The first attack lands at ``t=0``.  A ramp gains one stack per completed
    attack, holds it for its declared duration and re-rates every later swing;
    a re-armed window is live from the second attack until its duration runs
    out, and every attack after the first pays down the cooldown that reopens
    it.  A champion's own *active_window* (Yunara Q, Tristana Q) adds its
    bonus to every swing rated inside it, on top of the ramp's stacks.
    Nothing here reads a roster, a target or a damage number: the fight
    ledger consumes the timestamps and prices them itself.

    The arguments are the authored timing inputs, passed explicitly, so no
    caller can hide one in a global or let a stale fallback stand in for it.
    """
    if duration_seconds <= 0.0 or uptime <= 0.0 or attack_speed <= 0.0:
        return ()
    ramp, window = schedule.ramp, schedule.window
    times: list[float] = [0.0]
    stack_times: list[float] = [0.0]
    current = 0.0
    active_until = 0.0 if window is None else window.duration
    cooldown = 0.0 if window is None else window.cooldown
    refund = 0.0 if window is None else window.refund(critical_chance)
    first_attack = True
    while True:
        if ramp is None:
            stack_times.clear()
        else:
            stack_times[:] = [
                start for start in stack_times if current - start < ramp.stack_duration
            ]
        bonus = 0.0 if ramp is None else ramp.bonus_percent(len(stack_times))
        if active_window is not None:
            bonus += active_window.bonus_at(current)
        rate = calculate_attack_speed(attack_speed, attack_speed_ratio, bonus) * uptime
        if window is not None and not first_attack and current < active_until:
            rate += (
                calculate_attack_speed(0.0, attack_speed_ratio, window.bonus_percent)
                * uptime
            )
        if rate <= 0.0:
            break
        next_time = current + 1.0 / rate
        if next_time >= duration_seconds - _SWING_EPSILON:
            break
        if window is not None:
            cooldown = max(0.0, cooldown - (next_time - current))
            if not first_attack:
                cooldown = max(0.0, cooldown - refund)
                if cooldown <= 0.0:
                    active_until = next_time + window.duration
                    cooldown = window.cooldown
        times.append(next_time)
        if ramp is not None:
            stack_times.append(next_time)
        current = next_time
        first_attack = False
    return tuple(times)
