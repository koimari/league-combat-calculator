"""When auto attacks land."""

import math
from collections.abc import Iterable

from ... import rune_effects
from ...attack_windows import AttackSpeedWindow, attack_times_for_windows
from ...interpreters import rearmed_swings
from ...stats import calculate_attack_speed
from ..state import FightState


def _weave_around_bursts(
    offsets: Iterable[float],
    blocks: tuple[tuple[float, float], ...],
) -> list[float]:
    """Put ordinary swings on the clock a burst's blocks displace.

    ``offsets`` are elapsed ORDINARY-attack seconds; every block a swing
    has reached pushes it back by that block's own length. The blocks are
    disjoint and sorted, so one forward pass is exact — and since the auto
    count was bought out of ``duration - blocks``, the last woven swing
    always lands inside the fight.
    """
    times: list[float] = []
    for offset in offsets:
        time = offset
        for start, end in blocks:
            if time >= start:
                time += end - start
        times.append(time)
    return times


def _swings_at_rate(count: int, rate: float, start: float = 0.0) -> list[float]:
    """The one index/rate swing sequence: ``count`` swings from ``start``."""
    return [start + index / rate for index in range(count)]


def _base_auto_attack_timestamps(state: FightState) -> list[float]:
    """Return the per-swing schedule the auto count is derived from.

    A normal stream starts at time zero and advances at attack speed times
    uptime. Ultimate attack-speed windows use their buffed rate first, then
    hand the remaining swings to the ordinary rate. Keeping this schedule next
    to the count calculation prevents threshold defenses from treating a
    multi-second auto stream as one post-rotation burst.

    A kit burst that sets its own rate (Jayce's Hyper Charge) already
    resolved its swing times against the cast plan, so the ordinary stream
    is woven around those blocks — the same two-rate accounting the count
    was derived from, which is what keeps every swing inside the fight.
    """
    if state.support_attack_times is not None:
        return list(state.support_attack_times)
    if state.num_auto_attacks <= 0 or state.auto_attack_uptime <= 0:
        return []
    normal_rate = state.attack_speed * state.auto_attack_uptime
    if normal_rate <= 0:
        return []
    burst = state.burst_swings
    if burst is not None:
        ordinary = state.num_auto_attacks - len(burst.times)
        return sorted(
            burst.times
            + tuple(
                _weave_around_bursts(
                    _swings_at_rate(ordinary, normal_rate),
                    burst.blocks,
                )
            )
        )
        # Lich Bane's proc-timed speedup is applied once, by
        # ``_auto_attack_timestamps``, over whichever schedule this returns.
    if state.q_window_end > 0.0:
        # P1 Slice 11 (Ashe Q active window): the autos ride the base
        # rate before the cast, the buffed rate inside [cast_start,
        # q_window_end), then the base rate again from the window end
        # (end-exclusive — a swing landing exactly at the boundary is
        # normal).
        buffed_rate = state.attack_speed * state.auto_attack_uptime
        base_rate = state.q_window_base_rate * state.auto_attack_uptime
        times = []
        if base_rate > 0.0:
            times.extend(_swings_at_rate(state.q_window_pre_autos, base_rate))
        if buffed_rate > 0.0:
            times.extend(
                _swings_at_rate(state.q_window_autos, buffed_rate, state.q_window_start)
            )
        if base_rate > 0.0:
            times.extend(
                _swings_at_rate(
                    state.num_auto_attacks
                    - state.q_window_pre_autos
                    - state.q_window_autos,
                    base_rate,
                    state.q_window_end,
                )
            )
        return times
    buff = state.declared.charged_strikes.empowered_auto_buff
    empowered = state.empowered_autos if buff is not None else 0
    if empowered <= 0:
        schedule = state.declared.charged_strikes.swing_schedule
        if schedule is not None and schedule.schedules(one_rotation=state.one_rotation):
            times = list(
                rearmed_swings.swing_times(
                    schedule,
                    attack_speed=state.attack_speed,
                    attack_speed_ratio=state.attack_speed_ratio,
                    duration_seconds=state.fight_duration_seconds,
                    uptime=state.auto_attack_uptime,
                    critical_chance=state.champion_stats["critical_strike_chance"]
                    / 100.0,
                )
            )
            if len(times) != state.num_auto_attacks:
                # A kit stat buff re-priced the auto count on the flat
                # model (``_apply_stat_buff_ultimates``) after this ramp
                # schedule fixed the count at build time.  The count is
                # the priced fact, so the schedule follows the model that
                # produced it rather than being dropped — an eventless
                # fallback kept every swing-riding row coarse.
                times = _swings_at_rate(state.num_auto_attacks, normal_rate)
        else:
            times = _swings_at_rate(state.num_auto_attacks, normal_rate)
        return times

    buffed_rate = (
        state.attack_speed
        + state.attack_speed_ratio * buff.bonus_attack_speed_percent / 100.0
    ) * state.auto_attack_uptime
    if buffed_rate <= 0:
        return _swings_at_rate(state.num_auto_attacks, normal_rate)
    times = _swings_at_rate(empowered, buffed_rate)
    times.extend(
        _swings_at_rate(
            state.num_auto_attacks - empowered, normal_rate, empowered / buffed_rate
        )
    )
    return times


def _install_swing_count(state: FightState, count: int) -> None:
    """Install a keystone's authored auto count and re-price what reads it.

    Terminus and Black Cleaver are priced from that count, and the ability
    rotation consumes the resistance object next, so both keystone schedules
    re-resolve here rather than after the rotation has read stale averages.
    """
    state.num_auto_attacks = count
    if state.damage_effects.stacking_pen is not None:
        state.resists.terminus_avg_pen = state.damage_effects.stacking_pen.average_pen(
            count
        )
    if state.declared.armor_shred is not None:
        state.resists.bc_reduction = state.declared.armor_shred.average_reduction(count)
    state.resists.resolve_magic()
    state.resists.resolve_armor()


def _prepare_support_attack_schedule(state: FightState) -> None:
    """Price the attack count from accepted Whimsy windows before any casts."""
    windows = tuple(
        window
        for window in state.event_attack_speed_windows
        if window.recipient_id == state.event_actor_id
    )
    if not windows or state.auto_attack_uptime <= 0:
        return
    if isinstance(
        state.keystone_effect,
        (
            rune_effects.KeystoneHailOfBladesEffect,
            rune_effects.KeystoneLethalTempoEffect,
        ),
    ):
        raise ValueError(
            "Timed Whimsy with a keystone that changes attack cadence "
            "requires combined schedule support"
        )
    if (
        state.declared.charged_strikes.swing_schedule is not None
        or state.declared.charged_strikes.empowered_auto_buff is not None
        or (
            state.item_spellblade is not None
            and state.item_spellblade.bonus_attack_speed_percent > 0
        )
    ):
        raise ValueError(
            "Timed Whimsy with another temporary attack-speed schedule requires combined support"
        )
    base_rate = state.attack_speed
    reset_at: tuple[float, ...] = ()
    if state.q_window_end > 0:
        # The champion parser supplied this active window and its rate.
        # Keep Q's phase boundaries while Whimsy adds its separate grant.
        base_rate = state.q_window_base_rate
        if state.attack_speed_ratio <= 0:
            raise ValueError(
                "The champion attack-speed window requires a positive attack-speed ratio"
            )
        windows += (
            AttackSpeedWindow(
                event_id=f"{state.event_actor_id}:Q:active",
                recipient_id=state.event_actor_id,
                start=state.q_window_start,
                end=state.q_window_end,
                bonus_percent=(state.attack_speed - base_rate)
                / state.attack_speed_ratio
                * 100.0,
                stack_group="champion_active",
            ),
        )
        reset_at = (state.q_window_start, state.q_window_end)
    state.support_attack_times = attack_times_for_windows(
        windows,
        attack_speed=base_rate,
        ratio=state.attack_speed_ratio,
        duration=state.fight_duration_seconds,
        uptime=state.auto_attack_uptime,
        reset_at=reset_at,
    )
    if state.q_window_end > 0:
        state.q_window_pre_autos = sum(
            time < state.q_window_start for time in state.support_attack_times
        )
        state.q_window_autos = sum(
            state.q_window_start <= time < state.q_window_end
            for time in state.support_attack_times
        )
    _install_swing_count(state, len(state.support_attack_times))


class _HailStacks:
    """Hail of Blades' stack window, walked over one attack stream."""

    def __init__(self, effect: "rune_effects.KeystoneHailOfBladesEffect") -> None:
        self.effect = effect
        self.stacks = 0
        self.ready_at = float("-inf")
        self.active_until = float("-inf")
        self.activation_times: list[float] = []

    def arm(self, attack_time: float) -> None:
        """Activate on an attack once the sourced cooldown has passed."""
        if self.stacks <= 0 and attack_time + 1e-9 >= self.ready_at:
            self.stacks = self.effect.initial_stacks
            self.active_until = attack_time + self.effect.stack_duration_seconds
            self.activation_times.append(attack_time)

    def spend(self, attack_time: float) -> bool:
        """Consume one stack on an active attack; False when none is active."""
        if self.stacks <= 0 or attack_time > self.active_until + 1e-9:
            return False
        self.stacks -= 1
        self.active_until = attack_time + self.effect.stack_duration_seconds
        if self.stacks == 0:
            self.ready_at = attack_time + self.effect.cooldown_seconds
        return True

    def expire(self, time: float) -> bool:
        """Drop the stacks once ``time`` is past the window."""
        if time > self.active_until + 1e-9:
            self.stacks = 0
            return True
        return False


def _hail_attack_schedule(
    state: FightState, effect: "rune_effects.KeystoneHailOfBladesEffect"
) -> tuple[list[float], list[int], list[float]]:
    """Build Hail's timed swing window and active attack indexes.

    The first completed attack activates Hail and benefits from it. Each
    active basic attack consumes one sourced stack. A later activation waits
    for the sourced cooldown. Basic-attack reset receipts are handled by
    their carrier rows; the ambient schedule contains no reset event.
    """
    base_rate = state.attack_speed * state.auto_attack_uptime
    if (
        base_rate <= 0.0
        or state.fight_duration_seconds <= 0.0
        or effect.initial_stacks <= 0
        or effect.stack_duration_seconds <= 0.0
    ):
        return [], [], []

    bonus_percent = effect.bonus_attack_speed_percent(state.is_melee)
    active_rate = (
        calculate_attack_speed(
            state.attack_speed, state.attack_speed_ratio, bonus_percent
        )
        * state.auto_attack_uptime
    )
    if active_rate <= 0.0:
        return [], [], []

    times: list[float] = []
    active_indexes: list[int] = []
    hail = _HailStacks(effect)
    current = 0.0
    duration = state.fight_duration_seconds
    base_interval = 1.0 / base_rate
    active_interval = 1.0 / active_rate

    while current < duration - 1e-12:
        attack_index = len(times)
        times.append(current)
        hail.arm(current)
        if hail.spend(current):
            active_indexes.append(attack_index)
        next_time = current + (active_interval if hail.stacks > 0 else base_interval)
        if hail.expire(next_time):
            next_time = current + base_interval
        current = next_time

    return times, active_indexes, hail.activation_times


def _prepare_hail_attack_schedule(state: FightState) -> None:
    """Install Hail's raw swing schedule before the rotation is priced."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        return
    times, active_indexes, activation_times = _hail_attack_schedule(state, effect)
    state.hail_attack_times = tuple(times)
    state.hail_active_attack_indices = tuple(active_indexes)
    state.hail_activation_times = tuple(activation_times)
    _install_swing_count(state, len(times))


def _lethal_tempo_stacks_at(
    effect: "rune_effects.KeystoneLethalTempoEffect",
    stacks: int,
    last_attack: float | None,
    attack_time: float,
) -> int:
    """Expire Lethal Tempo stacks before one later attack."""
    if last_attack is None or attack_time < last_attack + effect.stack_duration_seconds:
        return stacks
    elapsed = attack_time - (last_attack + effect.stack_duration_seconds)
    expired = 1 + math.floor(elapsed / effect.expiry_step_seconds + 1e-9)
    return max(0, stacks - expired)


def _lethal_tempo_attack_schedule(
    state: FightState,
    effect: "rune_effects.KeystoneLethalTempoEffect",
    attack_times: list[float] | None = None,
) -> tuple[list[float], list[int], list[int], list[float]]:
    """Build Lethal Tempo's stack-sensitive swing and bolt schedule."""
    base_rate = state.attack_speed * state.auto_attack_uptime
    if (
        base_rate <= 0.0
        or state.fight_duration_seconds <= 0.0
        or effect.max_stacks <= 0
        or effect.stack_duration_seconds <= 0.0
        or effect.expiry_step_seconds <= 0.0
    ):
        return [], [], [], []

    # A schedule this walk generates is laid down below, at the rate each
    # attack's own stack count sets; only a caller's schedule is read here.
    generated = attack_times is None
    times = [] if generated else sorted(float(time) for time in attack_times or ())

    bolt_indexes: list[int] = []
    stack_counts: list[int] = []
    activation_times: list[float] = []
    stacks = 0
    last_attack: float | None = None

    def swing(attack_time: float) -> None:
        nonlocal stacks, last_attack
        stacks = _lethal_tempo_stacks_at(effect, stacks, last_attack, attack_time)
        if stacks <= 0:
            stacks = 0
            activation_times.append(attack_time)
        stacks = min(effect.max_stacks, stacks + 1)
        if stacks >= effect.max_stacks:
            bolt_indexes.append(len(stack_counts))
        stack_counts.append(stacks)
        last_attack = attack_time

    if generated:
        current = 0.0
        while current < state.fight_duration_seconds - 1e-12:
            times.append(current)
            swing(current)
            bonus_percent = effect.attack_speed_percent(state.is_melee, stacks)
            rate = (
                calculate_attack_speed(
                    state.attack_speed, state.attack_speed_ratio, bonus_percent
                )
                * state.auto_attack_uptime
            )
            if rate <= 0.0:
                break
            current += 1.0 / rate
        return times, bolt_indexes, stack_counts, activation_times

    for attack_time in times:
        swing(attack_time)
    return times, bolt_indexes, stack_counts, activation_times


def _prepare_lethal_tempo_attack_schedule(state: FightState) -> None:
    """Install Lethal Tempo's raw swing schedule before the rotation."""
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        return
    times, bolt_indexes, stack_counts, activation_times = _lethal_tempo_attack_schedule(
        state, effect
    )
    state.lethal_attack_times = tuple(times)
    state.lethal_bolt_attack_indices = tuple(bolt_indexes)
    state.lethal_stack_counts = tuple(stack_counts)
    state.lethal_activation_times = tuple(activation_times)
    _install_swing_count(state, len(times))


def _auto_attack_timestamps(state: FightState) -> list[float]:
    """Return the shared swing schedule after temporary AS adjustments."""
    times = (
        list(state.hail_attack_times)
        if state.hail_attack_times
        else (
            list(state.lethal_attack_times)
            if state.lethal_attack_times
            else _base_auto_attack_timestamps(state)
        )
    )
    return _apply_spellblade_attack_speed(state, times)


def _restore_stream_attack_timestamps(state: FightState) -> list[float]:
    """The auto-attack swing schedule the per-auto resource walk rides.

    ``_auto_restore_schedule`` runs BEFORE ``_prepare_hail_attack_schedule``
    and ``_prepare_lethal_tempo_attack_schedule`` install their stack-sensitive
    schedules, so reading ``state.hail_attack_times`` /
    ``state.lethal_attack_times`` here would fall back to the uniform base
    schedule.  This resolves the same schedule those installers compute, which
    depends only on ``state.attack_speed``, ``state.auto_attack_uptime``,
    ``state.fight_duration_seconds`` and the keystone effect, so recomputing is
    side-effect free.  Populated schedule fields are preferred outright.  Lich
    Bane's proc-timed speedup is not resolved at this point in the pipeline
    (``_prepare_spellblade_attack_schedule`` needs the priced rotation), so it
    is not mirrored here, matching the champion module's ASSUMPTIONS."""
    if state.hail_attack_times:
        return list(state.hail_attack_times)
    if state.lethal_attack_times:
        return list(state.lethal_attack_times)
    effect = state.keystone_effect
    if isinstance(effect, rune_effects.KeystoneHailOfBladesEffect):
        times, _active_indexes, _activation_times = _hail_attack_schedule(state, effect)
        if times:
            return list(times)
    elif isinstance(effect, rune_effects.KeystoneLethalTempoEffect):
        times, _bolt_indexes, _stack_counts, _activation_times = (
            _lethal_tempo_attack_schedule(state, effect)
        )
        if times:
            return list(times)
    return _base_auto_attack_timestamps(state)


def _apply_spellblade_attack_speed(
    state: FightState, times: list[float]
) -> list[float]:
    """Apply Lich Bane's empowered-attack speed to authored swing times.

    The engine's swing timestamps represent attack impacts.  When a
    Spellblade proc is armed, the first authored swing at or after its
    weave-timed proc consumes the charge.  Lich Bane's sourced bonus attack
    speed shortens the interval immediately after that empowered impact;
    later swings then continue at the ordinary authored rate.  This keeps
    the existing attack-count contract intact while making every dependent
    on-hit/proc row read the same adjusted schedule.
    """
    bonus_percent = state.spellblade_attack_speed_percent
    proc_times = state.spellblade_proc_times
    if bonus_percent <= 0.0 or not proc_times or len(times) < 2:
        return times
    normal_rate = state.attack_speed * state.auto_attack_uptime
    buffed_rate = (
        calculate_attack_speed(
            state.attack_speed, state.attack_speed_ratio, bonus_percent
        )
        * state.auto_attack_uptime
    )
    if normal_rate <= 0.0 or buffed_rate <= normal_rate:
        return times
    normal_interval = 1.0 / normal_rate
    buffed_interval = 1.0 / buffed_rate
    advance = normal_interval - buffed_interval
    adjusted = list(times)
    next_swing = 0
    for proc_time in proc_times:
        while next_swing < len(adjusted) and adjusted[next_swing] < proc_time:
            next_swing += 1
        if next_swing >= len(adjusted) - 1:
            break
        # The swing at ``next_swing`` consumes the charge; its faster
        # windup makes every later authored impact arrive ``advance`` sooner.
        for index in range(next_swing + 1, len(adjusted)):
            adjusted[index] -= advance
        next_swing += 1
    return adjusted
