"""Cast-triggered procs, interpreted: three tags, two shapes, one family.

Eight items deal damage that a *cast* arms and a cooldown re-arms.  Until this
module they reached the engine through three registry tags and three
compilers, two of which decided what an item carried by comparing its name:
Eclipse's self-shield and Malignance's magic-resistance shred were both
``if item_name == ...`` branches inside the number registry.

The declaration says it instead.  An ultimate proc opens a window an R cast
owns; everything else is a cooldown proc whose *trigger* the entry names, and
every sibling mechanic — the charge split, the attack-windup refund, the
two-hit gate, the shield — is a declared record or a declared ``None``.  Which
one an entry carries is decided by the registry's own schema, so a parse that
dropped half of Eclipse's shield raises naming item and key instead of
compiling an item that quietly stops shielding.

**The charge split is arithmetic, not a third number.**  Luden's Echo fires
six charges and pays a declared multiple when they all land on one target; how
much a *repeated* target takes is the remainder spread across the other five,
which is computed here from the two sourced numbers rather than declared as a
third that could disagree with them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    CooldownProcRule,
    EngineLane,
    KernelField,
    RuleFamily,
    UltimateProcRule,
)
from ..item_behavior_catalog import build_context, family_rules
from ..item_effects import (
    CooldownProcEffect,
    DamageSource,
    UltimateProcEffect,
    row_presentation,
)
from ..value_ref import AnyValueRef, resolve
from . import damage_formula

# The field a cast proc compiles to: the seconds before it can arm again.
PROC_COOLDOWN_FIELD = "proc_cooldown"

# How each shape's breakdown row is named when the entry names none itself.
# Presentation, kept beside the interpreter that builds the row.
PROC_SUFFIX = "proc"
PROC_BREAKDOWN_PREFIX = "proc_"
ULTIMATE_PROC_SUFFIX = "Hatefog"
ULTIMATE_PROC_BREAKDOWN_PREFIX = "ult_proc_"

# What a proc with no sibling of a given kind hands the engine.  The engine's
# own spelling for "this sibling does not exist"; written here so the
# declaration can say *nothing* rather than say zero.
NO_SIBLING = 0.0

# What a proc that does not split into charges hands the engine for its
# multi-target fields: no charges, and a multiplier of one on both the single
# and the repeated target.  The engine's own neutral element, named.
NO_CHARGES = 0
UNSPLIT_MULTIPLIER = 1.0


class CastProcInterpretationError(ValueError):
    """A rule reached this interpreter that is not a cast-triggered proc."""


def _sibling(reference: AnyValueRef | None, level: int) -> float:
    """A declared sibling's number, or the engine's "no sibling" spelling."""
    return NO_SIBLING if reference is None else resolve(reference, level)


def proc_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One proc's compiled numbers, stamped with *lane*.

    The clock this proc compiles to, plus the proof its bases resolve.  An
    ultimate proc's clock is the window it spreads over; a cooldown proc's is
    the wait before it re-arms.  Both are build-time numbers, and both are
    the field a damage lane can honestly compile.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.
    """
    payload = rule.payload
    if isinstance(payload, UltimateProcRule):
        clock = payload.duration
    elif isinstance(payload, CooldownProcRule):
        clock = payload.cooldown
    else:
        raise CastProcInterpretationError(
            f"{rule.mechanic_id} is not a cast-triggered proc rule"
        )
    damage_formula.compile_formula(payload.formula, ctx)
    return (
        KernelField(
            name=PROC_COOLDOWN_FIELD,
            value=resolve(clock, ctx.level),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


def proc_mechanic_id(owner: str) -> str:
    """*owner*'s cast-proc mechanic id, or a stop.

    A stop rather than a default: an unstamped proc row keeps the pair
    engine's number in every roster total while the walk prices the same
    declaration, and that is a double count.
    """
    rules = cast_proc_rules([owner])
    if not rules:
        raise CastProcInterpretationError(
            f"{owner} authors a cast-triggered proc and declares no cast_proc "
            "rule, so its pair row has no mechanic to be a preview of"
        )
    return rules[0].mechanic_id


def repeated_target_multiplier(charges: int, single_target: float) -> float:
    """A second target's share of one charge: what ``single_target`` leaves over."""
    return (single_target - UNSPLIT_MULTIPLIER) / max(1, charges - 1)


def _row(
    rule: BehaviorRule,
    ctx: BuildContext,
    *,
    prefix: str,
    suffix: str,
    **fields: object,
) -> DamageSource:
    """One declared proc's breakdown row, named by the entry or derived."""
    payload = rule.payload
    declared = row_presentation(rule.owner)
    key, name = declared or (
        f"{prefix}{rule.owner}",
        f"{rule.owner} ({suffix})",
    )
    return DamageSource(
        item_name=rule.owner,
        breakdown_key=key,
        display_name=name,
        damage_type=payload.formula.damage_class.value,
        raw_damage=damage_formula.compile_formula(payload.formula, ctx),
        **fields,  # type: ignore[arg-type]
    )


def cooldown_proc_effect(rule: BehaviorRule, ctx: BuildContext) -> CooldownProcEffect:
    """One declared cooldown proc as the record the fight engine consumes."""
    payload = rule.payload
    if not isinstance(payload, CooldownProcRule):
        raise CastProcInterpretationError(
            f"{rule.mechanic_id} is not a cooldown proc rule"
        )
    charged = payload.charged
    charges = NO_CHARGES
    single_target = UNSPLIT_MULTIPLIER
    repeated = UNSPLIT_MULTIPLIER
    if charged is not None:
        charges = int(resolve(charged.charges, ctx.level))
        single_target = resolve(charged.single_target_multiplier, ctx.level)
        repeated = repeated_target_multiplier(charges, single_target)
    threshold = payload.threshold
    stacks = payload.stacks
    shield = payload.self_shield
    return CooldownProcEffect(
        source=_row(
            rule,
            ctx,
            prefix=PROC_BREAKDOWN_PREFIX,
            suffix=PROC_SUFFIX,
            is_ability_damage=payload.is_ability_damage,
            basic_damage=payload.basic_damage,
            multi_target_charges=charges,
            repeated_target_multiplier=repeated,
            single_target_multiplier=single_target,
        ),
        cooldown=resolve(payload.cooldown, ctx.level),
        repeat_on_cooldown=payload.repeat_on_cooldown,
        late_phase=payload.late_phase,
        trigger=payload.trigger.value,
        damage_threshold_ratio=(
            NO_SIBLING
            if threshold is None
            else resolve(threshold.share_of_max_health, ctx.level)
        ),
        damage_threshold_window=(
            NO_SIBLING
            if threshold is None
            else resolve(threshold.window_seconds, ctx.level)
        ),
        on_attack_cooldown_refund=_sibling(payload.attack_cooldown_refund, ctx.level),
        stack_required=(
            int(NO_SIBLING)
            if stacks is None
            else int(resolve(stacks.required, ctx.level))
        ),
        stack_window=(
            NO_SIBLING if stacks is None else resolve(stacks.window_seconds, ctx.level)
        ),
        self_shield_melee_base=_sibling(
            None if shield is None else shield.melee_base, ctx.level
        ),
        self_shield_ranged_base=_sibling(
            None if shield is None else shield.ranged_base, ctx.level
        ),
        self_shield_melee_bonus_ad_ratio=_sibling(
            None if shield is None else shield.melee_bonus_ad_ratio, ctx.level
        ),
        self_shield_ranged_bonus_ad_ratio=_sibling(
            None if shield is None else shield.ranged_bonus_ad_ratio, ctx.level
        ),
        self_shield_duration=_sibling(
            None if shield is None else shield.duration, ctx.level
        ),
    )


def ultimate_proc_effect(rule: BehaviorRule, ctx: BuildContext) -> UltimateProcEffect:
    """One declared ultimate proc as the record the fight engine consumes."""
    payload = rule.payload
    if not isinstance(payload, UltimateProcRule):
        raise CastProcInterpretationError(
            f"{rule.mechanic_id} is not an ultimate proc rule"
        )
    return UltimateProcEffect(
        _row(
            rule,
            ctx,
            prefix=ULTIMATE_PROC_BREAKDOWN_PREFIX,
            suffix=ULTIMATE_PROC_SUFFIX,
        ),
        resolve(payload.duration, ctx.level),
        _sibling(payload.mr_reduction, ctx.level),
    )


@dataclass(frozen=True, slots=True)
class CastProcSlots:
    """One build's cast-triggered procs, split by the shape they declared.

    Two tuples rather than one, because the engine schedules them differently:
    a cooldown proc is armed by its own trigger and re-armed by its cooldown,
    while an ultimate proc's window opens at the R cast and closes with it.
    """

    cooldown_procs: tuple[CooldownProcEffect, ...]
    ultimate_procs: tuple[UltimateProcEffect, ...]


def cast_proc_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every cast-triggered proc *owners* declare, in build order."""
    return family_rules(owners, RuleFamily.CAST_PROC)


def self_shield_owners(owners: Sequence[str]) -> tuple[str, ...]:
    """Every held owner whose cast proc attaches a self shield to its event.

    Answered from the declarations alone, with no build context, and in build
    order so a receipt names the owners the way the caller supplied them.
    """
    return tuple(
        rule.owner
        for rule in cast_proc_rules(owners)
        if getattr(rule.payload, "self_shield", None) is not None
    )


def resolve_slots(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> CastProcSlots:
    """Every cast-triggered proc this build declares, split by shape.

    Build order is preserved within each shape, which is the order the
    registry's own loop appended them in and the order the engine's breakdown
    rows come out in.
    """
    cooldown_procs: list[CooldownProcEffect] = []
    ultimate_procs: list[UltimateProcEffect] = []
    for rule in cast_proc_rules(owners):
        ctx = build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        )
        if isinstance(rule.payload, UltimateProcRule):
            ultimate_procs.append(ultimate_proc_effect(rule, ctx))
        else:
            cooldown_procs.append(cooldown_proc_effect(rule, ctx))
    return CastProcSlots(
        cooldown_procs=tuple(cooldown_procs),
        ultimate_procs=tuple(ultimate_procs),
    )


__all__ = [
    "NO_CHARGES",
    "NO_SIBLING",
    "PROC_BREAKDOWN_PREFIX",
    "PROC_COOLDOWN_FIELD",
    "PROC_SUFFIX",
    "ULTIMATE_PROC_BREAKDOWN_PREFIX",
    "ULTIMATE_PROC_SUFFIX",
    "UNSPLIT_MULTIPLIER",
    "CastProcInterpretationError",
    "CastProcSlots",
    "cast_proc_rules",
    "proc_fields",
    "proc_mechanic_id",
    "self_shield_owners",
    "cooldown_proc_effect",
    "repeated_target_multiplier",
    "resolve_slots",
    "ultimate_proc_effect",
]
