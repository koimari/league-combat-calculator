"""The amp chain, interpreted: a declared magnitude becomes one number.

Amplification is the campaign's named diagnosis.  Seven ordered chain slots
multiply a fight's total, their order is load-bearing, and until this module
each slot's magnitude lived as a closure compiled inside the number registry
— a callable a declaration cannot hold and a reader cannot diff.  Here the
shape is a :class:`~..item_behavior.DeltaAmpRule`, the numbers are live
references into the registries, and the arithmetic that turns one into the
other lives in exactly one function per magnitude shape.

The pair engine reads a slot through :func:`resolve_slot`, which folds every
holder's contribution the way the engine folded it before: a multiplier that
starts at ``1.0`` and takes one ``+=`` per holder.  That is not an accident
of style — ``(1.0 + f) - 1.0`` is not ``f`` in binary floating point, and the
whole point of shipping Hypershot first is that a moved number means the
kernel is wrong rather than the mechanic.

Nothing here is a compiled-kernel lane: H5 is descoped, so every amp rule
carries ``ReceiptOnly`` and this interpreter serves ``PAIR_ENGINE`` only.
The receipt-walk half of the family arrives with the amps the coupled walk
actually owns.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    AmpChainSlot,
    BehaviorRule,
    BuildContext,
    DeltaAmpRule,
    EngineLane,
    Fixed,
    KernelField,
    Magnitude,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RuleFamily,
    TargetBonusHealthScaled,
    chain_rank,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve

# The one field name a delta-amp rule compiles to.  A slot's magnitude is a
# fraction of the pool it prices, never a multiplier: the multiplier is the
# chain's, and folding fractions is what keeps two holders additive.
AMP_FRACTION_FIELD = "amp_fraction"


class DeltaAmpInterpretationError(ValueError):
    """A magnitude shape reached this interpreter with no arithmetic for it."""


def magnitude_fraction(magnitude: Magnitude, ctx: BuildContext) -> float:
    """The fraction *magnitude* is worth for the fight *ctx* describes.

    One branch per member of the magnitude union, and the union is exactly
    the set of shapes the registry's amp schemas implement — so a new schema
    is a new member and a new member is a new branch, rather than a silent
    fall-through to zero.
    """
    if isinstance(magnitude, Fixed):
        return resolve(magnitude.value, ctx.level)
    if isinstance(magnitude, RampPerSecond):
        return _ramp_per_second(magnitude, ctx)
    if isinstance(magnitude, TargetBonusHealthScaled):
        return _target_bonus_health_scaled(magnitude, ctx)
    if isinstance(magnitude, RampPerStack):
        return _ramp_per_stack(magnitude, ctx)
    raise DeltaAmpInterpretationError(
        f"{type(magnitude).__name__} has no delta-amp arithmetic yet; the "
        "slice that declares a rule with it owns the branch"
    )


def _ramp_per_second(magnitude: RampPerSecond, ctx: BuildContext) -> float:
    """A time ramp's average value over the fight, capped by its maximum.

    The ramp climbs ``per_second`` until it reaches ``maximum``, so it has
    been at half its final height on average — hence the ``/ 2``.  The
    fight is assumed to last long enough for the whole climb only when
    ``duration`` allows it, which is what the ``min`` is for.
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


class DeltaAmpPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``delta_amp`` family."""

    FAMILY = RuleFamily.DELTA_AMP
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This rule's amp fraction, resolved against the live registries."""
        payload = rule.payload
        if not isinstance(payload, DeltaAmpRule):
            raise DeltaAmpInterpretationError(
                f"{rule.mechanic_id} is not a delta-amp rule"
            )
        return (
            KernelField(
                name=AMP_FRACTION_FIELD,
                value=magnitude_fraction(payload.magnitude, ctx),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            ),
        )


PAIR_INTERPRETER = DeltaAmpPairInterpreter()


@dataclass(frozen=True, slots=True)
class AmpSlot:
    """One chain slot, resolved for one build.

    ``fractions`` runs parallel to ``rules`` — one sourced fraction per
    holder, in build order — because the slot's occupants are additive among
    themselves and a caller that reports per-source rows needs the parts,
    not only the sum.  ``owner`` names the breakdown row, derived from the
    rule rather than passed in, which is what removes the item name from the
    engine's side of the call.
    """

    slot: AmpChainSlot
    rules: tuple[BehaviorRule, ...]
    fractions: tuple[float, ...]

    @property
    def multiplier(self) -> float:
        """What the engine multiplies by: ``1.0`` plus the holders' sum.

        The spelling is load-bearing, not stylistic.  ``1.0 + sum(f)`` and a
        running ``+=`` per holder disagree in the last bits once a slot has
        two occupants, and ``math.fsum`` disagrees with both.  This is the
        engine's own spelling for the one slot that *can* hold several
        mechanics (``WHOLE_TOTAL``); every other slot has a single holder, for
        which all three coincide exactly.  Keeping one fold is what lets this
        migration claim no number moved rather than no number moved much.
        """
        return 1.0 + sum(self.fractions)

    @property
    def owner(self) -> str:
        """The holder the slot's breakdown row is filed under."""
        return self.rules[0].owner

    def sources(self) -> tuple[tuple[str, float], ...]:
        """Each holder with the fraction it contributes, in build order."""
        return tuple(
            (rule.owner, fraction) for rule, fraction in zip(self.rules, self.fractions)
        )


def slot_rules(owners: Sequence[str], slot: AmpChainSlot) -> tuple[BehaviorRule, ...]:
    """Every declared rule *owners* bring to one chain slot, in build order.

    Build order is the order the items were bought, which is the order the
    engine's own accumulator folded them in.  Preserving it is what makes a
    migration provably arithmetic-neutral rather than merely equivalent in
    exact arithmetic.
    """
    rank = chain_rank(slot)
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DELTA_AMP
        and isinstance(rule.payload, DeltaAmpRule)
        and rule.payload.lane_chain_rank == rank
    )


def resolve_slot(
    owners: Sequence[str],
    slot: AmpChainSlot,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
) -> AmpSlot | None:
    """One chain slot's multiplier for this build, or ``None`` if nobody has it.

    ``None`` is an answer and not a zero: no holder declares the slot, so no
    rule ran and there is no number to report.  A holder whose sourced
    fraction really is zero returns a slot with a multiplier of ``1.0``,
    which the engine then measures rather than skips.
    """
    rules = slot_rules(owners, slot)
    if not rules:
        return None
    fractions: list[float] = []
    for rule in rules:
        ctx = build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
        )
        fields = PAIR_INTERPRETER.compile(rule, ctx)
        fractions.append(
            float(next(f.value for f in fields if f.name == AMP_FRACTION_FIELD))
        )
    return AmpSlot(slot=slot, rules=rules, fractions=tuple(fractions))


__all__ = [
    "AMP_FRACTION_FIELD",
    "AmpSlot",
    "DeltaAmpInterpretationError",
    "DeltaAmpPairInterpreter",
    "PAIR_INTERPRETER",
    "magnitude_fraction",
    "resolve_slot",
    "slot_rules",
]
