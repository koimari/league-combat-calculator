"""Damage routing: three mechanics that move a packet rather than resize it.

None of these three is an amplifier and none is a defence the holder keeps.
An execution decides whether a packet *ends the fight*; a shield bypass
decides how much of the target's shielding the packet has to get through;
and a deferral decides *when* the holder pays damage that has already
happened.  Grouping them by that shared question is what lets the deferral,
whose registry entry is tagged as a starting defence because that is where the
resolver builds it, stop being a name-matched branch inside the defensive
resolver without claiming the holder took less damage.

Three lanes, because the family really is built in three places.  The pair
engine prices the two target-side rules, the defensive resolver builds the
deferral schedule at the opening with every other declared defence, and the
receipt walk reads all three declarations itself.

The walk lane is the odd one, because nothing here has a price: a deferral
moves damage in time, an execution ends a fight, and a venom resizes a barrier.
So this family's walk-side delivery is the program rider system and the kernel
state paths, ``program.events.Defer`` and ``Execute``, the ``SurvivalAction``
fields that carry them, and ``shield_ledger.ShieldPools.venom_factor``, and
what the walk interpreter emits is the rider or the state adjustment rather
than an amount.  That substitution is sound because a rider carries a stamp and
no ``packet_source`` at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DamageDeferralRule,
    DefenseField,
    DefenseMechanic,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    ExecuteRule,
    KernelField,
    RuleFamily,
    ShieldBypassRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import AnyValueRef, ValueRefError, resolve, resolve_flat
from .defense_state import DefenseInterpretationError, DefenseSlot

# The field names a routing rule compiles to on the pair lane.
EXECUTE_THRESHOLD_FIELD = "execute_threshold"
SHIELD_BYPASS_FRACTION_FIELD = "shield_bypass_fraction"
SHIELD_BYPASS_DURATION_FIELD = "shield_bypass_duration"

# The field names a routing rule compiles to on the walk lane.  They are
# spelled for the kernel state each one lands in rather than for the
# declaration it came from: ``venom_keep`` is the surviving share the shield
# ledger multiplies by, which is the complement of the declared cut, and
# naming it after the cut is how the two would silently swap.
VENOM_KEEP_FIELD = "venom_keep"
VENOM_DURATION_FIELD = "venom_duration"
DEFER_FRACTION_FIELD = "defer_fraction"
DEFER_DURATION_FIELD = "defer_duration"
DEFER_TICKS_FIELD = "defer_ticks"

# Ignore Pain's own sentence, published beside the resolved state.  It names
# what the deferral does rather than the item that carries it, because the
# citation beside it already names the item.
IGNORE_PAIN_NOTE = (
    "{owner} Ignore Pain defers the sourced fraction of each "
    "post-mitigation physical or magic packet; Defy clears the "
    "remaining store and heals after a qualifying champion takedown."
)

# Which resolved field each of the deferral's sourced keys lands in, and
# which of them are counts.  A table rather than seven statements saying the
# same thing seven times — and the melee/ranged pair is deliberately absent,
# because which of the two is read is a property of the *subject* and is
# decided below.
_DEFERRAL_SCHEDULE: tuple[tuple[str, DefenseField], ...] = (
    ("damage_deferral_duration", DefenseField.DAMAGE_DEFERRAL_DURATION),
    ("damage_deferral_ticks", DefenseField.DAMAGE_DEFERRAL_TICKS),
    ("defy_window", DefenseField.DEFY_WINDOW),
    ("defy_heal_bonus_ad_ratio", DefenseField.DEFY_HEAL_BONUS_AD_RATIO),
    ("defy_heal_duration", DefenseField.DEFY_HEAL_DURATION),
    ("defy_heal_ticks", DefenseField.DEFY_HEAL_TICKS),
)

_INTEGER_FIELDS = frozenset(
    {DefenseField.DAMAGE_DEFERRAL_TICKS, DefenseField.DEFY_HEAL_TICKS}
)

# Which reference each fight-free field is read from, per routing payload —
# this family's mirror of ``SUSTAIN_PAYLOAD_REFERENCES``.  Total over the
# family's three shapes, and the two empty entries are the answer rather than
# an omission: both carry a melee/ranged share their subject's range class
# picks, which a reader holding item names and no fight cannot pick.
FLAT_ROUTING_REFERENCES: Mapping[type, tuple[tuple[str, str], ...]] = {
    ExecuteRule: ((EXECUTE_THRESHOLD_FIELD, "threshold"),),
    ShieldBypassRule: (),
    DamageDeferralRule: (),
}


class DamageRoutingInterpretationError(ValueError):
    """A routing rule was asked something its payload does not answer."""


def pair_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """The two target-side routing rules, priced for the pair engine.

    The melee/ranged share is chosen here, from the build context's own range
    class, because that choice is made once per build and not per event — the
    same reason the magnitude carries a split rather than the typing carrying
    an attack class.
    """

    def field(name: str, value: float) -> KernelField:
        return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)

    payload = rule.payload
    if isinstance(payload, ExecuteRule):
        return (field(EXECUTE_THRESHOLD_FIELD, resolve(payload.threshold, ctx.level)),)
    if not isinstance(payload, ShieldBypassRule):
        raise DamageRoutingInterpretationError(
            f"{rule.mechanic_id} is priced on the pair lane and is neither "
            "an execution nor a shield bypass; the deferral is built by the "
            "defensive resolver, not here"
        )
    share = payload.fraction.melee if ctx.holder_is_melee else payload.fraction.ranged
    return (
        field(SHIELD_BYPASS_FRACTION_FIELD, resolve(share, ctx.level)),
        field(SHIELD_BYPASS_DURATION_FIELD, resolve(payload.duration, ctx.level)),
    )


def resolve_deferral(rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
    """The deferral schedule, against the subject that will pay it."""
    slot = DefenseSlot(rule)
    if slot.mechanic is not DefenseMechanic.IGNORE_PAIN:
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares damage_routing at the resolver and "
            "this family has no branch for it; a schedule with no arithmetic "
            "is a mechanic that would silently do nothing"
        )
    deferred_key = (
        "damage_deferral_melee" if subject.is_melee else "damage_deferral_ranged"
    )
    fields = [
        slot.grant(DefenseField.DAMAGE_DEFERRAL_FRACTION, slot.value(deferred_key))
    ]
    fields.extend(
        slot.grant(
            field,
            int(slot.value(key)) if field in _INTEGER_FIELDS else slot.value(key),
        )
        for key, field in _DEFERRAL_SCHEDULE
    )
    return DefenseOutcome(
        fields=tuple(fields),
        notes=(IGNORE_PAIN_NOTE.format(owner=slot.owner),),
    )


def walk_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """All three routing rules, as the riders the walk stages.

    One branch per declared payload, and each emits the rider or the state
    adjustment the kernel already understands rather than a price.  Field
    names differ from the pair lane's, and the venom's share is delivered as
    its complement — the ledger holds what SURVIVES, not what is cut — so
    this is a different body rather than the pair lane's with a lane swapped.

    The deferral's branch is the one that looks redundant and is not.  Its
    schedule is also built by :func:`resolve_deferral`, and what the resolver
    publishes is the holder's *opening defensive state* — the block a receipt
    reader sees.  What this emits is the rider on the incoming events the walk
    stages, which is a different consumer of the same declaration; the two are
    one producer each rather than two producers of one number, and the
    equivalence fixture asserts they agree.

    The melee/ranged share is chosen from the build context's range class,
    exactly as the pair lane does — but the *participant* whose range class
    that is differs by payload and is the caller's to supply: a deferral is
    resolved against the holder paying it and a venom against the holder
    applying it.
    """

    def field(name: str, value: float) -> KernelField:
        return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)

    payload = rule.payload
    if isinstance(payload, ExecuteRule):
        return (field(EXECUTE_THRESHOLD_FIELD, resolve(payload.threshold, ctx.level)),)
    if isinstance(payload, ShieldBypassRule):
        share = (
            payload.fraction.melee if ctx.holder_is_melee else payload.fraction.ranged
        )
        return (
            field(VENOM_KEEP_FIELD, 1.0 - resolve(share, ctx.level)),
            field(VENOM_DURATION_FIELD, resolve(payload.duration, ctx.level)),
        )
    if not isinstance(payload, DamageDeferralRule):
        raise DamageRoutingInterpretationError(
            f"{rule.mechanic_id} declares damage_routing and this family has "
            "no walk branch for it; a routing rule the walk cannot stage would "
            "silently do nothing"
        )
    slot = DefenseSlot(rule)
    deferred_key = (
        "damage_deferral_melee" if ctx.holder_is_melee else "damage_deferral_ranged"
    )
    return (
        field(DEFER_FRACTION_FIELD, slot.value(deferred_key)),
        field(DEFER_DURATION_FIELD, slot.value("damage_deferral_duration")),
        field(DEFER_TICKS_FIELD, slot.value("damage_deferral_ticks")),
    )


@dataclass(frozen=True, slots=True)
class Execution:
    """One build's declared execution threshold, and the item that carries it."""

    owner: str
    threshold: float


@dataclass(frozen=True, slots=True)
class ShieldBypass:
    """One build's declared shield bypass, resolved for its holder's range."""

    owner: str
    fraction: float
    duration: float


def routing_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every pair-priced routing rule *owners* bring, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DAMAGE_ROUTING
        and isinstance(rule.payload, (ExecuteRule, ShieldBypassRule))
    )


def _field(fields: tuple[KernelField, ...], name: str) -> float:
    """One compiled field by name, or a stop naming the question asked."""
    for compiled in fields:
        if compiled.name == name:
            return float(compiled.value)
    raise DamageRoutingInterpretationError(
        f"no routing field named {name!r} was compiled; the engine asked a "
        "declaration a question it does not answer"
    )


def _sole_rule(owners: Sequence[str], payload_type: type) -> BehaviorRule | None:
    """The one rule of *payload_type* this build declares, or ``None``.

    Two holders of one shape is a stop rather than a fold — how two of them
    compose is a declaration somebody owes, and guessing it here is the silent
    default this campaign exists to remove.
    """
    found = [
        rule for rule in walk_rules(owners) if isinstance(rule.payload, payload_type)
    ]
    if not found:
        return None
    if len(found) > 1:
        raise DamageRoutingInterpretationError(
            f"{[rule.owner for rule in found]} all declare "
            f"{payload_type.__name__} and no rule declares how two of them "
            "compose; the slice that declares a second one owns the fold"
        )
    return found[0]


def _flat_references(rule: BehaviorRule) -> tuple[tuple[str, AnyValueRef], ...]:
    """Every field one routing declaration carries with no fight to read."""
    payload = rule.payload
    names = FLAT_ROUTING_REFERENCES.get(type(payload))
    if names is None:
        raise DamageRoutingInterpretationError(
            f"{rule.mechanic_id} is not a damage-routing rule"
        )
    if not names:
        raise DamageRoutingInterpretationError(
            f"{rule.mechanic_id} carries a melee/ranged share its subject's "
            "range class picks, and this accessor has no fight to pick one "
            "from; read it through the lane accessor handed a build context"
        )
    return tuple((name, getattr(payload, attribute)) for name, attribute in names)


def _flat_fields(rule: BehaviorRule, lane: EngineLane) -> tuple[KernelField, ...]:
    """One routing declaration's numbers, resolved without any fight context.

    The arithmetic behind :func:`declared_execution`, field for field
    :func:`pair_fields`.  A reference needing a level or a fight fact is a stop
    naming the shape, exactly as sustain's fight-free reader refuses one.
    """
    references = _flat_references(rule)
    try:
        values = resolve_flat([reference for _, reference in references])
    except ValueRefError as exc:
        raise DamageRoutingInterpretationError(
            f"{rule.mechanic_id} declares a reference that needs a level or a "
            "fight fact, and this accessor has neither; read it through "
            "resolve_execution, which is handed the context it resolves against"
        ) from exc
    return tuple(
        KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)
        for (name, _), value in zip(references, values)
    )


def declared_execution(owners: Sequence[str]) -> Execution | None:
    """This build's execution threshold from flat references alone.

    The fight-free reader, for the callers holding item names and no fight:
    identical to :func:`resolve_execution` on a flat declaration, and a stop
    rather than a defaulted zero on one that needs a context.
    """
    rule = _sole_rule(owners, ExecuteRule)
    if rule is None:
        return None
    fields = _flat_fields(rule, EngineLane.PAIR_ENGINE)
    return Execution(
        owner=rule.owner, threshold=_field(fields, EXECUTE_THRESHOLD_FIELD)
    )


def resolve_execution(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> Execution | None:
    """This build's execution threshold, or ``None`` if nobody declares one.

    ``None`` is an answer and not a zero: no holder executes, so no rule ran
    and no health share is low enough to finish the target.
    """
    rule = _sole_rule(owners, ExecuteRule)
    if rule is None:
        return None
    fields = pair_fields(
        rule,
        build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        ),
        EngineLane.PAIR_ENGINE,
    )
    return Execution(
        owner=rule.owner, threshold=_field(fields, EXECUTE_THRESHOLD_FIELD)
    )


def resolve_shield_bypass(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ShieldBypass | None:
    """This build's shield bypass, or ``None`` if nobody declares one."""
    rule = _sole_rule(owners, ShieldBypassRule)
    if rule is None:
        return None
    fields = pair_fields(
        rule,
        build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        ),
        EngineLane.PAIR_ENGINE,
    )
    return ShieldBypass(
        owner=rule.owner,
        fraction=_field(fields, SHIELD_BYPASS_FRACTION_FIELD),
        duration=_field(fields, SHIELD_BYPASS_DURATION_FIELD),
    )


@dataclass(frozen=True, slots=True)
class Venom:
    """One build's declared shield venom as the walk's ledger holds it.

    ``keep`` is the surviving share of a granted shield, never the cut: the
    two are complements and the ledger multiplies by this one.
    """

    owner: str
    keep: float
    duration: float


@dataclass(frozen=True, slots=True)
class Deferral:
    """One build's declared damage deferral, as the walk's Defer rider."""

    owner: str
    fraction: float
    duration: float
    ticks: int


def walk_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every routing rule *owners* bring, in build order, for the walk lane.

    All three payload shapes, unlike :func:`routing_rules`: the walk stages
    the deferral as well, and reading only the two the pair engine prices is
    how the third would quietly keep arriving from somewhere else.
    """
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DAMAGE_ROUTING
    )


def _walk_fields(  # pylint: disable=too-many-arguments
    owners: Sequence[str],
    payload_type: type,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> tuple[BehaviorRule, tuple[KernelField, ...]] | None:
    """The one declaration of *payload_type* this build brings, compiled.

    ``None`` when nobody declares one, which is an answer and not a zero: no
    holder defers, executes or envenoms, so no rule ran.
    """
    rule = _sole_rule(owners, payload_type)
    if rule is None:
        return None
    return rule, walk_fields(
        rule,
        build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        ),
        EngineLane.RECEIPT_WALK,
    )


def walk_execution(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> Execution | None:
    """The Execute rider this build's declarations arm, or ``None``."""
    compiled = _walk_fields(
        owners,
        ExecuteRule,
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )
    if compiled is None:
        return None
    rule, fields = compiled
    return Execution(
        owner=rule.owner, threshold=_field(fields, EXECUTE_THRESHOLD_FIELD)
    )


def walk_venom(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> Venom | None:
    """The barrier-state adjustment this build's declarations arm, or ``None``.

    ``holder_is_melee`` is the **attacker's** range class: this venom is
    attacker-owned and rides whoever is dealing the damage.
    """
    compiled = _walk_fields(
        owners,
        ShieldBypassRule,
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )
    if compiled is None:
        return None
    rule, fields = compiled
    keep = _field(fields, VENOM_KEEP_FIELD)
    if keep >= 1.0:
        return None
    return Venom(
        owner=rule.owner,
        keep=max(0.0, keep),
        duration=max(0.0, _field(fields, VENOM_DURATION_FIELD)),
    )


def walk_deferral(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> Deferral | None:
    """The Defer rider this build's declarations arm, or ``None``.

    ``holder_is_melee`` is the **defender's** range class: the deferral's
    subject is its own holder, who is the participant paying it.
    """
    compiled = _walk_fields(
        owners,
        DamageDeferralRule,
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )
    if compiled is None:
        return None
    rule, fields = compiled
    return Deferral(
        owner=rule.owner,
        fraction=_field(fields, DEFER_FRACTION_FIELD),
        duration=_field(fields, DEFER_DURATION_FIELD),
        ticks=int(_field(fields, DEFER_TICKS_FIELD)),
    )


__all__ = [
    "DEFER_DURATION_FIELD",
    "DEFER_FRACTION_FIELD",
    "DEFER_TICKS_FIELD",
    "DamageRoutingInterpretationError",
    "Deferral",
    "EXECUTE_THRESHOLD_FIELD",
    "Execution",
    "FLAT_ROUTING_REFERENCES",
    "IGNORE_PAIN_NOTE",
    "SHIELD_BYPASS_DURATION_FIELD",
    "SHIELD_BYPASS_FRACTION_FIELD",
    "ShieldBypass",
    "VENOM_DURATION_FIELD",
    "VENOM_KEEP_FIELD",
    "Venom",
    "declared_execution",
    "pair_fields",
    "resolve_deferral",
    "resolve_execution",
    "resolve_shield_bypass",
    "routing_rules",
    "walk_deferral",
    "walk_execution",
    "walk_fields",
    "walk_rules",
    "walk_venom",
]
