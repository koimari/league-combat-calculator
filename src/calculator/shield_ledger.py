"""One authoritative shield/health transition for every damage instance.

Absorption order and state mutation live here and nowhere else.  Every walk
in the calculator drives :func:`absorb`: the two ordered damage walks in
``damage.py`` and the one survival kernel in ``survival/transitions.py``
that both the receipt and compiled-score compositions run.  They differ
only in where the :class:`ShieldPools` they mutate is stored.

Adding a shield mechanic or changing absorption order is one edit here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

#: The three pools a shield can sit in.  A typed pool absorbs only its own
#: damage type; the general pool absorbs every type, true damage included.
PHYSICAL = "physical"
MAGIC = "magic"
GENERAL = "general"

#: Marks a timed grant a Lifeline armed, so receipts can report threshold
#: absorption apart from the pool the grant happens to sit in.
LIFELINE = "Lifeline"


@dataclass(slots=True)
class TimedShield:
    """A grant inside one pool's total that lapses at a sourced time.

    The pool float is the running total; this is a sub-ledger of the part of
    it that expires.  Timed grants drain before the untimed remainder so a
    shield cannot outlive its window by being saved for later damage.
    """

    amount: float
    expires_at: float
    pool: str = GENERAL
    source: str = ""


@dataclass(slots=True)
class ThresholdShield:
    """A Lifeline shield: it arms before the hit that would cross a threshold.

    ``damage_type`` names both what can arm it and the pool the grant lands
    in, so Maw of Malmortius' sourced magic shield never absorbs a physical
    hit.  ``"all"`` lands in the general pool.  It arms once per fight, and
    blocks the very instance that armed it.
    """

    amount: float
    health_threshold: float
    duration: float
    damage_type: str = "all"
    triggered: bool = False
    expired_at: float | None = None


@dataclass(slots=True)
class ThresholdHealth:
    """A Lifeline that answers with bonus health and a heal, not a shield.

    Both land before the crossing damage, so the transition applies them:
    the bonus health in full, and as much of the heal as the defender's
    missing health can take.  Protoplasm Harness sources the rest "over the
    same duration", which is a heal author's job, not absorption's.

    ``expires_at`` is stamped when the Lifeline arms, so the temporary
    maximum has a modeled end the way every timed shield does.
    """

    bonus: float
    heal: float
    health_ratio: float
    duration: float
    triggered: bool = False
    expires_at: float | None = None
    expired: bool = False


@dataclass(slots=True)
class ShieldPools:
    """One defender's absorbing state plus the totals a receipt reports."""

    health: float
    max_health: float
    physical_shield: float = 0.0
    magic_shield: float = 0.0
    general_shield: float = 0.0
    timed: list[TimedShield] = field(default_factory=list)
    threshold_shield: ThresholdShield | None = None
    threshold_health: ThresholdHealth | None = None
    #: Serpent's Fang: the surviving share of shields this defender gains.
    venom_factor: float = 1.0
    damage_taken: float = 0.0
    health_damage: float = 0.0
    overkill: float = 0.0
    shield_absorbed: float = 0.0
    physical_absorbed: float = 0.0
    magic_absorbed: float = 0.0
    general_absorbed: float = 0.0
    threshold_absorbed: float = 0.0
    shield_expired: float = 0.0


class Absorption(NamedTuple):
    """What one damage instance did, for the caller's receipt row.

    A tuple rather than a dataclass on purpose: one of these is built for
    every damage action in the optimizer's hot walk, where a frozen
    dataclass costs roughly 3.5x as much to allocate.
    """

    absorbed: float
    applied_to_health: float
    overkill: float
    threshold_shield_triggered: bool = False
    threshold_shield_expires_at: float | None = None
    threshold_health_triggered: bool = False
    #: The heal a threshold-health Lifeline started, after any live Grievous
    #: window cut it -- what a heal author still owes the defender.
    threshold_health_heal: float = 0.0
    #: The part of it the arming instant could take -- the transition has to
    #: apply this itself, because it lands before the crossing damage does.
    #: Anything left over belongs to the caller's own heal author.
    threshold_health_healed: float = 0.0
    #: What the live Grievous window took off the sourced heal, for the
    #: caller's ``healing_reduced`` receipt.
    threshold_health_reduced: float = 0.0


def build_pools(
    health: float,
    *,
    starting_health: float | None = None,
    magic_shield: float = 0.0,
    physical_shield: float = 0.0,
    general_shield: float = 0.0,
    threshold_shield_amount: float = 0.0,
    threshold_shield_health_ratio: float = 0.0,
    threshold_shield_duration: float = 0.0,
    threshold_shield_damage_type: str = "all",
    threshold_health_bonus: float = 0.0,
    threshold_health_heal: float = 0.0,
    threshold_health_ratio: float = 0.0,
    threshold_health_duration: float = 0.0,
) -> ShieldPools:
    """Stage one defender's resolved starting defenses as pools.

    The one place defense values become absorbing state, so the one-pair
    engine and the coupled ledger cannot stage the same item differently.
    A Lifeline with no amount is absent rather than present-and-inert.

    ``starting_health`` is the participant's health at the first instant of
    the fight.  It defaults to full health; an authored value is bounded to
    ``(0, health]`` by its parser, and every ratio Lifeline still arms off
    the MAXIMUM health, exactly as the game states them.
    """
    threshold_shield = None
    if threshold_shield_amount > 0.0:
        threshold_shield = ThresholdShield(
            amount=threshold_shield_amount,
            health_threshold=health * max(0.0, threshold_shield_health_ratio),
            duration=max(0.0, threshold_shield_duration),
            damage_type=threshold_shield_damage_type or "all",
        )
    threshold_health = None
    if threshold_health_bonus > 0.0:
        threshold_health = ThresholdHealth(
            bonus=threshold_health_bonus,
            heal=max(0.0, threshold_health_heal),
            health_ratio=max(0.0, threshold_health_ratio),
            duration=max(0.0, threshold_health_duration),
        )
    return ShieldPools(
        health=(
            health
            if starting_health is None
            else max(0.0, min(float(starting_health), health))
        ),
        max_health=health,
        magic_shield=max(0.0, magic_shield),
        physical_shield=max(0.0, physical_shield),
        general_shield=max(0.0, general_shield),
        threshold_shield=threshold_shield,
        threshold_health=threshold_health,
    )


def is_inert(pools: ShieldPools) -> bool:
    """Whether no pool can absorb and no Lifeline can arm.

    An inert defender's walk reduces bit-for-bit to sequential floored health
    subtraction, which callers use as a fast path.  It lives here so a new
    mechanic on :class:`ShieldPools` cannot leave a caller's shortcut behind.
    """
    threshold_shield = pools.threshold_shield
    threshold_health = pools.threshold_health
    return (
        pools.magic_shield <= 0.0
        and pools.physical_shield <= 0.0
        and pools.general_shield <= 0.0
        and not pools.timed
        and (
            threshold_shield is None
            or threshold_shield.amount <= 0.0
            or threshold_shield.health_threshold <= 0.0
        )
        and (
            threshold_health is None
            or threshold_health.bonus <= 0.0
            or threshold_health.health_ratio <= 0.0
            or threshold_health.duration <= 0.0
        )
    )


def grant(
    pools: ShieldPools,
    amount: float,
    *,
    pool: str = GENERAL,
    expires_at: float | None = None,
    source: str = "",
) -> None:
    """Add a shield to one pool, timed when the grant has an expiry.

    Every shield a fight hands out enters the pools here, so the pool total
    and its expiry sub-ledger can never disagree."""
    remaining, absorbed = _read_pool(pools, pool)
    _write_pool(pools, pool, remaining + amount, absorbed)
    if expires_at is not None:
        pools.timed.append(
            TimedShield(amount=amount, expires_at=expires_at, pool=pool, source=source)
        )


def expire_timed(pools: ShieldPools, event_time: float) -> float:
    """Drop timed grants whose window closed at or before ``event_time``."""
    if not pools.timed:
        return 0.0
    surviving: list[TimedShield] = []
    expired_total = 0.0
    for shield in pools.timed:
        if shield.expires_at > event_time + 1e-9:
            surviving.append(shield)
            continue
        amount = max(0.0, shield.amount)
        if amount > 0.0:
            remaining, absorbed = _read_pool(pools, shield.pool)
            _write_pool(pools, shield.pool, max(0.0, remaining - amount), absorbed)
            pools.shield_expired += amount
            expired_total += amount
    pools.timed = surviving
    return expired_total


# The sourced rule, from the Wiki's Health page, whose worked example is
# Protoplasm Harness itself: "A decrease in maximum health does not change
# current health (unless it would exceed the new maximum health). ... When the
# passive runs out, maximum health decreases by 200 from 1200 to 1000. Current
# health remains at 700."  A defender that spent more than the grant keeps
# every point it has; only an overhang above the new maximum is clamped away.
# https://wiki.leagueoflegends.com/en-us/Health
# Cached by ``python scripts/decompose_wiki.py --fetch "Health"``
# (``data/wiki-raw/Health.wiki``; the sentence is the Overview section's).
def expire_temporary_max_health(pools: ShieldPools, amount: float) -> float:
    """Remove a temporary maximum-health grant; return what was removed.

    The one implementation of the sourced rule above; both walks that carry a
    temporary maximum call it."""
    removed = min(max(0.0, amount), pools.max_health)
    pools.max_health -= removed
    pools.health = min(pools.health, pools.max_health)
    return removed


def expire_threshold_health(pools: ShieldPools, event_time: float) -> float:
    """Close an armed temporary-health Lifeline whose window has lapsed."""
    health = pools.threshold_health
    if (
        health is None
        or not health.triggered
        or health.expired
        or health.expires_at is None
        or event_time < health.expires_at - 1e-9
    ):
        return 0.0
    health.expired = True
    return expire_temporary_max_health(pools, health.bonus)


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


def _read_pool(pools: ShieldPools, pool: str) -> tuple[float, float]:
    """One pool's ``(remaining, absorbed)`` counters, failing closed on an unknown pool."""
    if pool == PHYSICAL:
        return pools.physical_shield, pools.physical_absorbed
    if pool == MAGIC:
        return pools.magic_shield, pools.magic_absorbed
    if pool == GENERAL:
        return pools.general_shield, pools.general_absorbed
    raise ValueError(f"shield_ledger: unknown pool {pool!r}")


def _write_pool(
    pools: ShieldPools, pool: str, remaining: float, absorbed: float
) -> None:
    """Store one pool's ``(remaining, absorbed)`` counters."""
    if pool == PHYSICAL:
        pools.physical_shield, pools.physical_absorbed = remaining, absorbed
    elif pool == MAGIC:
        pools.magic_shield, pools.magic_absorbed = remaining, absorbed
    elif pool == GENERAL:
        pools.general_shield, pools.general_absorbed = remaining, absorbed
    else:
        raise ValueError(f"shield_ledger: unknown pool {pool!r}")
