"""Bolts at targets the attack was not aimed at, interpreted.

Wind's Fury is the whole family: an attack fires extra bolts at nearby enemies
for a share of the attacker's damage.  Its two numbers used to be reached
through accessors that carried the item's name as a *default argument* and a
``has_item(items, "Runaan's Hurricane")`` test in the fight engine — a
mechanic reachable only by spelling the item that has it.

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


def _routing_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """This rule's two routing facts, compiled for *lane*.

    A cardinality and a share, and **no magnitude**: umbrella Amendment R,
    Ruling 3 rules this a *routing* family, so the packets it re-delivers are
    priced from the declarations of the families that own them and this
    interpreter states only how far the routing reaches and what share of the
    swing rides it.  A third field here would be a second producer of a
    number a source family already declares.

    The lane is the only thing that varies between the two interpreters
    below.  Sharing the body rather than spelling it twice is what makes "the
    walk reads the same declaration the pair engine reads" a property of the
    tree instead of a claim two functions could drift out of.
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


class SecondaryTargetPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``secondary_target`` family.

    Its numbers are a **preview** since this family retired: the mechanic
    declares ``ViewTag.THEORETICAL`` on its pair lane and
    ``damage._add_single_proc_on_hits`` stamps ``pair_preview_of`` on the two
    rows it authors, so the honest one-attacker figures stay in the pair
    fight's own receipt and leave every total the roster composes.
    """

    FAMILY = RuleFamily.SECONDARY_TARGET
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The bolt count and the bolt's share, read live from the registry."""
        return _routing_fields(rule, ctx, EngineLane.PAIR_ENGINE)


class SecondaryTargetWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The receipt walk's answer for the ``secondary_target`` family.

    The half that retires ``secondary_target/receipt_walk`` — the last of
    umbrella Amendment F's fourteen — in the lane Amendment K rules and with
    the shape Amendment L, Ruling 1 requires.  Before it, the coupled walk
    consumed this family as ``participant_timeline._pair_run_fight``'s
    already-priced rows.  Now the two rows the family authors are
    declarations and no price.

    **The two rows have two different producers**, which is what makes this
    family unlike the eight before it and is umbrella Amendment R, Ruling 3's
    whole subject.  The bolt is the router's own packet — a declared share of
    the attacker's damage, delivered as a basic-attack swing and priced
    through the composition Ruling 1 added.  The copied on-hit row is the
    attack's own on-hit packets re-delivered at the bolt's target, so its
    magnitudes belong to the families that declared them and each one is
    routed rather than re-declared: ``rule_id`` stays the source mechanic's
    and the routing rides as provenance beside it.
    """

    FAMILY = RuleFamily.SECONDARY_TARGET
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The bolt count and the bolt's share, resolved for the coupled walk."""
        return _routing_fields(rule, ctx, EngineLane.RECEIPT_WALK)


PAIR_INTERPRETER = SecondaryTargetPairInterpreter()
WALK_INTERPRETER = SecondaryTargetWalkInterpreter()


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
        """How many *extra* targets the bolts reach in this roster.

        The main target is excluded — it is hit by the attack itself — so a
        roster of one has no bolts at all.  The declared cap bounds the rest.
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
        """The rule the pair engine stamps its two rows as a preview of.

        Read back off the declaration rather than spelled in the engine: the
        stamp and the walk half's delivery reference are the same string, and
        a second spelling of a mechanic slug inside ``damage.py`` is the join
        failing silently.
        """
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


__all__ = [
    "DAMAGE_SHARE_FIELD",
    "MAX_TARGETS_FIELD",
    "PAIR_INTERPRETER",
    "SecondaryTargetInterpretationError",
    "SecondaryTargetPairInterpreter",
    "SecondaryTargetSlot",
    "SecondaryTargetWalkInterpreter",
    "WALK_INTERPRETER",
    "resolve_slot",
]
