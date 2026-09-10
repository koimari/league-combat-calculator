"""The pools a participant carries, the shields granted into them, and when each expires."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

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
