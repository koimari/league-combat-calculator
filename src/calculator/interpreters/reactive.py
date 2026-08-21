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

# The three sourced numbers a Thorns declaration strikes back with, named
# after the reference each was declared under.  The walk reads them as its own
# lane's fields, so a reader can tell a number the coupled timeline compiled
# from one the defensive resolver granted.
THORNS_FIELDS: tuple[str, ...] = ("base", "bonus_armor_ratio", "grievous_duration")


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


class ReactiveWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The receipt walk's answer for the one reactive mechanic it pays itself.

    Thorns is not staged from resolved defensive state: it writes none, and
    the coupled timeline compiles the declaration at its own boundary — one
    profile per roster actor, per fight — before scheduling a strike-back
    event against whoever swung.  That is a walk-lane interpretation and it
    has been one since the family was migrated; what it lacked was a
    registration saying so, which left the lane counted as a gap whose dated
    receipt said the walks stage the resolver's work.  They do for the two
    reactive shields and they do not for this.

    Field for field this is :func:`thorns_effects`' own arithmetic, shared
    through :func:`_thorns_fields`, so the registered interpreter and the
    accessor the timeline calls cannot answer differently — the same single
    arithmetic home the sustain family's walk half keeps.
    """

    FAMILY = RuleFamily.REACTIVE
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """One Thorns declaration's numbers, on the lane that pays them.

        ``ctx`` is unread: every reference a strike-back declares is flat, and
        the boundary that builds a walk has no level to resolve a ramp
        against.
        """
        del ctx
        return _thorns_fields(rule, EngineLane.RECEIPT_WALK)


RESOLVER_INTERPRETER = ReactiveResolverInterpreter()
WALK_INTERPRETER = ReactiveWalkInterpreter()


def _thorns_fields(rule: BehaviorRule, lane: EngineLane) -> tuple[KernelField, ...]:
    """One strike-back declaration's sourced numbers, or a named stop.

    A reactive rule that is not Thorns is refused rather than compiled to an
    empty tuple: the two Noxian shields reach the walk as the resolved state
    the defensive resolver granted, so asking this lane for one would be a
    second producer of a number that already has one.
    """
    slot = DefenseSlot(rule)
    if slot.mechanic is not DefenseMechanic.THORNS:
        raise DefenseInterpretationError(
            f"{rule.mechanic_id} declares reactive and is not a strike-back; "
            "the walk stages a reactive shield as the resolved state the "
            "defensive resolver granted, and compiling one here would price it "
            "twice"
        )
    return tuple(
        KernelField(
            name=name,
            value=slot.value(name),
            lane=lane,
            rule_id=rule.mechanic_id,
        )
        for name in THORNS_FIELDS
    )


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
            if DefenseSlot(rule).mechanic is not DefenseMechanic.THORNS:
                continue
            values = {
                field.name: field.value
                for field in _thorns_fields(rule, EngineLane.RECEIPT_WALK)
            }
            compiled.append(
                ThornsEffect(
                    item_name=owner,
                    damage_type=defense_state.payload(rule).damage_class.value,
                    damage=float(values["base"]),
                    bonus_armor_ratio=float(values["bonus_armor_ratio"]),
                    grievous_duration=float(values["grievous_duration"]),
                )
            )
    return tuple(compiled)


__all__ = [
    "REACTIVE_SHIELD_NOTE",
    "REACTIVE_SHIELD_SOURCE",
    "RESOLVER_INTERPRETER",
    "THORNS_FIELDS",
    "WALK_INTERPRETER",
    "ReactiveResolverInterpreter",
    "ReactiveWalkInterpreter",
    "thorns_effects",
]
