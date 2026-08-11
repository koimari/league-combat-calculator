"""Charged strikes, interpreted: four shapes of "not on every hit".

Eleven items strike harder than an on-hit does, and none of them strikes on
every hit.  A charge is spent on one attack, or a strike lands every Nth
application, or an ability arms a shaped charge, or an ultimate empowers a
run of the holder's own attacks.  Until this module the four shapes reached
the engine through four registry tags and four compilers, and two of those
compilers decided what an item carried by comparing its name: Voltaic
Cyclosword's temporary lethality was an ``item_name == ...`` branch, and
Fiendhunter Bolts' window was assembled inline in the projection loop.

The declaration says all four now.  Every optional mechanic — Energized
stacks, the lethality window, Statikk's arc — is a declared record or a
declared ``None``, chosen by the registry's own schema so a dropped parse
raises rather than being read as an absence.

**"This fires once" is a declaration.**  ``max_procs`` is always present and
is ``Const(1, "count")`` where the strike fires once, rather than being the
value a missing key falls through to; a second such strike would otherwise
inherit somebody else's answer by omission.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EmpoweredAutoBuffRule,
    EmpoweredHitRule,
    EngineLane,
    KernelField,
    RepeatingStrikeRule,
    RuleFamily,
    ShapedChargeRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import (
    CooldownProcEffect,
    DamageSource,
    FirstAutoEffect,
    StackingOnHitEffect,
    UltimateAutoBuffEffect,
    row_presentation,
)
from ..value_ref import AnyValueRef, resolve
from . import damage_formula

# The field a charged strike compiles to: how many times one build can spend
# it.  A count is a build-time number; the damage it carries is not.
CHARGE_COUNT_FIELD = "charge_count"

# How the shaped charge's breakdown row is named when the entry names none
# itself.  The other three shapes' entries all name their own rows.
SHAPED_CHARGE_SUFFIX = "Shaped Charge"
SHAPED_CHARGE_BREAKDOWN_PREFIX = "shaped_charge_"

# What a charged strike with no sibling of a given kind hands the engine.
NO_SIBLING = 0.0
NO_SIBLING_COUNT = 0


class ChargedStrikeInterpretationError(ValueError):
    """A rule reached this interpreter that is not a charged strike."""


def _sibling(reference: AnyValueRef | None, level: int) -> float:
    """A declared sibling's number, or the engine's "no sibling" spelling."""
    return NO_SIBLING if reference is None else resolve(reference, level)


def _sibling_count(reference: AnyValueRef | None, level: int) -> int:
    """A declared sibling's count, or the engine's "no sibling" spelling."""
    return NO_SIBLING_COUNT if reference is None else int(resolve(reference, level))


class ChargedStrikePairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``charged_strike`` family."""

    FAMILY = RuleFamily.CHARGED_STRIKE
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The count this strike compiles to, plus the proof its bases resolve.

        Each shape's count is the thing that decides how often it is paid:
        empowered attacks, on-hit applications, a cooldown, or the ultimate's
        own attack count.  All four are build-time numbers.
        """
        payload = rule.payload
        if isinstance(payload, EmpoweredHitRule):
            count = payload.max_procs
        elif isinstance(payload, RepeatingStrikeRule):
            count = payload.hits_required
        elif isinstance(payload, ShapedChargeRule):
            count = payload.cooldown
        elif isinstance(payload, EmpoweredAutoBuffRule):
            count = payload.empowered_auto_count
        else:
            raise ChargedStrikeInterpretationError(
                f"{rule.mechanic_id} is not a charged strike rule"
            )
        if not isinstance(payload, EmpoweredAutoBuffRule):
            damage_formula.compile_formula(payload.formula, ctx)
        return (
            KernelField(
                name=CHARGE_COUNT_FIELD,
                value=resolve(count, ctx.level),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            ),
        )


PAIR_INTERPRETER = ChargedStrikePairInterpreter()


def _payload_of(rule: BehaviorRule, shape: type) -> object:
    """*rule*'s payload if it is of *shape*, or a stop.

    The dispatch above has already chosen the branch; this is what keeps that
    choice checkable rather than assumed, and it raises under ``-O`` where an
    assertion would vanish.
    """
    if not isinstance(rule.payload, shape):
        raise ChargedStrikeInterpretationError(
            f"{rule.mechanic_id} is not a {shape.__name__}"
        )
    return rule.payload


def _row(
    rule: BehaviorRule,
    ctx: BuildContext,
    *,
    derived: tuple[str, str] | None = None,
    basic_damage: bool = False,
) -> DamageSource:
    """One declared strike's breakdown row, named by the entry or derived.

    Three of the four shapes' entries name their own row and the fourth's
    does not, so a shape that expects the entry to name it and finds nothing
    is a stop rather than a row invented from a prefix nobody chose.
    """
    payload = rule.payload
    declared = row_presentation(rule.owner)
    if declared is None and derived is None:
        raise ChargedStrikeInterpretationError(
            f"{rule.mechanic_id} names no breakdown row and its shape derives "
            "none; a row the engine publishes has to be somebody's statement"
        )
    key, name = declared or (
        f"{derived[0]}{rule.owner}",  # type: ignore[index]
        f"{rule.owner} ({derived[1]})",  # type: ignore[index]
    )
    return DamageSource(
        item_name=rule.owner,
        breakdown_key=key,
        display_name=name,
        damage_type=payload.formula.damage_class.value,
        raw_damage=damage_formula.compile_formula(payload.formula, ctx),
        basic_damage=basic_damage,
    )


def _first_auto_effect(rule: BehaviorRule, ctx: BuildContext) -> FirstAutoEffect:
    """One declared empowered hit as the record the fight engine consumes."""
    payload = _payload_of(rule, EmpoweredHitRule)
    energized = payload.energized
    lethality = payload.temporary_lethality
    chain = payload.chain_targets
    return FirstAutoEffect(
        _row(rule, ctx, basic_damage=payload.basic_damage),
        max_procs=int(resolve(payload.max_procs, ctx.level)),
        temporary_lethality_melee=_sibling(
            None if lethality is None else lethality.melee, ctx.level
        ),
        temporary_lethality_ranged=_sibling(
            None if lethality is None else lethality.ranged, ctx.level
        ),
        temporary_lethality_duration=_sibling(
            None if lethality is None else lethality.duration, ctx.level
        ),
        energized_max_stacks=_sibling_count(
            None if energized is None else energized.max_stacks, ctx.level
        ),
        energized_attack_stacks=_sibling_count(
            None if energized is None else energized.stacks_per_attack, ctx.level
        ),
        energized_ability_trigger=(
            energized is not None and energized.abilities_also_charge
        ),
        chain_targets_min=_sibling_count(
            None if chain is None else chain.minimum, ctx.level
        ),
        chain_targets_max=_sibling_count(
            None if chain is None else chain.maximum, ctx.level
        ),
    )


def _stacking_effect(rule: BehaviorRule, ctx: BuildContext) -> StackingOnHitEffect:
    """One declared every-Nth-hit strike as the engine's record."""
    payload = _payload_of(rule, RepeatingStrikeRule)
    return StackingOnHitEffect(
        source=_row(rule, ctx, basic_damage=payload.basic_damage),
        hits_required=int(resolve(payload.hits_required, ctx.level)),
        tracks_target_health=damage_formula.reads_target_current_health(
            payload.formula
        ),
    )


def _shaped_charge_effect(rule: BehaviorRule, ctx: BuildContext) -> CooldownProcEffect:
    """One declared shaped charge as the engine's record."""
    payload = _payload_of(rule, ShapedChargeRule)
    return CooldownProcEffect(
        _row(
            rule,
            ctx,
            derived=(SHAPED_CHARGE_BREAKDOWN_PREFIX, SHAPED_CHARGE_SUFFIX),
        ),
        resolve(payload.cooldown, ctx.level),
    )


def _empowered_auto_buff(
    rule: BehaviorRule, ctx: BuildContext
) -> UltimateAutoBuffEffect:
    """One declared empowered-attack window as the engine's record."""
    payload = _payload_of(rule, EmpoweredAutoBuffRule)
    return UltimateAutoBuffEffect(
        item_name=rule.owner,
        bonus_attack_speed_percent=resolve(
            payload.bonus_attack_speed_percent, ctx.level
        ),
        empowered_auto_count=int(resolve(payload.empowered_auto_count, ctx.level)),
        duration=resolve(payload.duration, ctx.level),
        reduced_crit_ratio=resolve(payload.reduced_crit_ratio, ctx.level),
        natural_crit_true_damage_ratio=resolve(
            payload.natural_crit_true_damage_ratio, ctx.level
        ),
    )


@dataclass(frozen=True, slots=True)
class ChargedStrikeSlots:
    """One build's charged strikes, split by the shape they declared.

    Four fields because the engine schedules the four shapes differently, and
    ``empowered_auto_buff`` is singular because an ultimate empowers one run
    of attacks: a build holding two would be arming two windows over one
    attack stream, which the engine has never modelled and which a tuple would
    quietly claim it does.
    """

    first_autos: tuple[FirstAutoEffect, ...]
    stacking_on_hits: tuple[StackingOnHitEffect, ...]
    shaped_charges: tuple[CooldownProcEffect, ...]
    empowered_auto_buff: UltimateAutoBuffEffect | None


def charged_strike_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every charged strike *owners* declare, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.CHARGED_STRIKE
    )


def resolve_slots(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ChargedStrikeSlots:
    """Every charged strike this build declares, split by shape.

    Build order is preserved within each shape, which is the order the
    registry's own loop appended them in and the order the engine's breakdown
    rows come out in.
    """
    first_autos: list[FirstAutoEffect] = []
    stacking: list[StackingOnHitEffect] = []
    shaped: list[CooldownProcEffect] = []
    buff: UltimateAutoBuffEffect | None = None
    for rule in charged_strike_rules(owners):
        ctx = build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        )
        payload = rule.payload
        if isinstance(payload, EmpoweredHitRule):
            first_autos.append(_first_auto_effect(rule, ctx))
        elif isinstance(payload, RepeatingStrikeRule):
            stacking.append(_stacking_effect(rule, ctx))
        elif isinstance(payload, ShapedChargeRule):
            shaped.append(_shaped_charge_effect(rule, ctx))
        elif isinstance(payload, EmpoweredAutoBuffRule):
            buff = _empowered_auto_buff(rule, ctx)
        else:
            raise ChargedStrikeInterpretationError(
                f"{rule.mechanic_id} declares charged_strike and no shape this "
                "interpreter can read; a charged strike with no shape is a "
                "declaration nothing prices"
            )
    return ChargedStrikeSlots(
        first_autos=tuple(first_autos),
        stacking_on_hits=tuple(stacking),
        shaped_charges=tuple(shaped),
        empowered_auto_buff=buff,
    )


__all__ = [
    "CHARGE_COUNT_FIELD",
    "NO_SIBLING",
    "NO_SIBLING_COUNT",
    "PAIR_INTERPRETER",
    "SHAPED_CHARGE_BREAKDOWN_PREFIX",
    "SHAPED_CHARGE_SUFFIX",
    "ChargedStrikeInterpretationError",
    "ChargedStrikePairInterpreter",
    "ChargedStrikeSlots",
    "charged_strike_rules",
    "resolve_slots",
]
