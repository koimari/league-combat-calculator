"""Cross-participant packets, interpreted for the roster walk.

The ally-packet family is the one whose members share no arithmetic.
Redemption heals a radius and Phage grants move speed; Imperial Mandate curses
an enemy and Cull books gold.  What they share is the *shape of the emission*
— which producer, which packet kinds, to whom, on what trigger — and the
emitters in ``item_support_effects`` are the code that turns one of those
shapes into timestamped packets.

This module is what stands between the two.  It resolves the declarations a
build's items carry into :class:`AllyPacketSlot`s keyed by producer, so an
emitter asks *"does this holder declare Everlasting?"* instead of asking
*"is the string ``Fimbulwinter`` in this holder's item names?"*, and it hands
every number back through the rule's own references, so a key the declaration
does not carry is a stop rather than a silent registry read.

Two consequences are the point of the exercise:

* deleting a producer's declaration takes its packets out of the walk with a
  named refusal, instead of leaving an emitter reading numbers for a mechanic
  nothing declares; and
* the pair engine has no lane here at all.  An ally packet is a roster fact,
  and the family's declared lanes say so.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from ..item_behavior import (
    AllyPacketRule,
    AllyProducer,
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    PacketKind,
    PacketSpec,
    PacketTrigger,
    Recipients,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules
from ..value_ref import LevelValueRef, ValueRef


class AllyPacketInterpretationError(ValueError):
    """A producer was asked something its declaration does not answer."""


def _payload(rule: BehaviorRule) -> AllyPacketRule:
    """*rule*'s ally-packet payload, or a stop."""
    payload = rule.payload
    if not isinstance(payload, AllyPacketRule):
        raise AllyPacketInterpretationError(
            f"{rule.mechanic_id} is not an ally-packet rule"
        )
    return payload


class AllyPacketWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The roster walk's answer for the ``ally_packet`` family.

    One field per declared value, named by the registry key it reads, so the
    compiled form of a producer is exactly "the numbers this mechanic is
    allowed to use, resolved".  Level ramps resolve at the build context's
    level; the emitters re-resolve them per recipient, because a shield read
    at the *holder's* level when it lands on an ally of another level is a
    wrong number nobody would see.
    """

    FAMILY = RuleFamily.ALLY_PACKET
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """Every number this producer declares, read live from its registry."""
        payload = _payload(rule)
        fields: list[KernelField] = []
        for reference in payload.values:
            if isinstance(reference, ValueRef):
                name, value = reference.key, reference.get()
            elif isinstance(reference, LevelValueRef):
                name, value = reference.min_key, reference.get(ctx.level)
            else:
                raise AllyPacketInterpretationError(
                    f"{rule.mechanic_id} declares {reference!r}, which names no "
                    "registry key for the walk to read it back by"
                )
            fields.append(
                KernelField(
                    name=name,
                    value=value,
                    lane=EngineLane.RECEIPT_WALK,
                    rule_id=rule.mechanic_id,
                )
            )
        return tuple(fields)


WALK_INTERPRETER = AllyPacketWalkInterpreter()


@dataclass(frozen=True, slots=True)
class AllyPacketSlot:
    """One holder's declared producer, with the numbers it may read.

    The emitters hold one of these instead of an item name.  Every accessor
    refuses rather than defaults: an undeclared key, an undeclared packet kind
    and a level read against a reference that is not level-scaled are each a
    stop, because the whole point of the declaration is that the emitter
    cannot reach past it.
    """

    rule: BehaviorRule

    @property
    def owner(self) -> str:
        """The item whose registry entry carries this producer."""
        return self.rule.owner

    @property
    def producer(self) -> AllyProducer:
        """Which mechanic this slot is."""
        return _payload(self.rule).producer

    @property
    def trigger(self) -> PacketTrigger:
        """What arms this producer."""
        return _payload(self.rule).trigger

    def emits(self, kind: PacketKind, recipients: Recipients) -> bool:
        """Whether this producer declares a packet of *kind* to *recipients*.

        The question an engine asks when it wants to know whether a mechanic
        lands inside its own jurisdiction — a shield the *holder* receives is
        priced by the pair engine, while the same producer's packet to an ally
        is the roster walk's.  Answered off the declared
        :class:`~..item_behavior.PacketSpec`s, so a producer that grows or
        loses a recipient reaches every such reader on the commit its
        declaration changes.
        """
        return any(
            spec.kind is kind and spec.recipients is recipients
            for spec in _payload(self.rule).packets
        )

    def value(self, key: str) -> float:
        """One declared number, read live from the registry that owns it."""
        for reference in _payload(self.rule).values:
            if isinstance(reference, ValueRef) and reference.key == key:
                return reference.get()
        raise AllyPacketInterpretationError(
            f"{self.rule.mechanic_id} declares no {key!r} value; a producer "
            "reads the numbers its declaration names and no others"
        )

    def level_value(self, key: str, level: int) -> float:
        """One declared level ramp, read at *level*.

        *key* is the ramp's low key, which is how the declaration names it —
        a ramp is one number with two ends, not two numbers.
        """
        for reference in _payload(self.rule).values:
            if isinstance(reference, LevelValueRef) and reference.min_key == key:
                return reference.get(level)
        raise AllyPacketInterpretationError(
            f"{self.rule.mechanic_id} declares no {key!r} level ramp"
        )

    def declared(self, kind: PacketKind) -> PacketSpec:
        """The declared packet of *kind*, or a stop.

        Called by an emitter before it builds a packet, so a packet whose kind
        the producer never declared cannot enter the walk — and deleting a
        :class:`~..item_behavior.PacketSpec` from a declaration turns the
        fight red rather than quietly dropping a receipt.
        """
        for spec in _payload(self.rule).packets:
            if spec.kind is kind:
                return spec
        raise AllyPacketInterpretationError(
            f"{self.rule.mechanic_id} declares no {kind.value} packet; the "
            "emitter built one its declaration does not carry"
        )


def resolve_slots(
    names: Collection[str],
) -> Mapping[AllyProducer, tuple[AllyPacketSlot, ...]]:
    """Every ally-packet producer this build's items declare, by producer.

    A tuple per producer rather than one slot, because two items really can
    carry one mechanic: the support quest is the same quest whichever
    transformed item is equipped.  Owners are walked in sorted order so a
    build holding both emits in a stated order rather than in whichever order
    the caller's set happened to iterate.
    """
    slots: dict[AllyProducer, tuple[AllyPacketSlot, ...]] = {}
    for owner in sorted(frozenset(names)):
        for rule in behavior_rules(owner):
            if rule.family is not RuleFamily.ALLY_PACKET:
                continue
            producer = _payload(rule).producer
            slots[producer] = slots.get(producer, ()) + (AllyPacketSlot(rule),)
    return slots


__all__ = [
    "AllyPacketInterpretationError",
    "AllyPacketSlot",
    "AllyPacketWalkInterpreter",
    "WALK_INTERPRETER",
    "resolve_slots",
]
