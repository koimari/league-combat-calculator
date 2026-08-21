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

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    AttackCooldownRefundRule,
    BehaviorRule,
    BuildContext,
    CritDamageBonusRule,
    CritOccurrence,
    EngineLane,
    ForcedCritRule,
    KernelField,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve

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


class CritProfileInterpretationError(ValueError):
    """A crit declaration was asked something its payload does not answer."""


def crit_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """The sourced numbers one crit declaration resolves to.

    Three payloads, three field sets, and no shared default: a rule that is
    none of the three is a stop rather than an empty tuple, because an empty
    tuple here would be a crit profile that silently changes nothing.
    """

    def field(name: str, value: float) -> KernelField:
        return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)

    payload = rule.payload
    if isinstance(payload, CritDamageBonusRule):
        return (field(CRIT_DAMAGE_BONUS_FIELD, resolve(payload.bonus, ctx.level)),)
    if isinstance(payload, AttackCooldownRefundRule):
        return (
            field(COOLDOWN_REFUND_FIELD, resolve(payload.refund_fraction, ctx.level)),
        )
    if not isinstance(payload, ForcedCritRule):
        raise CritProfileInterpretationError(
            f"{rule.mechanic_id} is not a crit-profile rule"
        )
    fields = [
        field(FORCED_CRIT_RATIO_FIELD, resolve(payload.reduced_ratio, ctx.level)),
        field(FORCED_CRIT_COOLDOWN_FIELD, resolve(payload.cooldown, ctx.level)),
    ]
    if payload.heal is not None:
        fields.extend(
            (
                field(
                    FORCED_CRIT_HEAL_BASE_AD_FIELD,
                    resolve(payload.heal.base_ad_ratio, ctx.level),
                ),
                field(
                    FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD,
                    resolve(payload.heal.base_ad_ratio_ranged, ctx.level),
                ),
                field(
                    FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD,
                    resolve(payload.heal.missing_health_ratio, ctx.level),
                ),
                field(
                    FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD,
                    resolve(payload.heal.temporary_health_duration, ctx.level),
                ),
            )
        )
    return tuple(fields)


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
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> CritProfile:
    """Fold every holder's crit declarations into one profile.

    A build declaring nothing gets ``CritProfile(0.0, None, None)``: the zero
    is the declared answer "no holder adds crit damage", and the two ``None``s
    are the declared answer "nobody forces a crit or refunds a cooldown" — a
    different thing from a number that resolved to zero, which is why the two
    slots are optional records rather than floats.
    """
    damage_bonus = 0.0
    forced: ForcedCrit | None = None
    refund: CooldownRefund | None = None
    for rule in crit_rules(owners):
        fields = crit_fields(
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
    "CooldownRefund",
    "CritProfile",
    "CritProfileInterpretationError",
    "FORCED_CRIT_COOLDOWN_FIELD",
    "FORCED_CRIT_HEAL_BASE_AD_FIELD",
    "FORCED_CRIT_HEAL_BASE_AD_RANGED_FIELD",
    "FORCED_CRIT_HEAL_MISSING_HEALTH_FIELD",
    "FORCED_CRIT_RATIO_FIELD",
    "FORCED_CRIT_TEMP_HEALTH_DURATION_FIELD",
    "ForcedCrit",
    "crit_fields",
    "crit_rules",
    "resolve_profile",
]
