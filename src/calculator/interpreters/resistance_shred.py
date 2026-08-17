"""Stacking resistance reduction, interpreted: a declared ramp becomes a cut.

Reduction is not penetration.  Penetration is the attacker's own stat and
cannot take a resistance below zero; a shred moves the *target's* resistance
before penetration is applied and may take it negative.  Two items do it —
one to armour, one to magic resistance — and until this module their two
models lived as two unrelated typed records in the number registry, each with
its arithmetic attached to it and neither able to say what applied a stack.

Here the shape is a :class:`~..item_behavior.ResistanceShredRule`, the numbers
are live references, and the two summation models are one guarded branch
each:

* ``CESARO_APPROX`` — Black Cleaver's Carve, averaged in closed form over the
  hit stream.  ``docs/math-foundations.md`` §2.3 calls re-tuning it a balance
  change, so it is reproduced constant for constant.
* ``EXACT`` — Bloodletter's Curse's Vile Decay, whose stacks the rotation
  counts one magic ability at a time.

Each model answers one question and refuses the other: an averaged ramp has
no answer for "what is the cut at three stacks", and an exactly-counted one
has no closed form to average.  Refusing is the point — a model that answered
both would be picking a plausible number for a question its declaration never
made.

Two lanes, because the ramp is read in two places.  The pair engine resolves
the cut into its own combat state, and — since this family retired off the
pair engine on 2026-08-16 — the receipt walk reads the same declaration for
the cross-participant packet it stages.  That second lane hands the walk no
price, and for a reason of its own rather than ``damage_routing``'s: a shred
is not damage, it moves the *target's* resistance before penetration is
applied, so every number it changes belongs to some other family's packet.
What retires the row is the walk reading this declaration instead of the
ally-packet declaration's own second copy of the same two numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..ability_spec import DamageClass
from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    RampModel,
    Resistance,
    ResistanceShredRule,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve

# The field names a shred rule compiles to.  ``per_stack`` is a fraction of
# the target's resistance, never a percentage: the percent conversion is the
# engine's own unit and lives at the one call site that needs it.
SHRED_PER_STACK_FIELD = "shred_per_stack"
SHRED_MAX_STACKS_FIELD = "shred_max_stacks"
SHRED_LEADING_STACKS_FIELD = "shred_leading_stacks"

# The engine's spelling for a number that is part physical and part magic.
# It is not a ``DamageClass`` member — a mixed *ability* is two typed parts,
# never a mixed part — but the rotation carries it as one ability-level label,
# so a shred asking "does this ability apply a stack" has to be told which
# classes that label covers.
MIXED_DAMAGE_TYPE = "mixed"

# The closed-form mean of the capped ramp the Cesàro model uses once the hit
# count reaches the stack cap.  A property of the *model*, not of any item —
# which is why it lives in the one branch that implements the model and not
# in a registry — and it is reproduced here exactly as the pair engine has
# always computed it (docs/math-foundations.md §2.3).
_CESARO_SATURATED_STACK_FRACTION = 0.8


class ResistanceShredInterpretationError(ValueError):
    """A shred was asked a question its declared model does not answer."""


def event_damage_classes(damage_type: str) -> frozenset[DamageClass]:
    """Which damage classes one engine damage-type spelling covers.

    Every spelling but ``mixed`` is a ``DamageClass`` value, so this is the
    enum's own projection plus the one label that is a *pair* of classes.  It
    exists so a declaration can say "magic damage applies a stack" and have
    that mean the same thing as the engine's own ``in ("magic", "mixed")``
    test, without either side re-spelling the other's vocabulary.
    """
    if damage_type == MIXED_DAMAGE_TYPE:
        return frozenset({DamageClass.MAGIC, DamageClass.PHYSICAL})
    return frozenset(
        damage_class
        for damage_class in DamageClass
        if damage_class.value == damage_type
    )


def _ramp_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One shred's compiled ramp numbers for *lane*.

    The three sourced numbers a shred's ramp resolves to.  The *model* is not
    a field: it is a policy the slot branches on, and compiling it to a value
    would let a caller read a summation rule off a number.

    The lane is the only thing that varies between the two interpreters below.
    Sharing the body rather than spelling it twice is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    instead of a claim two functions could drift out of.
    """
    payload = rule.payload
    if not isinstance(payload, ResistanceShredRule):
        raise ResistanceShredInterpretationError(
            f"{rule.mechanic_id} is not a resistance-shred rule"
        )

    def field(name: str, value: float) -> KernelField:
        return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)

    ramp = payload.ramp
    return (
        field(SHRED_PER_STACK_FIELD, resolve(ramp.per_stack, ctx.level)),
        field(SHRED_MAX_STACKS_FIELD, resolve(ramp.max_stacks, ctx.level)),
        field(SHRED_LEADING_STACKS_FIELD, resolve(ramp.leading_stacks, ctx.level)),
    )


class ResistanceShredPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``resistance_shred`` family.

    Its number is **not** a preview.  The pair engine resolves this family's
    cut into its own combat state (``damage._resolve_combat_state``), which is
    the pair-local half of a ``SPLIT`` the campaign's authority table leaves
    standing under H1, and the walk skips the holder rather than re-pricing
    it.  The triage measured this family authoring no priced pair row at all,
    so there is nothing here for a ``pair_preview_of`` stamp to describe.
    """

    FAMILY = RuleFamily.RESISTANCE_SHRED
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This shred's ramp, resolved for the one-attacker engine."""
        return _ramp_fields(rule, ctx, EngineLane.PAIR_ENGINE)


class ResistanceShredWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The receipt walk's answer for the ``resistance_shred`` family.

    The half that retires ``resistance_shred/receipt_walk`` (umbrella
    Amendment F's act, in the lane Amendment K rules, with the shape Amendment
    L, Ruling 1 requires and the substitution Amendment P makes to it for a
    family whose delivery is not a price).

    **It hands the walk no price**, and unlike ``damage_routing`` — the other
    such family — that is not because the effect is a rider.  A shred is not
    damage at all: it moves the *target's* resistance before penetration is
    applied, so every number it changes belongs to some other family's packet.
    ``survival.pricing`` gains no term here and no ``DeclaredPacket`` is
    touched.

    What it hands the walk is the **ramp**, and what consumes it is the
    cross-participant half the walk already stages: ``black_cleaver.carve``
    and ``bloodletters_curse.vile_decay`` emit this family's cut as a
    ``damage_modifier`` packet through
    ``item_support_effects.derive_item_support_effects``, which is the named
    walk-side delivery term umbrella Amendment O, Ruling 2 requires of a
    class-(c) row.  Before this interpreter that emitter read the ramp off the
    *ally-packet* declaration's own copy of the two numbers — a second
    declaration of one ramp, which is how a score and a receipt come to
    disagree about it, and exactly the shape Serpent's Fang's venom had before
    ``damage_routing`` retired.  Now both sides read this one.

    The stack **ledger** stays where it is.  Which authored events apply a
    stack, to which target, and in what order is a roster fact the emitter
    already walks; moving it in here would be a second producer of the count
    (D-60).  What this supplies is the two sourced numbers that count is
    multiplied and capped by.
    """

    FAMILY = RuleFamily.RESISTANCE_SHRED
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This shred's ramp, resolved for the coupled roster walk."""
        return _ramp_fields(rule, ctx, EngineLane.RECEIPT_WALK)


PAIR_INTERPRETER = ResistanceShredPairInterpreter()
WALK_INTERPRETER = ResistanceShredWalkInterpreter()


@dataclass(frozen=True, slots=True)
class ShredSlot:
    """One resistance's declared shred, resolved for one build.

    A slot holds exactly one rule.  Two items stacking their reductions on one
    resistance is a fold nobody has declared — the registries hold one shred
    per resistance and the engine's own accumulator kept one — so a second
    holder is a stop rather than a silently-chosen winner.
    """

    resistance: Resistance
    rule: BehaviorRule
    fields: tuple[KernelField, ...]

    @property
    def _payload(self) -> ResistanceShredRule:
        """The rule's payload, narrowed once for the accessors below."""
        payload = self.rule.payload
        if not isinstance(payload, ResistanceShredRule):
            raise ResistanceShredInterpretationError(
                f"{self.rule.mechanic_id} is not a resistance-shred rule"
            )
        return payload

    def value(self, name: str) -> float:
        """One compiled field of the slot's rule, or a stop."""
        for field in self.fields:
            if field.name == name:
                return float(field.value)
        raise ResistanceShredInterpretationError(
            f"{self.rule.mechanic_id} compiles no {name!r} field; the engine "
            "asked its declaration a question it does not answer"
        )

    @property
    def per_stack(self) -> float:
        """The sourced fraction one stack cuts."""
        return self.value(SHRED_PER_STACK_FIELD)

    @property
    def max_stacks(self) -> int:
        """The declared stack cap."""
        return int(self.value(SHRED_MAX_STACKS_FIELD))

    def accrues_on(self, damage_type: str) -> bool:
        """Whether damage of this type applies a stack of this shred.

        The declaration names the damage classes that apply one; a spelling
        the engine carries as a pair of classes applies a stack when *either*
        of them is declared, which is what makes the mixed label behave the
        way the rotation's own ``in ("magic", "mixed")`` test always did.
        """
        declared = self._payload.typing.damage_classes
        return bool(declared & event_damage_classes(damage_type))

    def average_reduction(self, applying_events: int) -> float:
        """The averaged cut over a counted stream — the Cesàro model only.

        The stream is the events the caller counted; the declaration's
        ``leading_stacks`` is what the model believes preceded it.  Once the
        combined count reaches the cap the ramp has been saturated for most of
        the fight and the model uses its closed-form mean; below the cap the
        stacks have been climbing linearly and the mean is half the count.
        """
        ramp = self._payload.ramp
        if ramp.model is not RampModel.CESARO_APPROX:
            raise ResistanceShredInterpretationError(
                f"{self.rule.mechanic_id} declares the {ramp.model.value} "
                "summation, which counts its stacks exactly and has no averaged "
                "form; ask it for the cut at a stack count instead"
            )
        cap = self.max_stacks
        hits = applying_events + int(self.value(SHRED_LEADING_STACKS_FIELD))
        if hits >= cap:
            average_stacks = cap * _CESARO_SATURATED_STACK_FRACTION
        else:
            average_stacks = hits / 2.0
        return self.per_stack * average_stacks

    def reduction_percent(self, stacks: int) -> float:
        """The cut at an exactly-counted stack count, as a percentage.

        Percent rather than fraction because that is the unit the resistance
        arithmetic takes, and converting at the one boundary that needs it is
        what keeps every declaration in one unit.
        """
        ramp = self._payload.ramp
        if ramp.model is not RampModel.EXACT:
            raise ResistanceShredInterpretationError(
                f"{self.rule.mechanic_id} declares the {ramp.model.value} "
                "summation, which averages over a stream and has no per-stack "
                "reading; ask it for the average over a hit count instead"
            )
        return self.per_stack * stacks * 100.0

    @property
    def owner(self) -> str:
        """The holder the shred is filed under."""
        return self.rule.owner


def shred_rules(
    owners: Sequence[str], resistance: Resistance
) -> tuple[BehaviorRule, ...]:
    """Every declared shred *owners* bring to one resistance, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.RESISTANCE_SHRED
        and isinstance(rule.payload, ResistanceShredRule)
        and rule.payload.resistance is resistance
    )


def _resolve_slot(  # pylint: disable=too-many-arguments
    owners: Sequence[str],
    resistance: Resistance,
    interpreter: Any,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ShredSlot | None:
    """This build's shred of one resistance, compiled by *interpreter*.

    One body for both lanes, so "the walk reads the declaration the pair
    engine reads" is a property of the tree rather than of two functions
    agreeing.
    """
    rules = shred_rules(owners, resistance)
    if not rules:
        return None
    if len(rules) > 1:
        raise ResistanceShredInterpretationError(
            f"{[rule.owner for rule in rules]} all declare a {resistance.value} "
            "shred and no rule declares how two stacking reductions of one "
            "resistance combine; the slice that declares a second one owns the "
            "fold"
        )
    rule = rules[0]
    return ShredSlot(
        resistance=resistance,
        rule=rule,
        fields=interpreter.compile(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
        ),
    )


def resolve_slot(
    owners: Sequence[str],
    resistance: Resistance,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ShredSlot | None:
    """This build's shred of one resistance, on the pair-engine lane.

    ``None`` is an answer and not a zero: no holder cuts this resistance, so
    no rule ran and the target keeps its stated value.
    """
    return _resolve_slot(
        owners,
        resistance,
        PAIR_INTERPRETER,
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )


def walk_slot(  # pylint: disable=too-many-arguments
    owners: Sequence[str],
    resistance: Resistance,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ShredSlot | None:
    """This build's shred of one resistance, on the receipt-walk lane.

    What the walk's own cross-participant emitter reads since this family
    retired off the pair engine: the same declaration, compiled by the
    interpreter registered in the lane the family declares, so the packet the
    walk stages and the cut the pair engine resolves cannot be two different
    readings of one ramp.

    ``None`` carries the same meaning it carries on the pair lane — nobody
    declares a shred of this resistance — and the emitter treats a holder of
    the cross-participant half with no such declaration as a stop rather than
    as a packet with no numbers.
    """
    return _resolve_slot(
        owners,
        resistance,
        WALK_INTERPRETER,
        level=level,
        fight_duration_seconds=fight_duration_seconds,
        target_bonus_health=target_bonus_health,
        holder_is_melee=holder_is_melee,
    )


__all__ = [
    "MIXED_DAMAGE_TYPE",
    "SHRED_LEADING_STACKS_FIELD",
    "SHRED_MAX_STACKS_FIELD",
    "SHRED_PER_STACK_FIELD",
    "PAIR_INTERPRETER",
    "WALK_INTERPRETER",
    "ResistanceShredInterpretationError",
    "ResistanceShredPairInterpreter",
    "ResistanceShredWalkInterpreter",
    "ShredSlot",
    "event_damage_classes",
    "resolve_slot",
    "shred_rules",
    "walk_slot",
]
