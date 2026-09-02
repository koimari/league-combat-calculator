"""Stat derivation: the shapes the build's stat block is assembled from.

``item_behavior.STAT_DERIVATION_REQUIRED_REFERENCES`` is the family's roster;
this module interprets every member of it and nothing else.

They are one family because of *when* they are answered, not what they say:
every one of them is resolved before any damage exists, folded into the
block that the pair engine, both walks and the passive-target model then
read.  That is why the family's two lanes are the stat resolver and the pair
engine and neither walk — a walk-lane interpreter here would be a second
producer of a number the block already holds.

The interpreter emits the declaration's own sourced numbers as
:class:`~..item_behavior.KernelField`s, named after the field they were
declared under, and refuses a field the rule does not carry.  It does not
apply them: ``item_effects.resolve_stat_effects`` owns the fold, and one
producer of a stat is the property this family exists to keep.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    STAT_DERIVATION_OPTIONAL_REFERENCES,
    STAT_DERIVATION_PAYLOADS,
    STAT_DERIVATION_REQUIRED_REFERENCES,
    STAT_DERIVATION_UNGRANTED_PAYLOADS,
    BehaviorRule,
    BuildContext,
    DerivedStat,
    EngineLane,
    KernelField,
    MeleeRangedSplit,
    PenetrationChannelRule,
    RuleFamily,
    StatAvailability,
    compiled_value,
    sole_declaration,
)
from ..item_behavior_catalog import behavior_rules
from ..value_ref import ValueRefError, resolve, resolve_flat


class StatDerivationInterpretationError(ValueError):
    """A stat-derivation rule was asked something its payload does not answer."""


def reference_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """Every sourced number one stat-derivation declaration resolves to.

    A declared absence contributes no field at all, which is the whole point
    of the optional half of the reference tables: a mechanic with no ceiling
    must not publish a zero ceiling that a reader would then cap against.

    Registered for the stat resolver and the pair engine, on two keys rather
    than one: a :class:`KernelField` carries the lane it was built for, so a
    field the pair engine reads must say so or the two lanes' fields become
    indistinguishable the moment anything collects them together.
    """
    payload = rule.payload
    if not isinstance(payload, STAT_DERIVATION_PAYLOADS):
        raise StatDerivationInterpretationError(
            f"{rule.mechanic_id} is not a stat-derivation rule"
        )
    names = (
        STAT_DERIVATION_REQUIRED_REFERENCES[type(payload)]
        + STAT_DERIVATION_OPTIONAL_REFERENCES[type(payload)]
    )
    fields: list[KernelField] = []
    for name in names:
        reference = getattr(payload, name)
        if reference is None:
            continue
        if isinstance(reference, MeleeRangedSplit):
            reference = reference.melee if ctx.holder_is_melee else reference.ranged
        fields.append(
            KernelField(
                name=name,
                value=resolve(reference, ctx.level),
                lane=lane,
                rule_id=rule.mechanic_id,
            )
        )
    return tuple(fields)


def granted_stat(payload: object) -> DerivedStat | None:
    """The stat a stat-derivation payload feeds, or ``None`` for none.

    Two payloads grant no stat at all -- an ultimate cooldown refund and an
    active window's cast economy -- and ``item_behavior`` names them, so the
    absence is read off that declaration rather than off a missing attribute.
    """
    if isinstance(payload, STAT_DERIVATION_UNGRANTED_PAYLOADS):
        return None
    if not isinstance(payload, STAT_DERIVATION_PAYLOADS):
        raise StatDerivationInterpretationError(
            f"{type(payload).__name__} is not a stat-derivation payload"
        )
    return payload.granted


@dataclass(frozen=True, slots=True)
class StatSlot:
    """One holder's stat derivation, resolved for one build.

    The accessor an engine holds instead of an item name.  ``value`` refuses
    a field the declaration does not carry, so deleting a reference takes the
    number out of the build with a named error rather than leaving a reader
    quietly defaulting — the same refusal the sustain slot makes.
    """

    rule: BehaviorRule
    fields: tuple[KernelField, ...]

    @property
    def owner(self) -> str:
        """The item whose registry entry carries this derivation."""
        return self.rule.owner

    @property
    def granted(self) -> DerivedStat | None:
        """The stat this derivation feeds, or ``None`` when it feeds none."""
        return granted_stat(self.rule.payload)

    @property
    def availability(self) -> StatAvailability:
        """When this stat is in the block the engines read."""
        return self.rule.payload.availability

    def value(self, name: str) -> float:
        """One declared number, by the field name it was declared under."""
        return compiled_value(
            self.fields,
            name,
            StatDerivationInterpretationError,
            f"{self.rule.mechanic_id} declares no {name!r} value; a stat derivation "
            "reads the numbers its declaration names and no others",
        )


def stat_derivation_rules(
    owners: Sequence[str], payload_type: type
) -> tuple[BehaviorRule, ...]:
    """Every stat-derivation rule of one shape *owners* bring, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.STAT_DERIVATION
        and isinstance(rule.payload, payload_type)
    )


def sole_declared_derivation(
    owners: Sequence[str], payload_type: type
) -> StatSlot | None:
    """This build's one derivation of a shape that does not compose, or ``None``.

    The companion to :func:`declared_stat_derivations` for shapes whose
    numbers multiply rather than grant.  Nothing declares how two casting
    trades compose, so a second holder is a named stop rather than whichever
    slot sorts first.  ``None`` is an answer and not a zero: no holder
    declares the shape, so the number the caller would have multiplied stays
    as it was.
    """
    slots = declared_stat_derivations(owners, payload_type)
    return sole_declaration(
        slots,
        [slot.owner for slot in slots],
        payload_type,
        StatDerivationInterpretationError,
    )


def declared_stat_derivations(
    owners: Sequence[str], payload_type: type
) -> tuple[StatSlot, ...]:
    """This build's derivations of one shape, from flat references alone.

    The twin of the sustain family's ``declared_sustain``: for the readers
    that author from a build and a
    duration before any fight context exists.  Both refuse a reference
    needing a level or a fight fact rather than inventing one — the shared
    check is ``value_ref.resolve_flat``, so "level-independent" is decided in
    one place for both families instead of twice.

    A tuple: two holders of one derivation both grant, so refusing a second
    would invent a restriction the game does not have.
    """
    slots: list[StatSlot] = []
    for rule in stat_derivation_rules(owners, payload_type):
        payload = rule.payload
        names = tuple(
            name
            for name in (
                STAT_DERIVATION_REQUIRED_REFERENCES[type(payload)]
                + STAT_DERIVATION_OPTIONAL_REFERENCES[type(payload)]
            )
            if getattr(payload, name) is not None
        )
        try:
            values = resolve_flat([getattr(payload, name) for name in names])
        except ValueRefError as exc:
            raise StatDerivationInterpretationError(
                f"{rule.mechanic_id} declares a reference that needs a level "
                "or a fight fact, and this accessor has neither; resolve it "
                "through the family's interpreter with a build context"
            ) from exc
        slots.append(
            StatSlot(
                rule=rule,
                fields=tuple(
                    KernelField(
                        name=name,
                        value=value,
                        lane=EngineLane.STAT_RESOLVER,
                        rule_id=rule.mechanic_id,
                    )
                    for name, value in zip(names, values, strict=False)
                ),
            )
        )
    return tuple(slots)


def armor_penetration_split(owner: str, percent: float) -> tuple[float, float]:
    """One item's percent armour penetration, split into the channels it feeds.

    Returns ``(total_channel, bonus_channel)`` — the two stat-block fields the
    cached ``armorPenetration`` percentage can land in, exactly one of which
    carries it.  The item says which through its
    :class:`~..item_behavior.PenetrationChannelRule`, which the build's stat
    fold reads.

    A holder with no percentage is asked no channel question: nothing to route
    means both channels are a measured zero, and refusing there would make
    every ordinary item a stop.  A holder that *does* carry one and declares
    no channel **is** a stop, naming the item — which armour a penetration
    reaches is a sourced fact about the item, and defaulting it to the
    ordinary channel is how a bonus-armour item would silently start cutting
    base armour too.
    """
    if not percent:
        return 0.0, 0.0
    slots = declared_stat_derivations([owner], PenetrationChannelRule)
    if not slots:
        raise StatDerivationInterpretationError(
            f"{owner} carries {percent}% armour penetration and declares no "
            "channel for it; which armour a percentage penetration reaches is "
            "a sourced property of the item, so an undeclared one is withheld "
            "rather than routed to the ordinary channel by default"
        )
    if len(slots) > 1:
        raise StatDerivationInterpretationError(
            f"{owner} declares {len(slots)} armour-penetration channels and "
            "nothing declares which of them one percentage lands in"
        )
    granted = slots[0].granted
    if granted is DerivedStat.ARMOR_PENETRATION_BONUS_PERCENT:
        return 0.0, percent
    return percent, 0.0


__all__ = [
    "StatDerivationInterpretationError",
    "StatSlot",
    "armor_penetration_split",
    "declared_stat_derivations",
    "reference_fields",
    "sole_declared_derivation",
    "stat_derivation_rules",
]
