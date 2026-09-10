"""One authoritative shield/health transition for every damage instance.

Absorption order and state mutation live here and nowhere else.  Every walk
in the calculator drives :func:`absorb`: the two ordered damage walks in
``damage.py`` and the one survival kernel in ``survival/transitions.py``
that both the receipt and compiled-score compositions run.  They differ
only in where the :class:`ShieldPools` they mutate is stored.

Adding a shield mechanic or changing absorption order is one edit here.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from .shield_pools import (
    GENERAL,
    LIFELINE,
    MAGIC,
    PHYSICAL,
    Absorption,
    ShieldPools,
    _read_pool,
    _write_pool,
    expire_timed,
    grant,
)


def _apply_to_health(pools: Any, amount: float) -> tuple[float, float]:
    """Take ``amount`` out of health; returns ``(applied, overkill)``."""
    applied_to_health = min(amount, pools.health)
    overkill = max(0.0, amount - applied_to_health)
    pools.health = max(0.0, pools.health - applied_to_health)
    pools.health_damage += applied_to_health
    pools.overkill += overkill
    return applied_to_health, overkill


def absorb(
    pools: ShieldPools,
    damage: float,
    damage_type: str,
    event_time: float,
    *,
    healing_factor: float = 1.0,
) -> Absorption:
    """Apply one post-mitigation damage instance to a defender's pools.

    The order is: lapsed grants expire, the damage type's own pool absorbs,
    Lifelines arm against the damage still coming, the general pool absorbs,
    and whatever is left reaches health -- damage past health being overkill
    rather than more effective HP.

    ``healing_factor`` is the defender's live healing multiplier at this
    instant: a Lifeline's heal is healing, so a Grievous window open when it
    arms cuts it exactly as it cuts an authored heal.  A walk with no wound
    model leaves it at 1.0 and the arithmetic is unchanged.
    """
    if (
        not pools.timed
        and pools.threshold_shield is None
        and pools.threshold_health is None
        and pools.magic_shield == 0.0
        and pools.physical_shield == 0.0
        and pools.general_shield == 0.0
    ):
        # Nothing can absorb and no Lifeline can arm: the transition is the
        # bare health subtraction, bit-identical to the full path below with
        # every pool at zero.  This is the optimizer walk's dominant state.
        pools.damage_taken += damage
        applied_to_health, overkill = _apply_to_health(pools, damage)
        return Absorption(0.0, applied_to_health, overkill)
    timed = pools.timed
    if timed:
        expire_timed(pools, event_time)
        timed = pools.timed
    pools.damage_taken += damage
    remaining = damage
    absorbed = 0.0

    if damage_type == MAGIC:
        if timed:
            used = _drain(pools, MAGIC, remaining)
        else:
            used = min(pools.magic_shield, remaining)
            pools.magic_shield -= used
            pools.magic_absorbed += used
        remaining -= used
        pools.shield_absorbed += used
        absorbed += used
    elif damage_type == PHYSICAL:
        if timed:
            used = _drain(pools, PHYSICAL, remaining)
        else:
            used = min(pools.physical_shield, remaining)
            pools.physical_shield -= used
            pools.physical_absorbed += used
        remaining -= used
        pools.shield_absorbed += used
        absorbed += used

    armed = None
    if pools.threshold_shield is not None or pools.threshold_health is not None:
        armed = _arm_thresholds(
            pools, remaining, damage_type, event_time, healing_factor=healing_factor
        )
        if armed.shield_pool is not None and armed.shield_pool != GENERAL:
            # A typed Lifeline (Maw's magic shield) blocks the very hit that
            # armed it, but its own pool was already drained above.
            used = _drain(pools, armed.shield_pool, remaining)
            remaining -= used
            pools.shield_absorbed += used
            absorbed += used
        timed = pools.timed

    if timed:
        used = _drain(pools, GENERAL, remaining)
    else:
        used = min(pools.general_shield, remaining)
        pools.general_shield -= used
        pools.general_absorbed += used
    remaining -= used
    pools.shield_absorbed += used
    absorbed += used

    applied_to_health, overkill = _apply_to_health(pools, remaining)
    if armed is None:
        return Absorption(absorbed, applied_to_health, overkill)
    return Absorption(
        absorbed,
        applied_to_health,
        overkill,
        threshold_shield_triggered=armed.shield_pool is not None,
        threshold_shield_expires_at=armed.shield_expires_at,
        threshold_health_triggered=armed.health_triggered,
        threshold_health_heal=armed.health_heal,
        threshold_health_healed=armed.health_healed,
        threshold_health_reduced=armed.health_reduced,
    )


class _Armed(NamedTuple):
    """Which Lifelines this instance armed, for the caller's receipt row."""

    shield_pool: str | None = None
    shield_expires_at: float | None = None
    health_triggered: bool = False
    health_heal: float = 0.0
    health_healed: float = 0.0
    health_reduced: float = 0.0


_NOTHING_ARMED = _Armed()


def _arm_thresholds(
    pools: ShieldPools,
    remaining: float,
    damage_type: str,
    event_time: float,
    *,
    healing_factor: float = 1.0,
) -> _Armed:
    """Arm whichever Lifelines this damage would carry past their threshold.

    Both conditions read the health the defender still has, so a shield and
    a bonus-health Lifeline on the same defender judge the same crossing.
    The sourced wording is "damage that would reduce you *below*" the
    threshold, so damage landing exactly on it does not arm.
    """
    shield = pools.threshold_shield
    health = pools.threshold_health
    shield_due = (
        shield is not None
        and not shield.triggered
        and shield.amount > 0.0
        and shield.health_threshold > 0.0
        and pools.health - remaining < shield.health_threshold
        and shield.damage_type in ("all", damage_type)
    )
    health_due = (
        health is not None
        and not health.triggered
        and health.bonus > 0.0
        and health.health_ratio > 0.0
        and health.duration > 0.0
        and pools.health - remaining < pools.max_health * health.health_ratio
    )
    if not shield_due and not health_due:
        return _NOTHING_ARMED

    shield_pool: str | None = None
    expires_at: float | None = None
    if shield_due:
        granted = shield.amount
        if pools.venom_factor < 1.0 and shield.damage_type != MAGIC:
            # Venom cuts non-magic shields the target gains; this hit's venom
            # was applied before the Lifeline check.
            granted *= pools.venom_factor
        shield.triggered = True
        shield.amount = 0.0
        shield_pool = GENERAL if shield.damage_type == "all" else shield.damage_type
        expires_at = (
            event_time + shield.duration if shield.duration > 0.0 else float("inf")
        )
        shield.expired_at = expires_at
        grant(pools, granted, pool=shield_pool, expires_at=expires_at, source=LIFELINE)

    heal = 0.0
    healed = 0.0
    reduced = 0.0
    if health_due:
        pools.max_health += health.bonus
        pools.health += health.bonus
        health.triggered = True
        health.expires_at = event_time + health.duration
        # The bonus health is a grant, not healing, so a Grievous window
        # leaves it alone and cuts only the heal beside it.
        heal = health.heal * healing_factor
        reduced = health.heal - heal
        # The heal lands before the crossing damage, so it can only take the
        # health the defender was already missing.  Whatever the sourced heal
        # has left over is the caller's heal author to deliver.
        healed = min(heal, max(0.0, pools.max_health - pools.health))
        pools.health += healed
    return _Armed(
        shield_pool=shield_pool,
        shield_expires_at=expires_at,
        health_triggered=health_due,
        health_heal=heal,
        health_healed=healed,
        health_reduced=reduced,
    )


def _drain(pools: ShieldPools, pool: str, remaining: float) -> float:
    """Absorb from one pool, earliest-expiring grants before untimed ones.

    Lifeline-sourced absorption is credited to ``threshold_absorbed`` rather
    than to the pool the grant sits in, so the two stay separately reportable
    and the grand total counts each unit exactly once.
    """
    total, credited = _read_pool(pools, pool)
    absorbed = 0.0
    for shield in sorted(pools.timed, key=lambda entry: entry.expires_at):
        if shield.pool != pool:
            continue
        available = max(0.0, shield.amount)
        used = min(available, remaining)
        if used <= 0.0:
            continue
        shield.amount = available - used
        remaining -= used
        absorbed += used
        total = max(0.0, total - used)
        if shield.source == LIFELINE:
            pools.threshold_absorbed += used
        else:
            credited += used
        if remaining <= 1e-9:
            break
    if remaining > 0.0:
        used = min(total, remaining)
        total -= used
        absorbed += used
        credited += used
    _write_pool(pools, pool, total, credited)
    pools.timed = [shield for shield in pools.timed if shield.amount > 1e-9]
    return absorbed
