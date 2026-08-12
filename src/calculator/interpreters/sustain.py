"""Sustain: seven shapes that put health back, sharing no arithmetic.

A vampirism stat the build's stat fold sums, a flat heal one on-hit
application pays, a share of damage dealt paid straight back, a resource
drain that only becomes health when there is no resource left to fill, a
heal bought with mana spent, a regeneration window a qualifying hit opens,
and a multiplier on everything the subject *receives*.

They are one family because they answer one question — where does the health
come from — and because the alternative was what this migration replaced:
six unrelated `if "<item name>" in names` branches in four modules, each
reading the registry directly and none of them able to say what kind of
restoration it was.

Two lanes.  The pair engine and the roster path read the six holder-side
shapes through :func:`sustain_slot`; the defensive resolver builds the
received-healing multiplier, because it has to run *after* every shield it
multiplies and that position is arithmetic rather than presentation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DefenseField,
    DefenseMechanic,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    KernelField,
    ReceivedHealingRule,
    RuleFamily,
    SUSTAIN_PAYLOAD_REFERENCES,
    SUSTAIN_VALUE_PAYLOADS,
    SustainStat,
    SustainStatRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import ValueRefError, resolve, resolve_flat
from . import defense_state
from .defense_state import DefenseInterpretationError, DefenseSlot

# The one field the received-healing multiplier compiles to on its own lane.
RECEIVED_HEALING_MULTIPLIER_FIELD = "healing_received_multiplier"


class SustainInterpretationError(ValueError):
    """A sustain rule was asked something its payload does not answer."""


class SustainPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the six holder-side sustain shapes.

    Every one of them compiles to the same thing — its own declared
    references, resolved and named after the field they were declared under —
    because that is genuinely all these six have in common.  The *shape* is
    what tells a caller which fields exist, and asking for one a rule does
    not declare is a stop rather than a zero.
    """

    FAMILY = RuleFamily.SUSTAIN
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """Every sourced number one sustain declaration resolves to."""
        payload = rule.payload
        if not isinstance(payload, SUSTAIN_VALUE_PAYLOADS):
            raise SustainInterpretationError(
                f"{rule.mechanic_id} is not a holder-side sustain rule; the "
                "received-healing multiplier is built by the defensive "
                "resolver, not here"
            )
        return tuple(
            KernelField(
                name=name,
                value=resolve(getattr(payload, name), ctx.level),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            )
            for name in SUSTAIN_PAYLOAD_REFERENCES[type(payload)]
        )


class SustainResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The defensive resolver's answer for the received-healing multiplier."""

    FAMILY = RuleFamily.SUSTAIN
    LANES = frozenset({EngineLane.DEFENSE_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape the multiplier compiles to, at build time."""
        return defense_state.compiled_shape(rule, ctx.level)

    def resolve(self, rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
        """The multiplier, as the one field the declaration says it writes.

        Applying it is the ledger's job and deliberately not this
        interpreter's: the multiplier scales state three earlier mechanics
        wrote, so the fold belongs where the state lives.  What the
        declaration owns is the number and the field it lands in.
        """
        del subject
        slot = DefenseSlot(rule)
        if slot.mechanic is not DefenseMechanic.BOUNDLESS_VITALITY:
            raise DefenseInterpretationError(
                f"{rule.mechanic_id} declares sustain at the resolver and this "
                "interpreter has no branch for it; a multiplier with no "
                "arithmetic is a mechanic that would silently do nothing"
            )
        return DefenseOutcome(
            fields=(
                slot.grant(
                    DefenseField.HEALING_RECEIVED_MULTIPLIER,
                    slot.value("shield_received_multiplier"),
                ),
            ),
            notes=(),
        )


PAIR_INTERPRETER = SustainPairInterpreter()
RESOLVER_INTERPRETER = SustainResolverInterpreter()


def received_healing_multiplier(rule: BehaviorRule) -> float:
    """The sourced multiplier one received-healing declaration carries."""
    payload = rule.payload
    if not isinstance(payload, ReceivedHealingRule):
        raise SustainInterpretationError(
            f"{rule.mechanic_id} is not a received-healing rule"
        )
    return DefenseSlot(rule).value("shield_received_multiplier")


@dataclass(frozen=True, slots=True)
class SustainSlot:
    """One holder's sustain declaration, resolved for one build.

    The accessor engines hold instead of an item name.  ``value`` refuses a
    field the declaration does not carry, which is what makes deleting a
    reference take the number out of the fight with a named error rather
    than leaving a reader quietly defaulting.
    """

    rule: BehaviorRule
    fields: tuple[KernelField, ...]

    @property
    def owner(self) -> str:
        """The item whose registry entry carries this sustain."""
        return self.rule.owner

    def value(self, name: str) -> float:
        """One declared number, by the field name it was declared under."""
        for field in self.fields:
            if field.name == name:
                return float(field.value)
        raise SustainInterpretationError(
            f"{self.rule.mechanic_id} declares no {name!r} value; a sustain "
            "rule reads the numbers its declaration names and no others"
        )


def sustain_rules(
    owners: Sequence[str], payload_type: type
) -> tuple[BehaviorRule, ...]:
    """Every sustain rule of one shape *owners* bring, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.SUSTAIN and isinstance(rule.payload, payload_type)
    )


def sustain_slot(
    owners: Sequence[str],
    payload_type: type,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> SustainSlot | None:
    """This build's sustain of one shape, or ``None`` if nobody declares one.

    ``None`` is an answer and not a zero: no holder restores health this way,
    so no rule ran.  Two holders of one shape is a stop, because nothing
    declares how two of them compose — the same refusal the shred slot makes.
    """
    rules = sustain_rules(owners, payload_type)
    if not rules:
        return None
    if len(rules) > 1:
        raise SustainInterpretationError(
            f"{[rule.owner for rule in rules]} all declare "
            f"{payload_type.__name__} and no rule declares how two of them "
            "compose; the slice that declares a second one owns the fold"
        )
    rule = rules[0]
    return SustainSlot(
        rule=rule,
        fields=PAIR_INTERPRETER.compile(
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


def declared_sustain(owners: Sequence[str], payload_type: type) -> SustainSlot | None:
    """This build's sustain of one shape, from flat references alone.

    The companion to :func:`sustain_slot`, for the two callers that author a
    heal *before* a fight context exists: the pipeline's item-heal events are
    built from a finished damage list, and the roster's resource ledger is
    built from incoming packets.  Neither has a level, a target's bonus
    health or the holder's range class to hand, and inventing them so an
    accessor's signature is satisfied is how a defaulted zero duration gets
    into a ramping magnitude.

    So this refuses instead.  Every reference the shape declares must be a
    plain :class:`~..value_ref.ValueRef`; a level ramp or any other
    context-dependent reference is a stop naming the shape, which is what
    stops this becoming a quiet second answer to the question
    :func:`sustain_slot` asks.  ``None`` means no holder declares the shape —
    an answer, not a zero — and two holders is the same stop as there.
    """
    rules = sustain_rules(owners, payload_type)
    if not rules:
        return None
    if len(rules) > 1:
        raise SustainInterpretationError(
            f"{[rule.owner for rule in rules]} all declare "
            f"{payload_type.__name__} and no rule declares how two of them "
            "compose; the slice that declares a second one owns the fold"
        )
    rule = rules[0]
    payload = rule.payload
    names = SUSTAIN_PAYLOAD_REFERENCES[type(payload)]
    try:
        values = resolve_flat([getattr(payload, name) for name in names])
    except ValueRefError as exc:
        raise SustainInterpretationError(
            f"{rule.mechanic_id} declares a reference that needs a level or a "
            "fight fact, and this accessor has neither; read it through "
            "sustain_slot, which is handed the context it resolves against"
        ) from exc
    return SustainSlot(
        rule=rule,
        fields=tuple(
            KernelField(
                name=name,
                value=value,
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            )
            for name, value in zip(names, values)
        ),
    )


def stat_grants(owners: Sequence[str], stat: SustainStat) -> tuple[BehaviorRule, ...]:
    """Every declared grant of one vampirism stat, in build order.

    Grants sum rather than refusing a second holder, because two life-steal
    items really do stack — which is the one place this family's fold is not
    a single slot.
    """
    return tuple(
        rule
        for rule in sustain_rules(owners, SustainStatRule)
        if isinstance(rule.payload, SustainStatRule) and rule.payload.stat is stat
    )


__all__ = [
    "PAIR_INTERPRETER",
    "RECEIVED_HEALING_MULTIPLIER_FIELD",
    "RESOLVER_INTERPRETER",
    "SustainInterpretationError",
    "SustainPairInterpreter",
    "SustainResolverInterpreter",
    "SustainSlot",
    "declared_sustain",
    "received_healing_multiplier",
    "stat_grants",
    "sustain_rules",
    "sustain_slot",
]
