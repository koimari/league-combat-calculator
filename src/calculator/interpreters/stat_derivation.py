"""Stat derivation: eight shapes the build's stat block is assembled from.

A stat converted from another stat by a sourced ratio, a percentage
multiplier on a total, the mana a charge ledger accrues, a stat that grows
per stack, a flat grant, an aura that reduces a stat on the enemy, a
regeneration a bonus-health threshold unlocks, and an ultimate cooldown
refund bought with lethality.

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
    BehaviorRule,
    BuildContext,
    DerivedStat,
    EngineLane,
    KernelField,
    MeleeRangedSplit,
    RuleFamily,
    STAT_DERIVATION_OPTIONAL_REFERENCES,
    STAT_DERIVATION_PAYLOADS,
    STAT_DERIVATION_REQUIRED_REFERENCES,
    StatAvailability,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import ValueRefError, resolve, resolve_flat


class StatDerivationInterpretationError(ValueError):
    """A stat-derivation rule was asked something its payload does not answer."""


def _reference_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """Every sourced number one stat-derivation declaration resolves to.

    A declared absence contributes no field at all, which is the whole point
    of the optional half of the reference tables: a mechanic with no ceiling
    must not publish a zero ceiling that a reader would then cap against.
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


class StatDerivationResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The stat resolver's answer: the numbers, before anything reads them."""

    FAMILY = RuleFamily.STAT_DERIVATION
    LANES = frozenset({EngineLane.STAT_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """One declaration's sourced numbers, resolved for this build."""
        return _reference_fields(rule, ctx, EngineLane.STAT_RESOLVER)


class StatDerivationPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer, which is the same numbers on its own lane.

    Two registrations rather than one shared interpreter object because a
    :class:`KernelField` carries the lane it was built for: a field the pair
    engine reads must say so, or the two lanes' fields become
    indistinguishable the moment anything collects them together.
    """

    FAMILY = RuleFamily.STAT_DERIVATION
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """One declaration's sourced numbers, resolved for this build."""
        return _reference_fields(rule, ctx, EngineLane.PAIR_ENGINE)


RESOLVER_INTERPRETER = StatDerivationResolverInterpreter()
PAIR_INTERPRETER = StatDerivationPairInterpreter()


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
        """The stat this derivation feeds, or ``None`` for the refund shape."""
        return getattr(self.rule.payload, "granted", None)

    @property
    def availability(self) -> StatAvailability:
        """When this stat is in the block the engines read."""
        return self.rule.payload.availability

    def value(self, name: str) -> float:
        """One declared number, by the field name it was declared under."""
        for field in self.fields:
            if field.name == name:
                return float(field.value)
        raise StatDerivationInterpretationError(
            f"{self.rule.mechanic_id} declares no {name!r} value; a stat "
            "derivation reads the numbers its declaration names and no others"
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


def stat_slots(
    owners: Sequence[str],
    payload_type: type,
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> tuple[StatSlot, ...]:
    """This build's stat derivations of one shape, in build order.

    A tuple and not a single slot, unlike the sustain family: two mana items
    really do both convert, and their grants sum — so refusing a second
    holder here would be inventing a restriction the game does not have.
    """
    return tuple(
        StatSlot(
            rule=rule,
            fields=RESOLVER_INTERPRETER.compile(
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
        for rule in stat_derivation_rules(owners, payload_type)
    )


def declared_stat_derivations(
    owners: Sequence[str], payload_type: type
) -> tuple[StatSlot, ...]:
    """This build's derivations of one shape, from flat references alone.

    The companion to :func:`stat_slots`, and the twin of the sustain family's
    ``declared_sustain``: for the readers that author from a build and a
    duration before any fight context exists.  Both refuse a reference
    needing a level or a fight fact rather than inventing one — the shared
    check is ``value_ref.resolve_flat``, so "level-independent" is decided in
    one place for both families instead of twice.

    A tuple like :func:`stat_slots`, and for the same reason: two holders of
    one derivation both grant, so refusing a second would invent a
    restriction the game does not have.
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
                "or a fight fact, and this accessor has neither; read it "
                "through stat_slots, which is handed the context it resolves "
                "against"
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
                    for name, value in zip(names, values)
                ),
            )
        )
    return tuple(slots)


__all__ = [
    "PAIR_INTERPRETER",
    "RESOLVER_INTERPRETER",
    "StatDerivationInterpretationError",
    "StatDerivationPairInterpreter",
    "StatDerivationResolverInterpreter",
    "StatSlot",
    "declared_stat_derivations",
    "stat_derivation_rules",
    "stat_slots",
]
