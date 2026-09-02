"""The critical-strike profile, interpreted: three declarations, one answer.

A build's crit behaviour is three unrelated questions the registry files
under one pair of tags, and until this module each was a separate
accumulator inside the number registry's own effect ladder:

* how much *more* a critical strike pays than the game's base multiplier,
* whether one strike of the fight is **made** to crit, at what fraction of a
  full one, and what it heals,
* and how much of the holder's remaining ability cooldowns a basic attack
  refunds — a crit item's passive that changes no damage number at all.

Here they are three payloads of one family, and this module is where a build
turns into the one profile the engines read.  ``resolve_profile`` is the
whole public surface: it folds every holder's declarations into a
:class:`CritProfile`, and a build that declares nothing gets a profile whose
bonus is a **declared** zero rather than an accumulator that never ran.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..item_behavior import (
    AttackCooldownRefundRule,
    BehaviorRule,
    BuildContext,
    CritDamageBonusRule,
    CritOccurrence,
    EngineLane,
    FightFacts,
    ForcedCritRule,
    KernelField,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import AnyValueRef, ValueRefError, resolve, resolve_flat

# The field names a crit-profile rule compiles to.  One per declared number,
# named for what it *is* rather than for the item it came from.
CRIT_DAMAGE_BONUS_FIELD = "crit_damage_bonus"
COOLDOWN_REFUND_FIELD = "attack_cooldown_refund_fraction"
FORCED_CRIT_RATIO_FIELD = "forced_crit_reduced_ratio"
FORCED_CRIT_COOLDOWN_FIELD = "forced_crit_cooldown"
FORCED_CRIT_HEAL_BASE_AD_FIELD = "forced_crit_heal_base_ad_ratio"
FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD = "forced_crit_heal_base_ad_ratio_ranged"
FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD = "forced_crit_heal_missing_health_ratio"
FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD = "forced_crit_temporary_health_duration"


# Which reference each compiled field is read from, per payload shape — the
# family's mirror of ``SUSTAIN_PAYLOAD_REFERENCES``.  One table so the
# contextual and fight-free readers cannot compile different field sets for
# one declaration.
CRIT_PAYLOAD_REFERENCES: Mapping[type, tuple[tuple[str, str], ...]] = {
    CritDamageBonusRule: ((CRIT_DAMAGE_BONUS_FIELD, "bonus"),),
    AttackCooldownRefundRule: ((COOLDOWN_REFUND_FIELD, "refund_fraction"),),
    ForcedCritRule: (
        (FORCED_CRIT_RATIO_FIELD, "reduced_ratio"),
        (FORCED_CRIT_COOLDOWN_FIELD, "cooldown"),
    ),
}

# The heal a forced crit declares, when it declares one.  Separate from the
# table above because these four are optional together: an item that forces a
# crit and heals nothing carries none of them.
FORCED_CRIT_HEAL_REFERENCES: tuple[tuple[str, str], ...] = (
    (FORCED_CRIT_HEAL_BASE_AD_FIELD, "base_ad_ratio"),
    (FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD, "base_ad_ratio_ranged"),
    (FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD, "missing_health_ratio"),
    (FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD, "temporary_health_duration"),
)


class CritProfileInterpretationError(ValueError):
    """A crit declaration was asked something its payload does not answer."""


def crit_references(rule: BehaviorRule) -> tuple[tuple[str, AnyValueRef], ...]:
    """Every field one crit declaration carries, and the reference behind it.

    A rule that is none of the three payloads is a stop rather than an empty
    tuple, because an empty tuple here would be a crit profile that silently
    changes nothing.
    """
    payload = rule.payload
    names = CRIT_PAYLOAD_REFERENCES.get(type(payload))
    if names is None:
        raise CritProfileInterpretationError(
            f"{rule.mechanic_id} is not a crit-profile rule"
        )
    references = [(name, getattr(payload, attribute)) for name, attribute in names]
    if isinstance(payload, ForcedCritRule) and payload.heal is not None:
        references.extend(
            (name, getattr(payload.heal, attribute))
            for name, attribute in FORCED_CRIT_HEAL_REFERENCES
        )
    return tuple(references)


def crit_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """The sourced numbers one crit declaration resolves to, at one fight."""
    return tuple(
        KernelField(
            name=name,
            value=resolve(reference, ctx.level),
            lane=lane,
            rule_id=rule.mechanic_id,
        )
        for name, reference in crit_references(rule)
    )


def _flat_fields(rule: BehaviorRule, lane: EngineLane) -> tuple[KernelField, ...]:
    """One crit declaration's numbers, resolved without any fight context.

    The arithmetic behind :func:`declared_crit_profile`, field for field
    :func:`crit_fields`.  A reference needing a level or a fight fact is a
    stop naming the shape, exactly as sustain's fight-free reader refuses one.
    """
    references = crit_references(rule)
    try:
        values = resolve_flat([reference for _, reference in references])
    except ValueRefError as exc:
        raise CritProfileInterpretationError(
            f"{rule.mechanic_id} declares a reference that needs a level or a "
            "fight fact, and this accessor has neither; read it through "
            "resolve_profile, which is handed the context it resolves against"
        ) from exc
    return tuple(
        KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)
        for (name, _), value in zip(references, values, strict=False)
    )


@dataclass(frozen=True, slots=True)
class ForcedCrit:  # pylint: disable=too-many-instance-attributes
    """One build's forced critical strike, resolved.

    ``heals`` is the declared-absence question answered once: an item that
    forces a crit and heals nothing has ``heal_base_ad_ratio == 0.0`` because
    it declared no heal, and the four ratios are zero for the same reason
    rather than because a formula measured zero.
    """

    owner: str
    occurrence: CritOccurrence
    reduced_ratio: float
    cooldown: float
    heals: bool
    heal_base_ad_ratio: float
    heal_base_ad_ratio_ranged: float
    heal_missing_health_ratio: float
    temporary_health_duration: float


@dataclass(frozen=True, slots=True)
class CooldownRefund:
    """One build's ability-cooldown refund, and the holder it is filed under."""

    owner: str
    fraction: float


@dataclass(frozen=True, slots=True)
class CritProfile:
    """Everything a build's declarations say about its critical strikes.

    ``damage_bonus`` sums, because two crit items really do both add to the
    multiplier; the other two are single-holder slots and a second holder is
    a stop rather than a silently-chosen winner, exactly as the shred slot
    treats two shreds of one resistance.
    """

    damage_bonus: float
    forced_crit: ForcedCrit | None
    cooldown_refund: CooldownRefund | None


def crit_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every crit-profile rule *owners* bring, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.CRIT_PROFILE
    )


def _field(fields: tuple[KernelField, ...], name: str) -> float:
    """One compiled field by name, or a stop naming the question asked."""
    for compiled in fields:
        if compiled.name == name:
            return float(compiled.value)
    raise CritProfileInterpretationError(
        f"no crit-profile field named {name!r} was compiled; the engine asked "
        "a declaration a question it does not answer"
    )


def _forced_crit(rule: BehaviorRule, fields: tuple[KernelField, ...]) -> ForcedCrit:
    """One forced-crit declaration, resolved into the record engines read."""
    payload = rule.payload
    if not isinstance(payload, ForcedCritRule):
        raise CritProfileInterpretationError(
            f"{rule.mechanic_id} is not a forced-crit rule"
        )
    heals = payload.heal is not None
    return ForcedCrit(
        owner=rule.owner,
        occurrence=payload.occurrence,
        reduced_ratio=_field(fields, FORCED_CRIT_RATIO_FIELD),
        cooldown=_field(fields, FORCED_CRIT_COOLDOWN_FIELD),
        heals=heals,
        heal_base_ad_ratio=(
            _field(fields, FORCED_CRIT_HEAL_BASE_AD_FIELD) if heals else 0.0
        ),
        heal_base_ad_ratio_ranged=(
            _field(fields, FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD) if heals else 0.0
        ),
        heal_missing_health_ratio=(
            _field(fields, FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD) if heals else 0.0
        ),
        temporary_health_duration=(
            _field(fields, FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD) if heals else 0.0
        ),
    )


def resolve_profile(
    owners: Sequence[str],
    *,
    facts: FightFacts,
) -> CritProfile:
    """Fold every holder's crit declarations into one profile.

    A build declaring nothing gets ``CritProfile(0.0, None, None)``: the zero
    is the declared answer "no holder adds crit damage", and the two ``None``s
    are the declared answer "nobody forces a crit or refunds a cooldown" — a
    different thing from a number that resolved to zero, which is why the two
    slots are optional records rather than floats.
    """
    return _fold(
        owners,
        lambda rule: crit_fields(
            rule,
            build_context(rule.owner, facts),
            EngineLane.PAIR_ENGINE,
        ),
    )


def declared_crit_profile(owners: Sequence[str]) -> CritProfile:
    """This build's crit profile from flat references alone — no fight needed."""
    return _fold(owners, lambda rule: _flat_fields(rule, EngineLane.PAIR_ENGINE))


def _fold(
    owners: Sequence[str],
    compile_fields: Callable[[BehaviorRule], tuple[KernelField, ...]],
) -> CritProfile:
    """Fold this build's crit declarations, however their fields were compiled.

    ``damage_bonus`` sums in build order, so the two readers replay one float
    addition rather than two spellings of it.
    """
    damage_bonus = 0.0
    forced: ForcedCrit | None = None
    refund: CooldownRefund | None = None
    for rule in crit_rules(owners):
        fields = compile_fields(rule)
        payload = rule.payload
        if isinstance(payload, CritDamageBonusRule):
            damage_bonus += _field(fields, CRIT_DAMAGE_BONUS_FIELD)
        elif isinstance(payload, AttackCooldownRefundRule):
            if refund is not None:
                raise CritProfileInterpretationError(
                    f"{refund.owner!r} and {rule.owner!r} both declare an "
                    "attack cooldown refund and no rule declares how two "
                    "refunds compose; the slice that declares a second one "
                    "owns the fold"
                )
            refund = CooldownRefund(
                owner=rule.owner, fraction=_field(fields, COOLDOWN_REFUND_FIELD)
            )
        else:
            if forced is not None:
                raise CritProfileInterpretationError(
                    f"{forced.owner!r} and {rule.owner!r} both force a critical "
                    "strike and no rule declares which one the strike pays; the "
                    "slice that declares a second one owns the fold"
                )
            forced = _forced_crit(rule, fields)
    return CritProfile(
        damage_bonus=damage_bonus, forced_crit=forced, cooldown_refund=refund
    )


__all__ = [
    "COOLDOWN_REFUND_FIELD",
    "CRIT_DAMAGE_BONUS_FIELD",
    "CRIT_PAYLOAD_REFERENCES",
    "FORCED_CRIT_COOLDOWN_FIELD",
    "FORCED_CRIT_HEAL_BASE_AD_FIELD",
    "FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD",
    "FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD",
    "FORCED_CRIT_HEAL_REFERENCES",
    "FORCED_CRIT_RATIO_FIELD",
    "FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD",
    "CooldownRefund",
    "CritProfile",
    "CritProfileInterpretationError",
    "ForcedCrit",
    "crit_fields",
    "crit_references",
    "crit_rules",
    "declared_crit_profile",
    "resolve_profile",
]
