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

Nothing here is a compiled-kernel lane.  The umbrella records H5 as SCOPED —
the kernel *is* to be taught timed, typed damage modifiers — but that lands
as its own stage after Phase 4's S7, and scoping it adds that stage rather
than relaxing this one: until its flip, every amp rule carries
``ReceiptOnly`` and the compiled lane is a named refusal.  The receipt-walk
half of the family arrives with the amps the coupled walk actually owns.

Two registry schemas amplify each part they price rather than the running
total, so they are not in the chain at all: :class:`PartAmp` is their
resolved form, and the engine asks for one by the attack class it is about
to price rather than by an item's name.

Everything the engine takes from a declaration comes through
:func:`amp_fields` — the fraction, the window bounds — and everything it
*asks* of one comes through :class:`AmpSlot` or :class:`PartAmp`.  A question a rule does not answer raises; it never
resolves to a zero.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..ability_spec import AttackClass
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
    PartAmpRule,
    Probe,
    RampModel,
    RampPerSecond,
    RampPerStack,
    RuleFamily,
    StatScaled,
    TargetBonusHealthScaled,
    TriggerWindow,
    WindowBoundary,
    WindowMerge,
    chain_rank,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import resolve_damage_effects
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
    if isinstance(magnitude, StatScaled):
        raise DeltaAmpInterpretationError(
            f"{ctx.owner} scales with the holder's {magnitude.stat.value}, "
            "which is not a build fact this context carries; its base and "
            f"rate compile to the {AMP_BASE_FRACTION_FIELD!r} and "
            f"{AMP_PER_HUNDRED_STAT_FIELD!r} fields and PartAmp.fraction "
            "takes the reading"
        )
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


def _magnitude_fields(
    magnitude: Magnitude,
    ctx: BuildContext,
    field: "Callable[[str, float], KernelField]",
) -> tuple[KernelField, ...]:
    """The compiled numbers a magnitude contributes — one field, or two.

    Every shape but :class:`StatScaled` resolves to a single fraction here.
    A stat-scaled one cannot: half of it is a reading of the holder's stat
    block, which this context deliberately does not carry, so its two sourced
    halves compile separately and :meth:`PartAmp.fraction` folds them with
    the reading.  Splitting the field rather than defaulting the stat is what
    keeps "the holder had no bonus mana" and "nobody asked for the stat"
    different answers.
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
    own reading because the holder's static amps used to reach it already
    folded into the pair engine's rows, and a walk that prices a declaration
    itself has nowhere to take them from (:func:`resolve_static_holder_amps`,
    ``survival.pricing.DeclaredPacket``).
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

        ``REFRESH`` is what this loop computes and now what the declaration
        calls it: a trigger landing inside a live window moves that window's
        end to its own time plus the duration.  The ``max`` is the identity
        under a constant duration — ``time`` is not before the trigger that
        opened the window, so ``time + duration`` is never the earlier of the
        two — and it is kept because it is the spelling
        ``survival.transitions._refresh_live_modifier`` uses for the same
        merge, so the two engines' refresh is one shape rather than two.

        ``EXTEND`` is the additive reading — a second immobilize adding its
        own duration to whatever is left — and ``INDEPENDENT`` a second
        window beside the first.  Both deliberately have no arithmetic: no
        rule declares them, and writing a branch nothing reaches is the
        orphan D-51 forbids.  ``EXTEND`` is additionally the reading the
        League Wiki's wording admits, kept unreached against the day a source
        settles it (``item_behavior_catalog.ACKNOWLEDGED_READING_DIVERGENCES``).
        """
        activation = self._trigger_activation(index)
        if activation.merge is not WindowMerge.REFRESH:
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
        trigger in the ledger is still excluded — and the coarseness is
        *kept* rather than merely inherited, on measured grounds.  Consulting
        the ledger's secondary key instead would read an ordering nothing
        authored: champion ability packets never carry ``timeline_order`` (the
        engine's own device for a same-instant claim, ``damage.py``'s ``+0.5``
        and ``-1.0``), so their key falls back to a construction counter that
        follows the rotation planner's slot list — reorder that list and the
        same simultaneous packets change sides.  The coupled walk cannot make
        the statement at all: its order is
        ``(time, ordering_slot(rank), …)`` with ``TransitionRank.DAMAGE`` at 3
        and ``DEBUFF_ARM`` at 6, so every packet at one timestamp resolves
        before any debuff arms there.  Command is ``Subject.ANY_ATTACKER`` —
        one rule, both engines — so amping the tie here alone would open a
        divergence at the one instant the two currently agree on.  The defect
        the measurement exposes is upstream, in a cast timeline that puts
        three casts on one instant; it is not this window test's to absorb.
        ``tests/test_phase0_sentinels.py`` prices what the tie is worth.
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


@dataclass(frozen=True, slots=True)
class PartAmp:
    """A per-part amplifier, resolved for one build.

    The chain's :class:`AmpSlot` answers "what does the running total get
    multiplied by at position *n*".  This answers a different question — "what
    does each part I am allowed to price get multiplied by" — and it is a
    separate type because the two must never be summed into one another's
    fold.  Everything else is deliberately the same shape: rules and their
    compiled fields in build order, and the engine's own ``1.0 + sum`` fold.
    """

    attack_class: AttackClass
    rules: tuple[BehaviorRule, ...]
    fields: tuple[tuple[KernelField, ...], ...]

    def _value(self, name: str, index: int) -> float:
        """One compiled field of one holder's rule, or a stop."""
        for field in self.fields[index]:
            if field.name == name:
                return float(field.value)
        raise DeltaAmpInterpretationError(
            f"{self.rules[index].mechanic_id} compiles no {name!r} field; the "
            "engine asked its declaration a question it does not answer"
        )

    def _terms(
        self, index: int, holder_stats: "Mapping[str, float]"
    ) -> tuple[float, ...]:
        """One holder's fraction, as the shares its magnitude is made of.

        Shares rather than one number because addition is not associative:
        the registry compiled a stat-scaled amp as ``1 + base + rate x`` and
        folding its two halves before the ``1`` lands on a different float.
        Every other magnitude has exactly one share, for which the two
        spellings coincide.

        A stat-scaled magnitude is read here rather than at build time, and
        the reading is *required*: a holder stat the caller did not supply is
        a caller that does not know what it is holding, which is a
        programming error and never a zero-mana Actualizer.
        """
        magnitude = self.rules[index].payload.magnitude
        if not isinstance(magnitude, StatScaled):
            return (self._value(AMP_FRACTION_FIELD, index),)
        if magnitude.stat.value not in holder_stats:
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} scales with the holder's "
                f"{magnitude.stat.value}, which the caller did not supply; a "
                "missing stat is an unanswered question, not a zero"
            )
        reading = float(holder_stats[magnitude.stat.value])
        return (
            self._value(AMP_BASE_FRACTION_FIELD, index),
            self._value(AMP_PER_HUNDRED_STAT_FIELD, index) * (reading / 100.0),
        )

    def fractions(self, holder_stats: "Mapping[str, float]") -> tuple[float, ...]:
        """Each holder's sourced fraction, in build order."""
        return tuple(
            sum(self._terms(index, holder_stats)) for index in range(len(self.rules))
        )

    def multiplier(self, holder_stats: "Mapping[str, float]") -> float:
        """What the engine multiplies each priced part by.

        One running sum from ``1.0`` over every holder's shares, in build
        order — the association the registry's own compiled multipliers used,
        which is what lets this migration claim no number moved rather than
        no number moved much.  Holders are additive with each other for the
        same reason the chain's occupants are; no registry entry puts two
        items in one attack class today, so the fold is stated rather than
        inferred from the one occupant every build has.
        """
        total = 1.0
        for index in range(len(self.rules)):
            for term in self._terms(index, holder_stats):
                total += term
        return total

    @property
    def owner(self) -> str:
        """The holder the amp's breakdown row is filed under."""
        return self.rules[0].owner


def part_amp_rules(
    owners: Sequence[str], attack_class: AttackClass
) -> tuple[BehaviorRule, ...]:
    """Every per-part amp *owners* bring that prices *attack_class*.

    The selector is the damage the engine is about to price, not an item
    name: "what amplifies a basic attack" is a question the declaration
    answers through ``typing.attack_classes``, and asking it that way is what
    takes the two item names out of the engine.
    """
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DELTA_AMP
        and isinstance(rule.payload, PartAmpRule)
        and attack_class in rule.payload.typing.attack_classes
    )


def resolve_part_amp(
    owners: Sequence[str],
    attack_class: AttackClass,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
    lane: EngineLane = EngineLane.PAIR_ENGINE,
) -> PartAmp | None:
    """The per-part amp for one attack class, or ``None`` if nobody has it.

    ``None`` is an answer and not a zero, exactly as it is for a chain slot:
    no holder declares a per-part amp for this damage, so no rule ran and
    there is no multiplier to report.

    ``lane`` names the engine asking, and is the only thing it changes: the
    values are identical and only the lane the fields carry differs, so the
    coupled walk's reading of an amp declaration is the pair engine's reading
    — which is the point, since the walk has to deliver the holder's amps
    itself without becoming a second place the amp is computed.
    """
    rules = part_amp_rules(owners, attack_class)
    if not rules:
        return None
    compiled = tuple(
        amp_fields(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
            lane,
        )
        for rule in rules
    )
    return PartAmp(attack_class=attack_class, rules=rules, fields=compiled)


def _armed_part_multiplier(
    owners: Sequence[str],
    attack_class: AttackClass,
    *,
    armed: bool,
    holder_stats: Mapping[str, float],
    build: Mapping[str, Any],
) -> tuple[float, str]:
    """The walk's reading of one part amp: its multiplier and its holder.

    ``armed`` is the caller's answer to whether the amp's activation is up at
    all — an item active nobody triggered amplifies nothing — and an unarmed
    build, or one holding no such amp, gets ``(1.0, "")``: a multiplier that
    changes no number, and no holder to attribute it to.  That pairing is
    deliberate, so an amp can never be reported against an item whose window
    did not run, which is the same convention ``damage._part_amp`` states for
    the pair engine.  Both reach the number through :func:`resolve_part_amp`,
    each naming its own lane — one compiler, two engines asking.
    """
    if not armed:
        return 1.0, ""
    amp = resolve_part_amp(owners, attack_class, lane=EngineLane.RECEIPT_WALK, **build)
    if amp is None:
        return 1.0, ""
    return amp.multiplier(holder_stats), amp.owner


@dataclass(frozen=True, slots=True)
class StaticHolderAmps:
    """The holder's own static, pair-local amplifiers, resolved for one build.

    Three numbers, and the umbrella's Amendment M measured that they come
    from **two** declaration shapes rather than one, which is why this type
    exists instead of a bare float per caller.  ``ability`` and ``basic`` are
    :class:`PartAmpRule` declarations of this family, selected by the attack
    class they price.  ``magic`` is not: it is Abyssal Mask's Unmake, family
    ``ALLY_PACKET``, applied by ``damage._mitigate`` on the defender's side
    and occupying no chain slot — which the catalog says in its own words
    through ``DELTA_AMP_UNMIGRATED_TAGS``.  A reader who went looking for the
    magic amp among the ``delta_amp`` declarations would find nothing and
    drop the term, and dropping it is the exact deletion Amendment M,
    Ruling 1 exists to forbid; so both readings meet here, once.

    "Static" and "pair-local" are the scope: these are the amplifiers the
    holder's own build brings to its own damage, resolved at build time and
    unchanging through the fight.  The timed, roster-wide modifiers a
    ``damage_modifier`` packet carries are a different thing, arrive through
    ``ActionKind.DAMAGE_MODIFIER``, and are not composed here.
    """

    magic: float = 1.0
    ability: float = 1.0
    basic: float = 1.0
    ability_owner: str = ""
    basic_owner: str = ""

    def factor_for(self, damage_type: str, attack_class: AttackClass) -> float:
        """What one packet of this class and this delivery is multiplied by.

        The pair engine's own order, read off the two sites that apply these
        amps: ``damage._mitigate`` multiplies magic damage by the magic amp
        whatever delivered it, and the part amp multiplies on top of that —
        by the ability amp for an ability-delivered part
        (``damage._add_item_proc_damage``) and by the basic amp for a swing
        (``damage._mitigate_basic_attack_swing``).  ``AttackClass.OTHER``
        takes neither part amp, because neither declaration's typing claims
        it.
        """
        factor = self.magic if damage_type == "magic" else 1.0
        if attack_class is AttackClass.ABILITY:
            factor *= self.ability
        elif attack_class is AttackClass.BASIC_ATTACK:
            factor *= self.basic
        return factor


def resolve_static_holder_amps(
    items: Sequence[Mapping[str, Any]],
    *,
    holder_stats: Mapping[str, float],
    ability_amp_armed: bool,
    **build: Any,
) -> StaticHolderAmps:
    """One holder's three static amps, read from the declarations that produce them.

    The reading the **coupled walk** makes so it can deliver the holder's amps
    itself rather than receiving them pre-multiplied inside another engine's
    rows — Amendment M, Ruling 1's retiring act for this family, in one
    function.

    ``build`` is :func:`resolve_part_amp`'s own build context — level, fight
    duration, target bonus health, holder range — forwarded rather than
    re-listed, so a fact the compiler starts needing arrives here without an
    edit and a fact it stops needing cannot linger.

    ``ability_amp_armed`` is the caller's answer to whether the ability amp's
    window is up, because that amp rides an item active and a build that never
    triggered it amplifies nothing — the same question
    ``damage._resolve_combat_state`` answers from ``actualizer_active_until``.
    It is a required argument rather than a defaulted one: guessing it would
    arm an amp nobody triggered, which is a number invented rather than
    delivered.
    """
    owners = [str(item.get("name", "")) for item in items]
    ability, ability_owner = _armed_part_multiplier(
        owners,
        AttackClass.ABILITY,
        armed=ability_amp_armed,
        holder_stats=holder_stats,
        build=build,
    )
    basic, basic_owner = _armed_part_multiplier(
        owners,
        AttackClass.BASIC_ATTACK,
        armed=True,
        holder_stats=holder_stats,
        build=build,
    )
    return StaticHolderAmps(
        magic=resolve_damage_effects(items).magic_amp,
        ability=ability,
        basic=basic,
        ability_owner=ability_owner,
        basic_owner=basic_owner,
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
        amp_fields(
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
        for rule in rules
    )
    return AmpSlot(slot=slot, rules=rules, fields=compiled)


__all__ = [
    "AMP_BASE_FRACTION_FIELD",
    "AMP_FRACTION_FIELD",
    "AMP_PER_HUNDRED_STAT_FIELD",
    "LIVE_THRESHOLD_FIELD",
    "WINDOW_DURATION_FIELD",
    "WINDOW_END_FIELD",
    "WINDOW_START_FIELD",
    "AmpSlot",
    "DeltaAmpInterpretationError",
    "PartAmp",
    "StaticHolderAmps",
    "amp_fields",
    "magnitude_fraction",
    "part_amp_rules",
    "resolve_part_amp",
    "resolve_slot",
    "resolve_static_holder_amps",
    "slot_rules",
]
