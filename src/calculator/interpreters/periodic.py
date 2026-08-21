"""Damage on a clock, interpreted: three cadences of one declared family.

Seven items deal damage the fight's *clock* produces rather than damage an
event produces, and until this module they reached the engine as three
unrelated registry tags whose only shared vocabulary was the word "formula".
A burn is a window every ability hit re-arms; an aura pays a rate for as long
as the fight lasts; a fixed-interval strike lands a whole packet every N
seconds and nothing in between.  The declaration names which, and this module
is where a cadence becomes the record the fight engine already consumes.

Two things the engine used to reach for by name are now read off the rule:
Unending Despair's Anguish radius, which the engine spelled its item's name to
fetch for the receipt on every one of its events, and its self-heal share.
Both are declared absences for every other periodic strike, because "this
mechanic publishes no radius" and "this mechanic publishes a radius of zero"
are different claims about the item.

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
from ..item_behavior_catalog import behavior_rules, build_context
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


def _cadence_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One periodic strike's compiled numbers for *lane*.

    The cadence this strike compiles to, plus the proof its bases resolve.

    The lane is the only thing that varies between the two interpreters
    below.  Sharing the body rather than spelling it twice is what makes
    "the walk reads the same declaration the pair engine reads" a property
    of the tree instead of a claim two functions could drift out of.
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


class PeriodicPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``periodic`` family.

    Its number is a **preview** since this family retired: every cadence
    declares ``ViewTag.THEORETICAL`` on its pair lane and
    ``damage._add_burn_damage`` stamps ``pair_preview_of`` on the row it
    authors, so the honest one-attacker figure stays in the pair fight's own
    receipt and leaves every total the roster composes.
    """

    FAMILY = RuleFamily.PERIODIC
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This cadence's numbers, resolved for the one-attacker engine."""
        return _cadence_fields(rule, ctx, EngineLane.PAIR_ENGINE)


class PeriodicWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The receipt walk's answer for the ``periodic`` family.

    The half that retires ``periodic/receipt_walk`` (umbrella Amendment F's
    act, in the lane Amendment K rules and with the whole shape Amendment L,
    Ruling 1 requires).  Before it, the coupled walk consumed this family as
    ``participant_timeline._pair_run_fight``'s already-priced rows, which is
    what the deferral row said in its own words.  Now each row's ticks are a
    declaration and no price: the walk mitigates the declared magnitude
    itself, through ``survival.pricing.price_declared_packet``.

    What the declaration carries is enumerated at the authoring site rather
    than assumed here.  The magnitude is the cadence's **pre-mitigation
    aggregate** — the burn's refreshed window, the aura's fight duration and
    the interval strike's proc count are already folded into it, because all
    three allocate the cadence rather than amplifying it and the engine
    applies them before mitigation.  Each tick then carries its share of that
    aggregate, which is exactly the share of the row's damage that tick
    received.  The attack class is ``OTHER`` for every one of the seven,
    measured rather than defaulted: a periodic row is priced by
    ``damage._mitigate`` and by nothing else.  All seven declare magic, so
    the holder's static magic amp is a live term for the whole family and is
    delivered off the damage type by ``StaticHolderAmps.factor_for``.
    """

    FAMILY = RuleFamily.PERIODIC
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This cadence's numbers, resolved for the coupled roster walk."""
        return _cadence_fields(rule, ctx, EngineLane.RECEIPT_WALK)


PAIR_INTERPRETER = PeriodicPairInterpreter()
WALK_INTERPRETER = PeriodicWalkInterpreter()


def periodic_mechanic_id(owner: str) -> str:
    """*owner*'s periodic strike mechanic id, or a stop.

    What the pair engine needs to stamp the rows it authors with the mechanic
    each row previews: ``damage._add_burn_damage`` walks
    :class:`~..item_effects.DamageSource` records, which carry an item name
    and no rule id, and reading the id back off the declaration here is what
    keeps the stamp from being a second spelling of the mechanic slug inside
    the engine.

    A stop rather than a default: an unstamped periodic row would keep the
    pair engine's number in every roster total *and* leave the walk pricing
    the declaration, which is the double count this family's retirement
    exists to make unrepresentable.
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
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.PERIODIC
    )


def declares_self_heal(owners: Sequence[str]) -> bool:
    """Whether any declared periodic strike heals its holder.

    Answered from the declarations alone, with no build context: the tuple
    ledger's adequacy question is "could this build emit a self-heal packet",
    which is a property of what the items declare and not of the fight.
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
    "PAIR_INTERPRETER",
    "PERIODIC_INTERVAL_FIELD",
    "WALK_INTERPRETER",
    "PeriodicInterpretationError",
    "PeriodicPairInterpreter",
    "PeriodicSlots",
    "PeriodicWalkInterpreter",
    "declares_self_heal",
    "periodic_mechanic_id",
    "periodic_rules",
    "resolve_slots",
]
