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
class DecayingStackRamp:
    """One declared ramp's resolved numbers."""

    per_stack: float
    max_stacks: int
    stack_duration: float

    def bonus_percent(self, live_stacks: int) -> float:
        """The bonus attack speed *live_stacks* stacks are worth, as a percent."""
        return 100.0 * self.per_stack * min(max(0, int(live_stacks)), self.max_stacks)


@dataclass(frozen=True, slots=True)
class RearmedWindow:
    """One declared re-armed window's resolved numbers."""

    bonus_percent: float
    duration: float
    cooldown: float
    refund_per_attack: float
    refund_per_crit: float

    def refund(self, critical_chance: float) -> float:
        """What one attack pays down this window's cooldown by.

        The critical share is weighted by the holder's chance, clamped to [0, 1].
        """
        return (
            self.refund_per_attack
            + max(0.0, min(1.0, float(critical_chance))) * self.refund_per_crit
        )


@dataclass(frozen=True, slots=True)
class SwingSchedule:
    """Every re-rating of one build's own attack stream, resolved together.

    A build holds at most one of each shape today and the type says so, but
    the merge is the point: two items re-rating one stream is one schedule,
    and the walk below reads both records on every swing rather than running
    twice.

    ``opening_rate_bonus_percent`` is what the *panel* rate already carries
    and this schedule re-applies itself: a re-armed window is folded into the
    public stat block as assumed-active, and the authored fight starts before
    the holder has attacked, so the opening rate has to give it back.
    """

    ramp: DecayingStackRamp | None
    window: RearmedWindow | None
    schedules_single_rotation: bool

    @property
    def opening_rate_bonus_percent(self) -> float:
        """The conditional bonus the opening rate must not carry."""
        return 0.0 if self.window is None else self.window.bonus_percent

    def schedules(self, *, one_rotation: bool) -> bool:
        """Whether this fight's attack stream is walked rather than flat-rated."""
        return self.schedules_single_rotation or not one_rotation


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
    schedules: list[SwingScheduleRule] = []
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
        swing_schedule=_merged_schedule(schedules, level),
    )


def _merged_schedule(
    declared: Sequence[SwingScheduleRule], level: int
) -> SwingSchedule | None:
    """Every declared re-rating of one attack stream, resolved into one record.

    ``None`` is the answer for a build that declares none, and it is the
    engine's instruction to rate the stream flat — a different statement from
    a schedule whose numbers happen to resolve to zero.
    """
    if not declared:
        return None
    ramp: DecayingStackRamp | None = None
    window: RearmedWindow | None = None
    for rule in declared:
        if rule.decaying_stacks is not None:
            stacks = rule.decaying_stacks
            ramp = DecayingStackRamp(
                per_stack=resolve(stacks.per_stack, level),
                max_stacks=int(resolve(stacks.max_stacks, level)),
                stack_duration=resolve(stacks.stack_duration, level),
            )
        if rule.refunded_window is not None:
            declared_window = rule.refunded_window
            window = RearmedWindow(
                bonus_percent=resolve(
                    declared_window.bonus_attack_speed_percent, level
                ),
                duration=resolve(declared_window.duration, level),
                cooldown=resolve(declared_window.cooldown, level),
                refund_per_attack=resolve(declared_window.refund_per_attack, level),
                refund_per_crit=resolve(declared_window.refund_per_crit, level),
            )
    return SwingSchedule(
        ramp=ramp,
        window=window,
        schedules_single_rotation=any(
            rule.schedules_single_rotation for rule in declared
        ),
    )


# How close to the fight's end a swing has to fall to be dropped: the walk
# compares against the duration, and a float sum that lands on it exactly is
# the last swing rather than one past the end.
_SWING_EPSILON = 1e-12


def swing_times(  # pylint: disable=too-many-arguments,too-many-locals
    schedule: SwingSchedule,
    *,
    attack_speed: float,
    attack_speed_ratio: float,
    duration_seconds: float,
    uptime: float = 1.0,
    critical_chance: float = 0.0,
) -> tuple[float, ...]:
    """Walk *schedule*, one swing at a time, and return when each lands.

    The first attack lands at ``t=0``.  A ramp gains one stack per completed
    attack, holds it for its declared duration and re-rates every later swing;
    a re-armed window is live from the second attack until its duration runs
    out, and every attack after the first pays down the cooldown that reopens
    it.  Nothing here reads a roster, a target or a damage number: the fight
    ledger consumes the timestamps and prices them itself.

    The arguments are the authored timing inputs, passed explicitly, so no
    caller can hide one in a global or let a stale fallback stand in for it.
    """
    if duration_seconds <= 0.0 or uptime <= 0.0 or attack_speed <= 0.0:
        return ()
    ramp, window = schedule.ramp, schedule.window
    times: list[float] = [0.0]
    stack_times: list[float] = [0.0]
    current = 0.0
    active_until = 0.0 if window is None else window.duration
    cooldown = 0.0 if window is None else window.cooldown
    refund = 0.0 if window is None else window.refund(critical_chance)
    # Call-time import: stats -> interpreters -> this module at import time.
    from ..stats import calculate_attack_speed

    first_attack = True
    while True:
        if ramp is None:
            stack_times.clear()
        else:
            stack_times[:] = [
                start for start in stack_times if current - start < ramp.stack_duration
            ]
        bonus = 0.0 if ramp is None else ramp.bonus_percent(len(stack_times))
        rate = calculate_attack_speed(attack_speed, attack_speed_ratio, bonus) * uptime
        if window is not None and not first_attack and current < active_until:
            rate += (
                calculate_attack_speed(0.0, attack_speed_ratio, window.bonus_percent)
                * uptime
            )
        if rate <= 0.0:
            break
        next_time = current + 1.0 / rate
        if next_time >= duration_seconds - _SWING_EPSILON:
            break
        if window is not None:
            cooldown = max(0.0, cooldown - (next_time - current))
            if not first_attack:
                cooldown = max(0.0, cooldown - refund)
                if cooldown <= 0.0:
                    active_until = next_time + window.duration
                    cooldown = window.cooldown
        times.append(next_time)
        if ramp is not None:
            stack_times.append(next_time)
        current = next_time
        first_attack = False
    return tuple(times)


__all__ = [
    "CHARGE_COUNT_FIELD",
    "NO_SIBLING",
    "NO_SIBLING_COUNT",
    "SHAPED_CHARGE_BREAKDOWN_PREFIX",
    "SHAPED_CHARGE_SUFFIX",
    "ChargedStrikeInterpretationError",
    "ChargedStrikeSlots",
    "DecayingStackRamp",
    "RearmedWindow",
    "SwingSchedule",
    "charged_strike_rules",
    "resolve_slots",
    "strike_fields",
    "strike_mechanic_id",
    "swing_times",
]
