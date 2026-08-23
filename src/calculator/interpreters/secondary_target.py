"""Bolts at targets the attack was not aimed at, interpreted.

Wind's Fury is the whole family: an attack fires extra bolts at nearby enemies
for a share of the attacker's damage.

The declaration says the two things the mechanic is: how many extra targets it
may reach and what share of the attack each one takes.  Neither is a damage
formula, because the bolt's number is a share of the swing that fired it
rather than a sum of its own shares — which is exactly why this is its own
family and not a strike with an unusual basis.

Target *allocation* stays with the roster ledger, which is the only thing that
knows who is standing where.  This module supplies the sourced cardinality and
the sourced share, and refuses both when no holder declares them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    RuleFamily,
    SecondaryTargetRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve

MAX_TARGETS_FIELD = "secondary_max_targets"
DAMAGE_SHARE_FIELD = "secondary_damage_share"


class SecondaryTargetInterpretationError(ValueError):
    """A rule reached this interpreter that is not a secondary-target rule."""


def routing_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """This rule's two routing facts, stamped with *lane*.

    A cardinality and a share, and **no magnitude**: this is a *routing*
    family, so the packets it re-delivers are priced from the declarations of
    the families that own them and what is compiled here is only how far the
    routing reaches and what share of the swing rides it.  A third field would
    be a second producer of a number a source family already declares.

    Registered for both the pair engine and the receipt walk: the lane is the
    only thing that differs between them, so one body is what makes "the walk
    reads the same declaration the pair engine reads" a property of the tree
    rather than a claim two functions could drift out of.
    """
    payload = rule.payload
    if not isinstance(payload, SecondaryTargetRule):
        raise SecondaryTargetInterpretationError(
            f"{rule.mechanic_id} is not a secondary-target rule"
        )

    def field(name: str, value: float) -> KernelField:
        return KernelField(
            name=name,
            value=value,
            lane=lane,
            rule_id=rule.mechanic_id,
        )

    return (
        field(MAX_TARGETS_FIELD, resolve(payload.max_targets, ctx.level)),
        field(DAMAGE_SHARE_FIELD, resolve(payload.damage_share, ctx.level)),
    )


@dataclass(frozen=True, slots=True)
class SecondaryTargetSlot:
    """One build's declared secondary-target strike, resolved."""

    rule: BehaviorRule
    fields: tuple[KernelField, ...]

    def value(self, name: str) -> float:
        """One compiled field of the slot's rule, or a stop."""
        for field in self.fields:
            if field.name == name:
                return float(field.value)
        raise SecondaryTargetInterpretationError(
            f"{self.rule.mechanic_id} compiles no {name!r} field; the engine "
            "asked its declaration a question it does not answer"
        )

    def bolt_count(self, roster_target_count: int) -> int:
        """How many *extra* targets the bolts reach: the declared cap, less the
        main target, which the attack itself hits.
        """
        if roster_target_count <= 1:
            return 0
        return min(int(self.value(MAX_TARGETS_FIELD)), roster_target_count - 1)

    def bolt_damage(self, total_attack_damage: float) -> float:
        """One bolt's raw packet: the declared share of the attacker's damage."""
        return float(total_attack_damage) * self.value(DAMAGE_SHARE_FIELD)

    @property
    def applies_on_hit(self) -> bool:
        """Whether a bolt carries the attack's on-hit effects with it."""
        payload = self.rule.payload
        if not isinstance(payload, SecondaryTargetRule):
            raise SecondaryTargetInterpretationError(
                f"{self.rule.mechanic_id} is not a secondary-target rule"
            )
        return payload.applies_on_hit

    @property
    def owner(self) -> str:
        """The holder the bolts are filed under."""
        return self.rule.owner

    @property
    def mechanic_id(self) -> str:
        """The rule the pair engine stamps its two rows as a preview of."""
        return self.rule.mechanic_id


def resolve_slot(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> SecondaryTargetSlot | None:
    """This build's secondary-target strike, or ``None`` if nobody declares one.

    ``None`` is an answer and not a zero: the attack hits what it was aimed at
    and no rule had anything to add.
    """
    rules = tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.SECONDARY_TARGET
    )
    if not rules:
        return None
    if len(rules) > 1:
        raise SecondaryTargetInterpretationError(
            f"{[rule.owner for rule in rules]} all declare secondary targets and "
            "no rule declares how two bolt sets combine; the slice that "
            "declares a second one owns the fold"
        )
    rule = rules[0]
    return SecondaryTargetSlot(
        rule=rule,
        fields=routing_fields(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
            EngineLane.PAIR_ENGINE,
        ),
    )


__all__ = [
    "DAMAGE_SHARE_FIELD",
    "MAX_TARGETS_FIELD",
    "SecondaryTargetInterpretationError",
    "SecondaryTargetSlot",
    "resolve_slot",
    "routing_fields",
]
