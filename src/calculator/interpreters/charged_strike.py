"""Charged strikes, interpreted: four shapes of "not on every hit".

Eleven items strike harder than an on-hit does, and none of them strikes on
every hit.  A charge is spent on one attack, or a strike lands every Nth
application, or an ability arms a shaped charge, or an ultimate empowers a
run of the holder's own attacks.  The declaration says which shape an item
takes.  Every optional mechanic (Energized stacks, the lethality window,
Statikk's arc) is a declared record or a declared ``None``, chosen by the
registry's own schema so a dropped parse raises rather than being read as an
absence.

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
    FightFacts,
    KernelField,
    RepeatingStrikeRule,
    RuleFamily,
    ShapedChargeRule,
    SwingScheduleRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import (
    CooldownProcEffect,
    DamageSource,
    FirstAutoEffect,
    StackingOnHitEffect,
    UltimateAutoBuffEffect,
    counter_trigger,
    row_presentation,
)
from ..value_ref import AnyValueRef, resolve
from . import damage_formula
from .rearmed_swings import SwingSchedule, _merged_schedule

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


def strike_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One charged strike's compiled numbers, stamped with *lane*.

    The count this strike compiles to, plus the proof its bases resolve.
    Each shape's count is the thing that decides how often it is paid:
    empowered attacks, on-hit applications, a cooldown, or the ultimate's
    own attack count.  All four are build-time numbers.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.
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
    elif isinstance(payload, SwingScheduleRule):
        # A schedule is not spent, so what it compiles to is the ceiling
        # on what its ramp can hold.  A window-only schedule holds none
        # and says so with the family's own "no sibling" spelling.
        stacks = payload.decaying_stacks
        count = None if stacks is None else stacks.max_stacks
    else:
        raise ChargedStrikeInterpretationError(
            f"{rule.mechanic_id} is not a charged strike rule"
        )
    if isinstance(payload, (EmpoweredHitRule, RepeatingStrikeRule, ShapedChargeRule)):
        damage_formula.compile_formula(payload.formula, ctx)
    return (
        KernelField(
            name=CHARGE_COUNT_FIELD,
            value=_sibling(count, ctx.level),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


def strike_mechanic_id(owner: str) -> str:
    """*owner*'s damage-authoring charged-strike mechanic id, or a stop.

    A **swing schedule** is skipped rather than returned: Guinsoo's Rageblade
    declares one beside its on-hit strike and Yun Tal Wildarrows declares one
    alone, and neither authors a damage row.  A schedule changes how often the
    holder swings, which the pair engine applies and no walk re-prices, so
    returning one here would stamp somebody else's row as a preview of it.

    A stop rather than a default: an unstamped strike row keeps the pair
    engine's number in every roster total while the walk prices the same
    declaration, and that is a double count.
    """
    rules = [
        rule
        for rule in charged_strike_rules([owner])
        if not isinstance(rule.payload, SwingScheduleRule)
    ]
    if not rules:
        raise ChargedStrikeInterpretationError(
            f"{owner} authors a charged strike and declares no damaging "
            "charged_strike rule, so its pair row has no mechanic to be a "
            "preview of"
        )
    return rules[0].mechanic_id


def _payload_of(rule: BehaviorRule, shape: type) -> object:
    """*rule*'s payload if it is of *shape*, or a stop.

    The dispatch above has already chosen the branch; this keeps that choice
    checkable, and it raises under ``-O`` where an assertion would vanish.
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
        damage_type=payload.formula.damage_type,
        raw_damage=damage_formula.compile_formula(payload.formula, ctx),
        mechanic_id=rule.mechanic_id,
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
        counter_trigger=counter_trigger(rule.owner),
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

    Five fields because the engine schedules the five shapes differently, and
    ``empowered_auto_buff`` is singular because an ultimate empowers one run
    of attacks: a build holding two would be arming two windows over one
    attack stream, which the engine has never modelled and which a tuple would
    quietly claim it does.  ``swing_schedule`` is singular for the opposite
    reason — every declared re-rating of the stream is merged into the one
    schedule the stream has.
    """

    first_autos: tuple[FirstAutoEffect, ...]
    stacking_on_hits: tuple[StackingOnHitEffect, ...]
    shaped_charges: tuple[CooldownProcEffect, ...]
    empowered_auto_buff: UltimateAutoBuffEffect | None
    swing_schedule: SwingSchedule | None


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
    facts: FightFacts,
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
    schedules: list[SwingScheduleRule] = []
    for rule in charged_strike_rules(owners):
        ctx = build_context(rule.owner, facts)
        payload = rule.payload
        if isinstance(payload, EmpoweredHitRule):
            first_autos.append(_first_auto_effect(rule, ctx))
        elif isinstance(payload, RepeatingStrikeRule):
            stacking.append(_stacking_effect(rule, ctx))
        elif isinstance(payload, ShapedChargeRule):
            shaped.append(_shaped_charge_effect(rule, ctx))
        elif isinstance(payload, EmpoweredAutoBuffRule):
            buff = _empowered_auto_buff(rule, ctx)
        elif isinstance(payload, SwingScheduleRule):
            schedules.append(payload)
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
        swing_schedule=_merged_schedule(schedules, facts.level),
    )


__all__ = [
    "CHARGE_COUNT_FIELD",
    "NO_SIBLING",
    "NO_SIBLING_COUNT",
    "SHAPED_CHARGE_BREAKDOWN_PREFIX",
    "SHAPED_CHARGE_SUFFIX",
    "ChargedStrikeInterpretationError",
    "ChargedStrikeSlots",
    "charged_strike_rules",
    "resolve_slots",
    "strike_fields",
    "strike_mechanic_id",
]
