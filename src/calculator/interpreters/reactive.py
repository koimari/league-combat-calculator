"""Defences armed by an incoming event rather than by the clock.

Three mechanics, and the family's whole point is in the word *armed*: a
reactive shield is granted **after** a typed champion hit lands, so it must
not absorb the hit that armed it, and Thorns strikes back at whoever swung.
Neither is a defence the subject is holding when the exchange opens, which
is why they are their own family rather than opening defences with a delay.

The two Noxian boots publish a shield the ordered ledger arms; Thorns
publishes the strike-back packet the coupled timeline schedules against the
attacker.  Thorns writes no resolved defensive state at all — its
``writes`` is empty and that is the declaration saying so — because what it
produces is an event, not a state the subject starts the fight in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DefenseField,
    DefenseMechanic,
    DefenseOutcome,
    DefenseSubject,
    EngineLane,
    KernelField,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules
from ..item_effects import ThornsEffect
from . import defense_state
from .defense_state import DefenseInterpretationError, DefenseSlot

# The published sentence and state-source label of a typed reactive shield.
# Both name the boots that granted them, which is why both interpolate the
# owner the declaration carries rather than being written twice.
REACTIVE_SHIELD_NOTE = (
    "{owner}'s typed reactive shield is ready and is granted "
    "after champion {damage_type} damage."
)

REACTIVE_SHIELD_SOURCE = "{owner} — Noxian"

_REACTIVE_SHIELDS = frozenset(
    {DefenseMechanic.NOXIAN_ENDURANCE, DefenseMechanic.NOXIAN_PERSISTENCE}
)


class ReactiveResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The defensive resolver's answer for the ``reactive`` family."""

    FAMILY = RuleFamily.REACTIVE
    LANES = frozenset({EngineLane.DEFENSE_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape a reactive defence compiles to, at build time."""
        return defense_state.compiled_shape(rule, ctx.level)

    def resolve(self, rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
        """One reactive defence, against the subject it is defending."""
        slot = DefenseSlot(rule)
        if slot.mechanic in _REACTIVE_SHIELDS:
            return _reactive_shield(slot, subject)
        if slot.mechanic is DefenseMechanic.THORNS:
            return DefenseOutcome(fields=(), notes=())
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares reactive and this interpreter has no "
            "branch for it; a defence with no arithmetic is a mechanic that "
            "would silently do nothing"
        )


RESOLVER_INTERPRETER = ReactiveResolverInterpreter()


def _reactive_shield(slot: DefenseSlot, subject: DefenseSubject) -> DefenseOutcome:
    """A level-ramped shield plus a share of the subject's bonus health."""
    absorbs = defense_state.payload(slot.rule).absorbs
    amount = slot.late_ramp("reactive_shield_base", subject.level) + slot.value(
        "reactive_shield_bonus_health_ratio"
    ) * subject.stat("bonus_health")
    fields = [
        slot.grant(DefenseField.REACTIVE_SHIELD_AMOUNT, amount),
        slot.grant(DefenseField.REACTIVE_SHIELD_DAMAGE_TYPE, absorbs.value),
        slot.grant(
            DefenseField.REACTIVE_SHIELD_DURATION,
            slot.value("reactive_shield_duration"),
        ),
        slot.grant(
            DefenseField.REACTIVE_SHIELD_COOLDOWN,
            slot.value("reactive_shield_cooldown"),
        ),
        slot.grant(
            DefenseField.REACTIVE_SHIELD_SOURCE,
            REACTIVE_SHIELD_SOURCE.format(owner=slot.owner),
        ),
    ]
    if slot.mechanic is DefenseMechanic.NOXIAN_ENDURANCE:
        fields.insert(
            0,
            slot.grant(
                DefenseField.BASIC_DAMAGE_MULTIPLIER,
                slot.value("basic_damage_multiplier"),
            ),
        )
    return DefenseOutcome(
        fields=tuple(fields),
        notes=(
            REACTIVE_SHIELD_NOTE.format(owner=slot.owner, damage_type=absorbs.value),
        ),
    )


def thorns_effects(items: Sequence[Mapping[str, object]]) -> tuple[ThornsEffect, ...]:
    """The build's reactive strike-back packets, in the order it bought them.

    One packet per equipped Thorns item and none without one.  The record the
    coupled timeline consumes is unchanged; what changed is where its numbers
    come from — the item's declaration rather than a tag comparison inside
    the number registry, so a Thorns item whose declaration was deleted stops
    striking back with a named refusal instead of quietly dealing zero.
    """
    compiled: list[ThornsEffect] = []
    for item in items:
        owner = str(item.get("name", ""))
        for rule in behavior_rules(owner):
            if rule.family is not RuleFamily.REACTIVE:
                continue
            slot = DefenseSlot(rule)
            if slot.mechanic is not DefenseMechanic.THORNS:
                continue
            damage_class = defense_state.payload(rule).damage_class
            compiled.append(
                ThornsEffect(
                    item_name=owner,
                    damage_type=damage_class.value,
                    damage=slot.value("base"),
                    bonus_armor_ratio=slot.value("bonus_armor_ratio"),
                    grievous_duration=slot.value("grievous_duration"),
                )
            )
    return tuple(compiled)


__all__ = [
    "REACTIVE_SHIELD_NOTE",
    "REACTIVE_SHIELD_SOURCE",
    "RESOLVER_INTERPRETER",
    "ReactiveResolverInterpreter",
    "thorns_effects",
]
