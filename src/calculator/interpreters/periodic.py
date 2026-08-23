"""Damage on a clock, interpreted: three cadences of one declared family.

Seven items deal damage the fight's *clock* produces rather than damage an
event produces.  A burn is a window every ability hit re-arms; an aura pays a
rate for as long as the fight lasts; a fixed-interval strike lands a whole
packet every N seconds and nothing in between.  The declaration names which,
and this module is where a cadence becomes the record the fight engine
consumes.

Unending Despair's Anguish radius and its self-heal share are read off the
rule.  Both are declared absences for every other periodic strike, because
"this mechanic publishes no radius" and "this mechanic publishes a radius of
zero" are different claims about the item.

Nothing here is memoized, for the same reason the catalog is not:
``refresh_item_effects()`` has to move the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    PeriodicCadence,
    PeriodicRule,
    RuleFamily,
)
from ..item_behavior_catalog import build_context, family_rules
from ..item_effects import BurnEffect, DamageSource, PeriodicEffect, damage_source
from ..value_ref import resolve
from . import damage_formula

# The field a periodic strike compiles to: the seconds between its packets.
# Unlike its damage, a cadence really is a build-time number.
PERIODIC_INTERVAL_FIELD = "periodic_interval"

# How each cadence's breakdown row is named.  Presentation, kept beside the
# interpreter that builds the row rather than in the registry, and keyed by
# the declared cadence so no item name chooses a prefix.
CADENCE_PRESENTATION: dict[PeriodicCadence, tuple[str, str]] = {
    PeriodicCadence.REFRESHED_BURN: ("burn_", "burn"),
    PeriodicCadence.CONTINUOUS_AURA: ("immolate_", "Immolate"),
    PeriodicCadence.FIXED_INTERVAL: ("periodic_", "Anguish"),
}

# What a fixed-interval strike that heals nobody hands the engine.  The
# engine's own spelling for "no self-heal packet"; written here so the
# declaration can say *nothing* rather than say zero.
NO_SELF_HEAL_SHARE = 0.0


class PeriodicInterpretationError(ValueError):
    """A rule reached this interpreter that is not a periodic strike."""


def _payload(rule: BehaviorRule) -> PeriodicRule:
    """*rule*'s periodic payload, or a stop."""
    payload = rule.payload
    if not isinstance(payload, PeriodicRule):
        raise PeriodicInterpretationError(
            f"{rule.mechanic_id} is not a periodic strike rule"
        )
    return payload


def cadence_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One periodic strike's compiled numbers, stamped with *lane*.

    The cadence this strike compiles to, plus the proof its bases resolve.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.
    """
    payload = _payload(rule)
    damage_formula.compile_formula(payload.formula, ctx)
    return (
        KernelField(
            name=PERIODIC_INTERVAL_FIELD,
            value=resolve(payload.interval, ctx.level),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


def periodic_mechanic_id(owner: str) -> str:
    """*owner*'s periodic strike mechanic id, or a stop.

    A stop rather than a default: an unstamped periodic row keeps the pair
    engine's number in every roster total while the walk prices the same
    declaration, and that is a double count.
    """
    rules = periodic_rules([owner])
    if not rules:
        raise PeriodicInterpretationError(
            f"{owner} authors a periodic row and declares no periodic rule, "
            "so its pair row has no mechanic to be a preview of"
        )
    return rules[0].mechanic_id


def _row(
    rule: BehaviorRule,
    ctx: BuildContext,
    *,
    event_interval: float | None = None,
) -> DamageSource:
    """One declared periodic strike's breakdown row.

    ``event_interval`` is the aura's own field on the engine's row and is
    ``None`` for the cadences whose spacing the engine reads elsewhere; the
    row's contract has always been that ``None`` means "this aggregate stays
    untimed".
    """
    payload = _payload(rule)
    prefix, suffix = CADENCE_PRESENTATION[payload.cadence]
    return damage_source(
        rule.owner,
        payload.formula.damage_class.value,
        damage_formula.compile_formula(payload.formula, ctx),
        suffix=suffix,
        breakdown_key=f"{prefix}{rule.owner}",
        event_interval=event_interval,
    )


@dataclass(frozen=True, slots=True)
class PeriodicSlots:
    """One build's periodic strikes, split by the cadence they declared.

    Three tuples rather than one, because the fight engine really does price
    the three cadences differently — a burn stretches past the fight's end, an
    aura is a rate times the fight, a fixed-interval strike is a packet count
    — and a single list would make the engine ask each record what it was.

    ``range_units`` is the targeting radius a fixed-interval strike publishes
    on each of its events, read off the declaration rather than fetched by
    item name at the point of use.  It is keyed by breakdown row, so a second
    such strike gets its own radius instead of borrowing the first one's, and
    a strike that publishes none is simply absent from it.
    """

    burns: tuple[BurnEffect, ...]
    auras: tuple[DamageSource, ...]
    intervals: tuple[PeriodicEffect, ...]
    range_units: Mapping[str, float]


def periodic_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every periodic strike *owners* declare, in build order."""
    return family_rules(owners, RuleFamily.PERIODIC)


def declares_self_heal(owners: Sequence[str]) -> bool:
    """Whether any declared periodic strike heals its holder, answered from the
    declarations alone rather than from a resolved fight.
    """
    return any(
        _payload(rule).self_heal_share is not None for rule in periodic_rules(owners)
    )


def resolve_slots(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> PeriodicSlots:
    """Every periodic strike this build declares, split by cadence.

    Build order is preserved within each cadence, which is the order the
    registry's own loop appended them in and the order the engine's breakdown
    rows come out in.
    """
    burns: list[BurnEffect] = []
    auras: list[DamageSource] = []
    intervals: list[PeriodicEffect] = []
    range_units: dict[str, float] = {}
    for rule in periodic_rules(owners):
        payload = _payload(rule)
        ctx = build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        )
        interval = resolve(payload.interval, ctx.level)
        if payload.cadence is PeriodicCadence.REFRESHED_BURN:
            if payload.duration is None:
                raise PeriodicInterpretationError(
                    f"{rule.mechanic_id} is a burn with no declared window; "
                    "validate_rule refuses one, so reaching here means a rule "
                    "was built past its own validation"
                )
            burns.append(
                BurnEffect(
                    _row(rule, ctx),
                    resolve(payload.duration, ctx.level),
                    interval,
                )
            )
            continue
        if payload.cadence is PeriodicCadence.CONTINUOUS_AURA:
            auras.append(_row(rule, ctx, event_interval=interval))
            continue
        share = payload.self_heal_share
        row = _row(rule, ctx)
        intervals.append(
            PeriodicEffect(
                row,
                interval,
                (NO_SELF_HEAL_SHARE if share is None else resolve(share, ctx.level)),
            )
        )
        if payload.aoe_range_units is not None:
            range_units[row.breakdown_key] = resolve(payload.aoe_range_units, ctx.level)
    return PeriodicSlots(
        burns=tuple(burns),
        auras=tuple(auras),
        intervals=tuple(intervals),
        range_units=range_units,
    )


__all__ = [
    "CADENCE_PRESENTATION",
    "NO_SELF_HEAL_SHARE",
    "PERIODIC_INTERVAL_FIELD",
    "PeriodicInterpretationError",
    "PeriodicSlots",
    "cadence_fields",
    "declares_self_heal",
    "periodic_mechanic_id",
    "periodic_rules",
    "resolve_slots",
]
