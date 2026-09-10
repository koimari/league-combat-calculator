"""How a declared amp magnitude becomes a fraction, and the fields it compiles to."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..item_behavior import (
    AbsoluteWindow,
    BehaviorRule,
    BuildContext,
    DeltaAmpRule,
    EngineLane,
    Fixed,
    KernelField,
    LivePredicate,
    Magnitude,
    MeleeRangedSplit,
    PartAmpRule,
    RampModel,
    RampPerSecond,
    RampPerStack,
    StatScaled,
    TargetBonusHealthScaled,
    TriggerWindow,
    compiled_value,
)
from ..value_ref import resolve

# The field names a delta-amp rule compiles to.  A slot's magnitude is a
# fraction of the pool it prices, never a multiplier: the multiplier is the
# chain's, and folding fractions is what keeps two holders additive.  The two
# window bounds appear only for a rule whose activation declares them.
AMP_FRACTION_FIELD = "amp_fraction"


AMP_BASE_FRACTION_FIELD = "amp_base_fraction"


AMP_PER_HUNDRED_STAT_FIELD = "amp_fraction_per_hundred_stat"


WINDOW_START_FIELD = "window_start"


WINDOW_END_FIELD = "window_end"


WINDOW_DURATION_FIELD = "window_duration"


LIVE_THRESHOLD_FIELD = "live_threshold"


class DeltaAmpInterpretationError(ValueError):
    """A magnitude shape reached this interpreter with no arithmetic for it."""


def magnitude_fraction(magnitude: Magnitude, ctx: BuildContext) -> float:
    """The fraction *magnitude* is worth for the fight *ctx* describes.

    One branch per member of the magnitude union, and the union is exactly
    the set of shapes the registry's amp schemas implement — so a new schema
    is a new member and a new member is a new branch, rather than a silent
    fall-through to zero.
    """
    match magnitude:
        case Fixed():
            return resolve(magnitude.value, ctx.level)
        case RampPerSecond():
            return _ramp_per_second(magnitude, ctx)
        case TargetBonusHealthScaled():
            return _target_bonus_health_scaled(magnitude, ctx)
        case RampPerStack():
            return _ramp_per_stack(magnitude, ctx)
        case MeleeRangedSplit():
            return _melee_ranged_split(magnitude, ctx)
        case StatScaled():
            raise DeltaAmpInterpretationError(
                f"{ctx.owner} scales with the holder's {magnitude.stat.value}, "
                "which is not a build fact this context carries; its base and "
                f"rate compile to the {AMP_BASE_FRACTION_FIELD!r} and "
                f"{AMP_PER_HUNDRED_STAT_FIELD!r} fields and PartAmp.fraction "
                "takes the reading"
            )
        case _:
            raise DeltaAmpInterpretationError(
                f"{type(magnitude).__name__} has no delta-amp arithmetic yet; the "
                "slice that declares a rule with it owns the branch"
            )


def _melee_ranged_split(magnitude: MeleeRangedSplit, ctx: BuildContext) -> float:
    """Whichever of the two sourced rates the holder's range class earns."""
    reference = magnitude.melee if ctx.holder_is_melee else magnitude.ranged
    return resolve(reference, ctx.level)


def _ramp_per_second(magnitude: RampPerSecond, ctx: BuildContext) -> float:
    """A time ramp's average value over the fight, capped by its maximum.

    The ramp is at half its final height on average, hence the ``/ 2``.
    """
    per_second = resolve(magnitude.per_second, ctx.level)
    maximum = resolve(magnitude.maximum, ctx.level)
    stacks = min(ctx.fight_duration_seconds, maximum / per_second)
    return per_second * stacks / 2.0


def _target_bonus_health_scaled(
    magnitude: TargetBonusHealthScaled, ctx: BuildContext
) -> float:
    """A ratio that reaches ``maximum`` when the target hits the cap.

    The scaling reads the *target's* bonus health and never compares it with
    the holder's — the reading the registry's own accessor documented, kept
    here because this is now the only place it is implemented.
    """
    maximum = resolve(magnitude.maximum, ctx.level)
    cap = resolve(magnitude.bonus_health_cap, ctx.level)
    if cap <= 0.0:
        raise DeltaAmpInterpretationError(
            f"{ctx.owner}: a target-bonus-health cap must be positive; a "
            "non-positive one is a registry defect, not a full-strength amp"
        )
    return max(0.0, maximum) * min(max(0.0, ctx.target_bonus_health) / cap, 1.0)


def _ramp_per_stack(magnitude: RampPerStack, ctx: BuildContext) -> float:
    """A per-stack ramp at the stack count the fight's length implies.

    The stack count is the declared cadence applied to the fight duration,
    floored at one — the holder is assumed to have opened with the mechanic —
    and capped by the declared maximum.  ``model`` says how the stacks are
    summed, and only ``EXACT`` has an implementation here: no delta-amp rule
    declares ``CESARO_APPROX``, and writing arithmetic for a shape nothing
    reaches would be exactly the orphan branch D-51 forbids.
    """
    if magnitude.model is not RampModel.EXACT:
        raise DeltaAmpInterpretationError(
            f"{ctx.owner}: no delta-amp rule declares the "
            f"{magnitude.model.value} ramp model, so this interpreter has no "
            "arithmetic for it; the slice that declares one owns the branch"
        )
    per_stack = resolve(magnitude.per_stack, ctx.level)
    max_stacks = int(resolve(magnitude.max_stacks, ctx.level))
    seconds_per_stack = resolve(magnitude.seconds_per_stack, ctx.level)
    stacks = min(
        max_stacks, max(1, int(ctx.fight_duration_seconds / seconds_per_stack))
    )
    return per_stack * stacks


def _magnitude_fields(
    magnitude: Magnitude,
    ctx: BuildContext,
    field: Callable[[str, float], KernelField],
) -> tuple[KernelField, ...]:
    """The compiled numbers a magnitude contributes: one field, or two.

    Every shape but :class:`StatScaled` resolves to a single fraction.  A
    stat-scaled one cannot: half of it reads the holder's stat block, which this
    context does not carry, so its halves compile separately and
    :meth:`PartAmp.fraction` folds them with the reading.  Splitting the field
    keeps "the holder had no bonus mana" and "nobody asked" different answers.
    """
    if isinstance(magnitude, StatScaled):
        return (
            field(AMP_BASE_FRACTION_FIELD, resolve(magnitude.base, ctx.level)),
            field(
                AMP_PER_HUNDRED_STAT_FIELD, resolve(magnitude.per_hundred, ctx.level)
            ),
        )
    return (field(AMP_FRACTION_FIELD, magnitude_fraction(magnitude, ctx)),)


def amp_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """Every number one amp rule contributes, stamped with *lane*.

    The fraction always; the window bounds when the activation declares an
    absolute one.  This is the single path from a declaration to a number an
    engine uses — a caller that resolved a `ValueRef` itself would be a
    second reader of the same declaration.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.  The walk needs its
    own reading because a walk that prices a declaration itself has nowhere to
    take the holder's static amps from
    (:func:`resolve_static_holder_amps`, ``survival.pricing.DeclaredPacket``).
    """
    payload = rule.payload
    if not isinstance(payload, (DeltaAmpRule, PartAmpRule)):
        raise DeltaAmpInterpretationError(f"{rule.mechanic_id} is not a delta-amp rule")

    def field(name: str, value: float) -> KernelField:
        return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)

    fields = list(_magnitude_fields(payload.magnitude, ctx, field))
    if isinstance(payload.activation, AbsoluteWindow):
        fields.append(
            field(WINDOW_START_FIELD, resolve(payload.activation.start, ctx.level))
        )
        fields.append(
            field(WINDOW_END_FIELD, resolve(payload.activation.end, ctx.level))
        )
    if isinstance(payload.activation, LivePredicate):
        # The *threshold* is a sourced number and compiles here; the pool it
        # is compared against does not exist yet and must not be guessed at
        # build time.  That asymmetry is what ``requires_live_pool`` names,
        # and it is why the comparison lives in ``live_predicate_holds`` and
        # not in a field.
        fields.append(
            field(
                LIVE_THRESHOLD_FIELD, resolve(payload.activation.threshold, ctx.level)
            )
        )
    if isinstance(payload.activation, TriggerWindow):
        fields.append(
            field(
                WINDOW_DURATION_FIELD, resolve(payload.activation.duration, ctx.level)
            )
        )
    return tuple(fields)


def _declared_field(
    rule: BehaviorRule, fields: Sequence[KernelField], name: str
) -> float:
    """One compiled field of one holder's rule, or a stop.

    A missing field means the rule's activation or magnitude does not declare
    what the caller is asking for — asking a window's end of a rule with no
    window — and that is a programming error, never a zero."""
    missing = (
        f"{rule.mechanic_id} compiles no {name!r} field; the "
        "engine asked its declaration a question it does not answer"
    )
    return compiled_value(fields, name, DeltaAmpInterpretationError, missing)
