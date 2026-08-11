"""The amp chain, interpreted: a declared magnitude becomes one number.

Amplification is the campaign's named diagnosis.  Seven ordered chain slots
multiply a fight's total, their order is load-bearing, and until this module
each slot's magnitude lived as a closure compiled inside the number registry
— a callable a declaration cannot hold and a reader cannot diff.  Here the
shape is a :class:`~..item_behavior.DeltaAmpRule`, the numbers are live
references into the registries, and the arithmetic that turns one into the
other lives in exactly one function per magnitude shape.

The pair engine reads a slot through :func:`resolve_slot`, which folds every
holder's contribution the way the engine folded it before: ``1.0`` plus the
holders' sum, never ``math.fsum`` and never a running ``+=``.  That is not an
accident of style — the three spellings land on different floats once a slot
has two occupants, and the whole point of shipping Hypershot first is that a
moved number means the kernel is wrong rather than the mechanic.

Nothing here is a compiled-kernel lane: H5 is descoped, so every amp rule
carries ``ReceiptOnly`` and this interpreter serves ``PAIR_ENGINE`` only.
The receipt-walk half of the family arrives with the amps the coupled walk
actually owns.

Everything the engine takes from a declaration comes through
:meth:`DeltaAmpPairInterpreter.compile` — the fraction, the window bounds —
and everything it *asks* of one comes through :class:`AmpSlot`.  A question a
rule does not answer raises; it never resolves to a zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    AbsoluteWindow,
    AfterTrigger,
    AmpChainSlot,
    BehaviorRule,
    BonusTyping,
    BuildContext,
    Comparison,
    DeltaAmpRule,
    EngineLane,
    ExcludeTrigger,
    Fixed,
    Isolation,
    KernelField,
    LivePredicate,
    Magnitude,
    MeleeRangedSplit,
    Probe,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RuleFamily,
    TargetBonusHealthScaled,
    TriggerWindow,
    WindowBoundary,
    WindowMerge,
    chain_rank,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve

# The field names a delta-amp rule compiles to.  A slot's magnitude is a
# fraction of the pool it prices, never a multiplier: the multiplier is the
# chain's, and folding fractions is what keeps two holders additive.  The two
# window bounds appear only for a rule whose activation declares them.
AMP_FRACTION_FIELD = "amp_fraction"
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
    if isinstance(magnitude, Fixed):
        return resolve(magnitude.value, ctx.level)
    if isinstance(magnitude, RampPerSecond):
        return _ramp_per_second(magnitude, ctx)
    if isinstance(magnitude, TargetBonusHealthScaled):
        return _target_bonus_health_scaled(magnitude, ctx)
    if isinstance(magnitude, RampPerStack):
        return _ramp_per_stack(magnitude, ctx)
    if isinstance(magnitude, MeleeRangedSplit):
        return _melee_ranged_split(magnitude, ctx)
    raise DeltaAmpInterpretationError(
        f"{type(magnitude).__name__} has no delta-amp arithmetic yet; the "
        "slice that declares a rule with it owns the branch"
    )


def _melee_ranged_split(magnitude: MeleeRangedSplit, ctx: BuildContext) -> float:
    """Whichever of the two sourced rates the holder's range class earns.

    One branch, no default: the context carries the class as a required
    field, so there is no path on which a holder silently takes the ranged
    rate because nobody said which they were.
    """
    reference = magnitude.melee if ctx.holder_is_melee else magnitude.ranged
    return resolve(reference, ctx.level)


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
        """Every number this rule contributes, resolved against the registries.

        The fraction always; the window bounds when the activation declares
        an absolute one.  This is the single path from a declaration to a
        number the engine uses — a caller that resolved a `ValueRef` itself
        would be a second reader of the same declaration.
        """
        payload = rule.payload
        if not isinstance(payload, DeltaAmpRule):
            raise DeltaAmpInterpretationError(
                f"{rule.mechanic_id} is not a delta-amp rule"
            )

        def field(name: str, value: float) -> KernelField:
            return KernelField(
                name=name,
                value=value,
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            )

        fields = [field(AMP_FRACTION_FIELD, magnitude_fraction(payload.magnitude, ctx))]
        if isinstance(payload.activation, AbsoluteWindow):
            fields.append(
                field(WINDOW_START_FIELD, resolve(payload.activation.start, ctx.level))
            )
            fields.append(
                field(WINDOW_END_FIELD, resolve(payload.activation.end, ctx.level))
            )
        if isinstance(payload.activation, LivePredicate):
            # The *threshold* is a sourced number and compiles here; the
            # pool it is compared against does not exist yet and must not be
            # guessed at build time.  That asymmetry is what
            # ``requires_live_pool`` names, and it is why the comparison
            # lives in ``live_predicate_holds`` and not in a field.
            fields.append(
                field(
                    LIVE_THRESHOLD_FIELD,
                    resolve(payload.activation.threshold, ctx.level),
                )
            )
        if isinstance(payload.activation, TriggerWindow):
            fields.append(
                field(
                    WINDOW_DURATION_FIELD,
                    resolve(payload.activation.duration, ctx.level),
                )
            )
        return tuple(fields)


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
    fields: tuple[tuple[KernelField, ...], ...]

    @property
    def fractions(self) -> tuple[float, ...]:
        """Each holder's sourced fraction, in build order."""
        return tuple(
            float(self.value(AMP_FRACTION_FIELD, index))
            for index in range(len(self.rules))
        )

    def value(self, name: str, index: int = 0) -> float:
        """One compiled field of one holder's rule, or a stop.

        A missing field means the rule's activation or magnitude does not
        declare what the caller is asking for — asking a window's end of a
        rule with no window — and that is a programming error, never a zero.
        """
        for field in self.fields[index]:
            if field.name == name:
                return float(field.value)
        raise DeltaAmpInterpretationError(
            f"{self.rules[index].mechanic_id} compiles no {name!r} field; the "
            "engine asked its declaration a question it does not answer"
        )

    def window(self, index: int = 0) -> tuple[float, float]:
        """The ``[start, end)`` an absolute-window holder declares."""
        return self.value(WINDOW_START_FIELD, index), self.value(
            WINDOW_END_FIELD, index
        )

    def prices_damage_type(self, damage_type: str, index: int = 0) -> bool:
        """Whether the holder's declared typing admits this damage class.

        ``DamageClass``' string values are the engine's own spellings, so the
        ledger's ``damage_type`` and the declaration's ``damage_classes`` are
        one vocabulary rather than two that have to be kept in step.
        """
        typing = self.rules[index].payload.typing
        return damage_type in {cls.value for cls in typing.damage_classes}

    def applies_after(
        self, event_time: float, trigger_time: float, index: int = 0
    ) -> bool:
        """Whether an event is inside an after-trigger activation.

        The boundary is the declaration's ``strict`` flag, not the engine's
        comparison operator: whether the event that armed a buff is itself
        amplified is a modelling ruling, and it belongs where a reader can
        find it.
        """
        activation = self.rules[index].payload.activation
        if not isinstance(activation, AfterTrigger):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no after-trigger "
                "activation, so it has no answer for an event's position "
                "relative to one"
            )
        if activation.strict:
            return event_time > trigger_time
        return event_time >= trigger_time

    def _trigger_activation(self, index: int) -> TriggerWindow:
        """The trigger-window activation this holder declares, or a stop."""
        activation = self.rules[index].payload.activation
        if not isinstance(activation, TriggerWindow):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no trigger window, so "
                "it has no answer for when a trigger opens one"
            )
        return activation

    def trigger_windows(
        self, trigger_times: Sequence[float], index: int = 0
    ) -> tuple[tuple[float, float], ...]:
        """The armed windows *trigger_times* open, merged as the rule declares.

        ``EXTEND`` is the Wiki reading the engine already implements — "
        subsequent immobilizes against a target extend the duration of the
        effect" — and it is now the declaration's word rather than the shape
        of a loop.  ``REFRESH`` and ``INDEPENDENT`` deliberately have no
        arithmetic: no rule declares them, and writing a branch nothing
        reaches is the orphan D-51 forbids.
        """
        activation = self._trigger_activation(index)
        if activation.merge is not WindowMerge.EXTEND:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares the "
                f"{activation.merge.value} window merge and no rule this "
                "interpreter serves does; the slice that declares one owns "
                "the branch"
            )
        duration = self.value(WINDOW_DURATION_FIELD, index)
        windows: list[list[float]] = []
        for time in sorted(trigger_times):
            if windows and time <= windows[-1][1]:
                windows[-1][1] = max(windows[-1][1], time + duration)
            else:
                windows.append([time, time + duration])
        return tuple((start, end) for start, end in windows)

    def window_holds(
        self,
        windows: Sequence[tuple[float, float]],
        time: float,
        index: int = 0,
    ) -> bool:
        """Whether an event at *time* is inside one of *windows* (D-13).

        ``OPEN_CLOSED`` is ``start < t <= end``: the trigger itself and
        same-timestamp packets are outside, and an event exactly on the
        expiry is inside.  That boundary used to be a comparison operator two
        engines had to agree on by inspection; it is now the one thing the
        declaration says and this method reads.  It is deliberately
        timestamp-only coarseness — a same-tick packet ordered after the
        trigger in the ledger is still excluded.
        """
        boundary = self._trigger_activation(index).boundary
        if boundary is not WindowBoundary.OPEN_CLOSED:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares the "
                f"{boundary.value} expiry boundary and no rule this "
                "interpreter serves does; the slice that declares one owns "
                "the branch"
            )
        return any(start < time <= end for start, end in windows)

    def exclusion(self, index: int = 0) -> Isolation:
        """What this holder's exclusion rule excludes, or a stop.

        The engine subtracts a pool from the total it amps, and *which* pool
        is a modelling ruling: Hypershot drops one event, Expose Weakness
        drops the whole chain that armed it.  Reading it off the declaration
        is what keeps that ruling somewhere a reader can find, instead of in
        the shape of whichever sum the engine happens to build.
        """
        activation = self.rules[index].payload.activation
        if not isinstance(activation, ExcludeTrigger):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no exclusion, so it "
                "has no answer for what an amp leaves out"
            )
        return activation.isolation

    def live_predicate_holds(
        self, probe: Probe, value: float, scale: float, index: int = 0
    ) -> bool:
        """Whether a live pool satisfies the rule's declared predicate.

        Shadowflame's Cinderbloom is the one amp whose pool cannot be
        precomputed: it reads the target's health at the instant of the hit,
        under fire from a whole roster.  So the *threshold* is compiled and
        the *reading* is passed in here, event by event.

        ``value`` and ``scale`` are two arguments rather than one ratio on
        purpose: the engine compares ``value < scale * threshold`` and
        ``value / scale < threshold`` is a different float.  ``probe`` is the
        pool the caller believes it is offering, checked against the one the
        rule declares — an engine handing the holder's health to a rule that
        reads the target's would otherwise be a silent wrong answer.
        """
        activation = self.rules[index].payload.activation
        if not isinstance(activation, LivePredicate):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no live predicate, "
                "so it has no answer for a pool reading"
            )
        if activation.probe is not probe:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} reads {activation.probe.value} "
                f"and the engine offered {probe.value}"
            )
        if activation.cmp is not Comparison.LT:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares the "
                f"{activation.cmp.value} comparison and no rule this "
                "interpreter serves does; the slice that declares one owns "
                "the branch"
            )
        return value < scale * self.value(LIVE_THRESHOLD_FIELD, index)

    def bonus_damage_type(self, source_type: str, index: int = 0) -> str:
        """What this amp's own bonus lands as, given the event it amplified."""
        typing = self.rules[index].payload.bonus_typing
        if typing is BonusTyping.SAME_AS_SOURCE:
            return source_type
        return typing.value

    def uniform_bonus_damage_type(self, index: int = 0) -> str:
        """The single type this amp's bonus always lands as, or a stop.

        An aggregate breakdown row needs one type for a sum of bonuses.  A
        rule whose bonus follows whatever it amplified has no single answer,
        and a caller that needs one is asking the wrong rule — so this raises
        rather than picking a plausible spelling.
        """
        typing = self.rules[index].payload.bonus_typing
        if typing is BonusTyping.SAME_AS_SOURCE:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares a bonus that follows "
                "its source, so it has no single aggregate damage type"
            )
        return typing.value

    @property
    def bonus_fraction(self) -> float:
        """The holders' summed fraction — what a bonus is priced from.

        Deliberately not ``multiplier - 1.0``: that round trip is not the
        identity in floating point (``1.0 + 0.07 - 1.0`` is not ``0.07``),
        and an amp priced from it would move every Command build's number by
        the last bits for no reason anybody could name.
        """
        return sum(self.fractions)

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
    holder_is_melee: bool,
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
    compiled = tuple(
        PAIR_INTERPRETER.compile(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
        )
        for rule in rules
    )
    return AmpSlot(slot=slot, rules=rules, fields=compiled)


__all__ = [
    "AMP_FRACTION_FIELD",
    "LIVE_THRESHOLD_FIELD",
    "WINDOW_DURATION_FIELD",
    "WINDOW_END_FIELD",
    "WINDOW_START_FIELD",
    "AmpSlot",
    "DeltaAmpInterpretationError",
    "DeltaAmpPairInterpreter",
    "PAIR_INTERPRETER",
    "magnitude_fraction",
    "resolve_slot",
    "slot_rules",
]
