"""When each ability casts: haste, refunds, lockouts and the shared cast timeline."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ... import item_effects
from ...ability_atoms import ability_field
from ...stats import effective_cooldown
from ...trigger_stream import is_immobilizing_event
from ...champions.cast_arming import banking_swings, declared_rules, ready_at
from ..cast_control_marker import _declared_cc_marker
from ..cast_slots import _base_slot, _slot_is_cast
from ..empower_declaration import _empower_cooldown_delay
from .cast_resource_lockout import LockoutWalk, declared_rule
from ..results import RotationResult
from ..state import FightState


@dataclass(frozen=True, slots=True)
class CooldownRefunds:
    """The only two numbers a cast schedule reads off the swing stream.

    Navori Flickerblade pays a cooldown down per landed attack, so the cast
    schedule depends on how fast the champion swings. Naming that dependency
    as a two-field record is what lets a caller who does not have a walked
    swing stream yet ask for a schedule anyway: ``NO_REFUNDS`` says the
    attacks pay nothing down, which places every recast at or later than the
    fight will, so a count taken from it is a floor.
    """

    navori_refund: float = 0.0
    autos_per_second: float = 0.0

    @classmethod
    def of(cls, result: "RotationResult") -> "CooldownRefunds":
        """What a walked rotation already measured."""
        return cls(
            navori_refund=result.navori_refund,
            autos_per_second=result.autos_per_second,
        )


NO_REFUNDS = CooldownRefunds()


def _navori_effective_cd(
    base_cd: float,
    autos_per_second: float,
    refund_percent: float,
) -> float:
    """Compute effective cooldown with Navori Flickerblade CD refund.

    The cooldown ticks down in real time (1 second per 1 second).  Each
    auto attack that lands reduces the *remaining* cooldown by
    ``refund_percent`` (e.g. 15%), which the loop below steps through.

    Example (7s CD, 1 auto/sec, 15% refund)::

        t=0  Cast, 7s remaining
        t=1  Auto → remaining = (7-1) * 0.85 = 5.10
        t=2  Auto → remaining = (5.10-1) * 0.85 = 3.485
        t=3  Auto → remaining = (3.485-1) * 0.85 = 2.112
        t=4  Auto → remaining = (2.112-1) * 0.85 = 0.945
        t=5  Auto → remaining ≤ 0, ability ready
        Effective CD ≈ 5.0s (down from 7.0s)
    """
    if base_cd <= 0 or autos_per_second <= 0 or refund_percent <= 0:
        return base_cd

    retain = 1.0 - refund_percent  # 0.85 for 15% refund
    auto_interval = 1.0 / autos_per_second
    remaining = base_cd
    elapsed = 0.0

    # Simulate auto attacks landing at regular intervals
    next_auto = auto_interval
    while remaining > 0:
        if next_auto <= remaining:
            # Time passes until auto lands, then refund
            elapsed += next_auto
            remaining -= next_auto
            remaining *= retain
            next_auto = auto_interval
        else:
            # No more autos before CD expires — just wait it out
            elapsed += remaining
            remaining = 0.0

    return elapsed


def _immobilize_ability_haste(
    state: "FightState", ability_info: Mapping[str, Any]
) -> float:
    """The haste one slot earns by immobilizing (Imperial Mandate's Control).
    Gated on the slot's *reviewed* control marker, so a slot nobody reviewed
    pays nothing; the item is found by the value key it declares, not by name."""
    if not is_immobilizing_event(_declared_cc_marker(ability_info)):
        return 0.0
    return item_effects.immobilize_ability_haste(state.items)


def _effective_timed_cooldown(
    state: "FightState",
    refunds: "CooldownRefunds",
    ability_key: str,
    ability_info: dict,
    *,
    basic_ability_haste: float,
    control_applies: bool = True,
) -> float:
    """Effective recast cooldown in timed mode: ability haste, Spear of
    Shojin basic-ability haste (Q/W/E), ultimate haste (R), the haste an
    immobilizing slot earns (Imperial Mandate's Control), and Navori
    auto-attack refunds.

    Which haste applies is a property of the SLOT, so a variant row resolves
    to its base slot first: Briar's ``W_frenzy`` and Kindred's ``W_vigor`` are
    basic abilities and Riven's ``R_buff`` is an ultimate, and before this
    each of them matched neither branch and earned no Shojin-class or
    ultimate haste at all."""
    base_cd = ability_field(ability_info, "cooldown")
    slot = _base_slot(ability_key)
    total_haste = state.ability_haste
    if slot in ("Q", "W", "E"):
        total_haste += basic_ability_haste
    elif slot == "R":
        total_haste += float(state.champion_stats["ultimate_haste"])
    if control_applies:
        total_haste += _immobilize_ability_haste(state, ability_info)
    cd = effective_cooldown(base_cd, total_haste)
    if refunds.navori_refund > 0 and cd > 0 and slot in ("Q", "W", "E"):
        cd = _navori_effective_cd(cd, refunds.autos_per_second, refunds.navori_refund)
    return cd


def _cooldown_ready_at(
    state: "FightState", cooldown_start: float, cooldown: float
) -> float:
    """Return a cooldown's ready timestamp across an Actualizer window.

    Mana Made Real accelerates basic-ability cooldown *progress* only while
    its explicit eight-second window is active.  A single multiplied duration
    is wrong when a cooldown straddles that boundary, so consume the active
    portion first and continue the remainder at the ordinary rate.
    """
    if (
        cooldown <= 0.0
        or state.actualizer_active_until <= cooldown_start + _CAST_SCHEDULE_EPS
        or state.actualizer_basic_cooldown_multiplier >= 1.0
    ):
        return cooldown_start + cooldown
    progress_rate = 1.0 / state.actualizer_basic_cooldown_multiplier
    active_seconds = state.actualizer_active_until - cooldown_start
    active_progress = active_seconds * progress_rate
    if active_progress >= cooldown:
        return cooldown_start + cooldown / progress_rate
    return state.actualizer_active_until + (cooldown - active_progress)


_CAST_SCHEDULE_EPS = 1e-9


# ``recast_of`` is the authority for recast parentage; riding the parent's cast
# *count* is narrower.  It holds for a recast declaring a cooldown of its own to
# share (Camille Q2 at 5.0, Ambessa's at 10.0), not for the cast-exactly-once
# idiom, where Syndra's second charge is ONE extra cast.  The test is a POSITIVE
# cooldown, so zero, absent, ``None`` and negative all schedule once: a module
# stamping parentage with no cooldown has declared no shared timer either.
def _ridden_parent_slot(info: Mapping[str, Any]) -> str | None:
    """The slot whose cast COUNT this entry rides, or ``None``."""
    parent = info.get("recast_of")
    if not parent:
        return None
    return parent if float(ability_field(info, "cooldown")) > 0 else None


def _lockout_walk(state: "FightState") -> LockoutWalk | None:
    """The kit's self-silencing bar, or ``None`` when the fight has no clock."""
    if state.one_rotation or state.auto_attacks_only:
        return None
    rule = declared_rule(state.ability_damages)
    return LockoutWalk(rule) if rule is not None else None


def _schedule_authored_casts(
    state: "FightState", refunds: "CooldownRefunds", basic_ability_haste: float
) -> dict[str, list[float]]:
    """Check requested times against the sourced cooldown rules."""
    times: dict[str, list[float]] = {key: [] for key in state.cast_order}
    ready: dict[str, float] = {}
    hands_free = 0.0
    # An authored timeline is checked against the same bar the shared
    # timeline walks: a cast placed inside a lockout the earlier casts
    # earned is refused, naming the window, rather than silently landing.
    walk = _lockout_walk(state)
    for event in state.combat_events or ():
        if event.caster_id != state.event_actor_id:
            continue
        key = event.slot
        info = state.ability_damages.get(key)
        if info is None or key not in times:
            raise ValueError(f"Cast {event.id}: {key} is unavailable at this rank")
        if event.time >= state.fight_duration_seconds:
            raise ValueError(f"Cast {event.id}: time must precede the fight end")
        if event.time + _CAST_SCHEDULE_EPS < max(hands_free, ready.get(key, 0.0)):
            raise ValueError(f"Cast {event.id}: cast time or cooldown is still active")
        if times[key] and key == "R" and not state.ultimate_recasts:
            raise ValueError(f"Cast {event.id}: this ultimate supports one cast")
        cast_time = ability_field(info, "cast_time")
        cooldown = _effective_timed_cooldown(
            state,
            refunds,
            key,
            info,
            basic_ability_haste=basic_ability_haste,
            control_applies=event.caster_id.startswith("enemy:")
            != event.recipient_id.startswith("enemy:"),
        )
        if times[key] and cooldown <= 0:
            raise ValueError(
                f"Cast {event.id}: this slot has no certified recast cooldown"
            )
        hands_free = event.time + cast_time
        if walk is not None:
            locked = walk.cast(key, event.time, hands_free)
            if locked > 0.0:
                hands_free = max(hands_free, locked)
        ready[key] = _cooldown_ready_at(
            state,
            hands_free + _empower_cooldown_delay(info.get("empowers_next_auto")),
            cooldown,
        )
        times[key].append(event.time)
    return times


def _schedule_shared_casts(
    state: "FightState",
    refunds: "CooldownRefunds",
    basic_ability_haste: float,
) -> dict[str, list[float]]:
    """Timed-mode cast start times on ONE shared timeline.

    The champion has one set of hands: each cast occupies its
    ``cast_time`` (stamped from the wiki by the champion engine; absent
    means instant), and an ability recasts when its cooldown — running
    from the END of its cast — is back up and no other cast is in
    progress. Ties break by cast_order position. Zero-cooldown entries
    cast exactly once, and so does an ultimate unless its module certifies
    ``ULTIMATE_RECASTS`` — a form, a stance, a charge pool or an escalating
    cost the engine does not simulate is not safe to repeat, so silence
    keeps the one-cast rule. Recast entries ride their parent's casts and
    are not scheduled. A cast counts if it STARTS within the fight
    duration. Cassiopeia's 0.75s-cooldown E is the case that pins the
    shared timeline: 3 casts in-game over a 3s fight, where an
    independent timeline schedules 5.

    A kit that silences ITSELF (Rumble's Overheat) declares the seconds it
    spends unable to cast, and they come off this horizon.  That prices how
    much casting the lockout costs without claiming where the span sits —
    the module declaring it could not source the instant, only the length.
    """
    if state.combat_events is not None:
        return _schedule_authored_casts(state, refunds, basic_ability_haste)
    duration = state.fight_duration_seconds
    walk = _lockout_walk(state)
    # Mirror the rotation loop's recast pairing exactly: an entry rides
    # its parent's casts only when the parent appears EARLIER in the
    # cast order; otherwise it schedules independently.
    seen: set[str] = set()
    keys: list[str] = []
    for key in state.cast_order:
        info = state.ability_damages.get(key)
        if info is None:
            continue
        parent = _ridden_parent_slot(info)
        if not (parent and parent in seen):
            keys.append(key)
        seen.add(key)
    cooldowns = {
        key: _effective_timed_cooldown(
            state,
            refunds,
            key,
            state.ability_damages[key],
            basic_ability_haste=basic_ability_haste,
        )
        for key in keys
    }
    cast_times = {
        key: ability_field(state.ability_damages[key], "cast_time") for key in keys
    }
    # Dead time between the cast finishing and its cooldown starting: an
    # empowered burst whose timer only begins once its attacks are spent.
    cooldown_delays = {
        key: _empower_cooldown_delay(
            state.ability_damages[key].get("empowers_next_auto")
        )
        for key in keys
    }
    once_only_ultimate = not state.ultimate_recasts
    single_cast = {
        key
        for key in keys
        if cooldowns[key] <= 0 or (once_only_ultimate and _base_slot(key) == "R")
    }

    # A charge slot banks casts in advance (champions/charge_cadence.py):
    # ``cooldown`` above is its recharge, the time to bank ONE cast, and the
    # fight opens with the stock full, the way a champion walks into a fight.
    # Between two banked casts the game still enforces the short cached gap.
    pools = {
        key: float(ability_field(state.ability_damages[key], "charge_pool"))
        for key in keys
    }
    between_casts = {
        key: float(ability_field(state.ability_damages[key], "charge_between_casts"))
        for key in keys
    }
    stock = dict(pools)
    stock_time = dict.fromkeys(keys, 0.0)

    times: dict[str, list[float]] = {key: [] for key in keys}
    next_ready = dict.fromkeys(keys, 0.0)
    # A slot whose first cast waits on a counter the fight banks opens at
    # the instant the count stands, and never before (champions/cast_arming).
    for key, rule in declared_rules(state.ability_damages).items():
        if key in next_ready:
            armed = ready_at(
                rule,
                banking_swings(
                    state.attack_speed,
                    state.auto_attack_uptime,
                    state.fight_duration_seconds,
                ),
            )
            # Past the horizon rather than unreachable: the loop below reads
            # this as a time and an infinity is not one it can compare.
            next_ready[key] = min(armed, duration + 1.0)
    pending = set(keys)
    now = 0.0
    while pending and now <= duration + _CAST_SCHEDULE_EPS:
        if walk is not None and walk.blocked_until() > now + _CAST_SCHEDULE_EPS:
            # Silenced by the bar this plan filled: nothing casts, and the
            # clock moves to the moment the hands are free again.
            now = walk.blocked_until()
            continue
        ready = [
            key
            for key in keys
            if key in pending and next_ready[key] <= now + _CAST_SCHEDULE_EPS
        ]
        if not ready:
            # Hands free but everything on cooldown — jump to the next
            # ready time (strictly advances: nothing was ready at now).
            now = min(next_ready[key] for key in pending)
            continue
        key = ready[0]
        times[key].append(now)
        if walk is not None:
            walk.cast(key, now, now + cast_times[key])
        if key in single_cast:
            pending.remove(key)
        else:
            cooldown_start = now + cast_times[key] + cooldown_delays[key]
            next_ready[key] = _cooldown_ready_at(
                state,
                cooldown_start,
                cooldowns[key],
            )
            # Only a slot that banks more than one cast can ever be held
            # by the short inter-cast gap; with one charge the recharge is
            # always the longer wait, so the ordinary path is exact.
            if pools[key] > 1.0:
                next_ready[key] = _charge_ready_at(
                    state,
                    stock,
                    stock_time,
                    key,
                    now=now,
                    cooldown_start=cooldown_start,
                    recharge=cooldowns[key],
                    pool=pools[key],
                    gap=between_casts[key],
                )
        now += cast_times[key]
    if walk is not None:
        state.lockout_windows = tuple(walk.windows)
    return times


def _charge_ready_at(
    state: "FightState",
    stock: dict[str, float],
    stock_time: dict[str, float],
    key: str,
    *,
    now: float,
    cooldown_start: float,
    recharge: float,
    pool: float,
    gap: float,
) -> float:
    """Spend one banked cast and return when the next one may be cast.

    The stock accrues continuously at one cast per ``recharge`` seconds and
    stops at ``pool``, which is how the game's charge timer behaves, partial
    progress included: a slot that waited on the champion's hands banked that
    time too. Two casts of stock already banked are still held apart by
    ``gap``, the short cached cooldown a charge slot carries beside its
    recharge.
    """
    banked = min(pool, stock[key] + _accrued(stock_time[key], now, recharge)) - 1.0
    stock[key] = banked
    stock_time[key] = now
    if banked >= 1.0:
        # Another cast is already banked, so only the short gap holds it.
        return now + gap
    if recharge <= 0.0:
        return now + gap
    ready = _cooldown_ready_at(state, cooldown_start, recharge * (1.0 - banked))
    return max(ready, now + gap)


def _accrued(start: float, end: float, recharge: float) -> float:
    """Charges banked between two times, at one per ``recharge`` seconds."""
    if recharge <= 0.0 or end <= start:
        return 0.0
    return (end - start) / recharge


def _disclose_ultimate_cast_rule(state: "FightState", timed_mode: bool) -> None:
    """State the one-cast rule on the R row when it costs the fight a cast.

    An uncertified ultimate casts once whatever its cooldown, so every
    source of ultimate haste — Malignance, Ultimate Hunter, Axiom Arcanist's
    refund — is inert for this kit.  The note is raised only when the rule
    actually binds: the hasted cooldown fits inside the window, so a
    certified module would have cast R again.
    """
    if timed_mode is False or state.ultimate_recasts:
        return
    for key, info in state.ability_damages.items():
        if _base_slot(key) != "R" or not _slot_is_cast(key, info, state.cast_order):
            continue
        cooldown = effective_cooldown(
            ability_field(info, "cooldown"),
            state.ability_haste + float(state.champion_stats["ultimate_haste"]),
        )
        if 0.0 < cooldown <= state.fight_duration_seconds:
            state.notes.append(
                f"{info.get('name', key)} is cast once: the timed scheduler "
                "recasts an ultimate only for a module that certifies it "
                "(ULTIMATE_RECASTS), so ultimate haste does not change this "
                f"fight even though the hasted cooldown is {cooldown:.1f}s."
            )
