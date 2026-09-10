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

Three registry schemas amplify each part they price rather than the running
total, so they are not in the chain at all: :class:`PartAmp` is the resolved
form of the two the engine asks for by the attack class it is about to price,
and :func:`declared_magic_amp` reads the third, which restricts the damage
class instead. Neither selector is asked by an item's name.

Everything the engine takes from a declaration comes through
:func:`amp_fields` — the fraction, the window bounds — and everything it
*asks* of one comes through :class:`AmpSlot` or :class:`PartAmp`.  A question
a rule does not answer raises; it never resolves to a zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    AfterTrigger,
    AmpChainSlot,
    BehaviorRule,
    BonusTyping,
    Comparison,
    DeltaAmpRule,
    EngineLane,
    ExcludeTrigger,
    FightFacts,
    Isolation,
    KernelField,
    LivePredicate,
    Probe,
    RuleFamily,
    TriggerWindow,
    WindowBoundary,
    WindowMerge,
    chain_rank,
)
from ..item_behavior_catalog import behavior_rules, build_context
from .amp_magnitude import (
    AMP_FRACTION_FIELD,
    LIVE_THRESHOLD_FIELD,
    WINDOW_DURATION_FIELD,
    WINDOW_END_FIELD,
    WINDOW_START_FIELD,
    DeltaAmpInterpretationError,
    _declared_field,
    amp_fields,
)


@dataclass(frozen=True, slots=True)
class AmpSlot:
    """One chain slot, resolved for one build.

    ``fractions`` runs parallel to ``rules``, one sourced fraction per holder in
    build order, because the slot's occupants are additive among themselves and a
    caller that reports per-source rows needs the parts, not only the sum.
    ``owner`` names the breakdown row, derived from the rule rather than passed in,
    which removes the item name from the engine's side of the call.

    The fold spelling is load-bearing, not stylistic.  ``1.0 + sum(f)``, a running
    ``+=`` per holder and ``math.fsum`` disagree in the last bits once a slot has
    two occupants, and ``1.0 + 0.07 - 1.0`` is not ``0.07``.  So :attr:`multiplier`
    is ``1.0 + sum(fractions)``, the engine's own spelling for the one slot that
    can hold several mechanics (``WHOLE_TOTAL``), and :attr:`bonus_fraction` is
    ``sum(fractions)`` rather than ``multiplier - 1.0``.
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
        """One compiled field of one holder's rule, or a stop."""
        return _declared_field(self.rules[index], self.fields[index], name)

    def window(self, index: int = 0) -> tuple[float, float]:
        """The ``[start, end)`` an absolute-window holder declares."""
        return self.value(WINDOW_START_FIELD, index), self.value(
            WINDOW_END_FIELD, index
        )

    def prices_damage_type(self, damage_type: str, index: int = 0) -> bool:
        """Whether the holder's declared typing admits this damage class."""
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

        ``REFRESH`` is what this loop computes and what the declaration calls it: a
        trigger landing inside a live window moves that window's end to its own time
        plus the duration.  The ``max`` is the identity under a constant duration,
        since ``time`` is never before the trigger that opened the window, and it is
        kept because ``survival.transitions._refresh_live_modifier`` spells the same
        merge that way, so the two engines' refresh is one shape rather than two.

        ``EXTEND`` is the additive reading, a second immobilize adding its own
        duration to whatever is left, and ``INDEPENDENT`` a second window beside the
        first.  Both deliberately have no arithmetic: no rule declares them, and a
        branch nothing reaches is an orphan.  ``EXTEND`` is additionally the reading
        the League Wiki's wording admits, kept unreached against the day a source
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
        """Whether an event at *time* is inside one of *windows*.

        ``OPEN_CLOSED`` is ``start < t <= end``: the trigger itself and
        same-timestamp packets are outside, and an event exactly on the expiry is
        inside.  The coarseness is timestamp-only and kept on measured grounds: a
        ledger's secondary key would read an ordering nothing authored, and the
        coupled walk resolves every packet at one timestamp before any debuff arms
        there, so amping the tie here alone would open a divergence.
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

        The engine subtracts a pool from the total it amps, and *which* pool is a
        modelling ruling: Hypershot drops one event, Expose Weakness drops the whole
        chain that armed it.  Reading it off the declaration keeps that ruling where
        a reader can find it.
        """
        activation = self.rules[index].payload.activation
        if not isinstance(activation, ExcludeTrigger):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no exclusion, so it "
                "has no answer for what an amp leaves out"
            )
        return activation.isolation

    def live_comparison(self, index: int = 0) -> Comparison:
        """Which side of its threshold this holder's live predicate arms on.

        What a caller needs when it has to *say* what the rule did, read off
        the declaration for the same reason :meth:`exclusion` is: a second
        spelling of the side is a second place it can be wrong.
        """
        activation = self.rules[index].payload.activation
        if not isinstance(activation, LivePredicate):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares no live predicate, "
                "so it has no side of a threshold to arm on"
            )
        return activation.cmp

    def live_predicate_holds(
        self, probe: Probe, value: float, scale: float, index: int = 0
    ) -> bool:
        """Whether a live pool satisfies the rule's declared predicate.

        Cinderbloom and the rune page's two target-health amplifiers are the
        amps whose pool cannot be precomputed: they read the target's health
        at the instant of the hit, under fire from a whole roster.  So the
        *threshold* is compiled and the *reading* is passed in here, event by
        event.

        ``value`` and ``scale`` are two arguments rather than one ratio on
        purpose: the engine compares ``value < scale * threshold`` and
        ``value / scale < threshold`` is a different float.  ``probe`` is the
        pool the caller believes it is offering, checked against the one the
        rule declares — an engine handing the holder's health to a rule that
        reads the target's would otherwise be a silent wrong answer.

        ``LT`` and ``GT`` are the two comparisons declared: Coup de Grace and
        Cinderbloom arm under a share of the target's health, Cut Down over
        one.  ``LE`` and ``GE`` deliberately have no arithmetic — no rule
        declares which side of the threshold itself is inside, and a branch
        nothing reaches is an orphan.
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
        if activation.cmp not in (Comparison.LT, Comparison.GT):
            raise DeltaAmpInterpretationError(
                f"{self.rules[index].mechanic_id} declares the "
                f"{activation.cmp.value} comparison and no rule this "
                "interpreter serves does; the slice that declares one owns "
                "the branch"
            )
        threshold = scale * self.value(LIVE_THRESHOLD_FIELD, index)
        if activation.cmp is Comparison.GT:
            return value > threshold
        return value < threshold

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
        """The holders' summed fraction, which is what a bonus is priced from."""
        return sum(self.fractions)

    @property
    def multiplier(self) -> float:
        """What the engine multiplies by: ``1.0`` plus the holders' sum."""
        return 1.0 + sum(self.fractions)

    @property
    def owner(self) -> str:
        """The holder the slot's breakdown row is filed under."""
        return self.rules[0].owner

    def sources(self) -> tuple[tuple[str, float], ...]:
        """Each holder with the fraction it contributes, in build order."""
        return tuple(
            (rule.owner, fraction)
            for rule, fraction in zip(self.rules, self.fractions, strict=False)
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
    facts: FightFacts,
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
            build_context(rule.owner, facts),
            EngineLane.PAIR_ENGINE,
        )
        for rule in rules
    )
    return AmpSlot(slot=slot, rules=rules, fields=compiled)


__all__ = ["AmpSlot", "resolve_slot", "slot_rules"]
