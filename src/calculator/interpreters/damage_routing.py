"""Damage routing: three mechanics that move a packet rather than resize it.

None of these three is an amplifier and none is a defence the holder keeps.
An execution decides whether a packet *ends the fight*; a shield bypass
decides how much of the target's shielding the packet has to get through;
and a deferral decides *when* the holder pays damage that has already
happened.  Grouping them by that shared question is what lets the deferral —
whose registry entry is tagged as a starting defence, because that is where
the resolver builds it — stop being a name-matched branch inside the
defensive resolver without claiming the holder took less damage.

Two lanes, because the family really is built in two places: the pair engine
prices the two target-side rules, and the defensive resolver builds the
deferral schedule at the opening with every other declared defence.
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
    ExecuteRule,
    KernelField,
    RuleFamily,
    ShieldBypassRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..value_ref import resolve
from . import defense_state
from .defense_state import DefenseInterpretationError, DefenseSlot

# The field names a routing rule compiles to on the pair lane.
EXECUTE_THRESHOLD_FIELD = "execute_threshold"
SHIELD_BYPASS_FRACTION_FIELD = "shield_bypass_fraction"
SHIELD_BYPASS_DURATION_FIELD = "shield_bypass_duration"

# Ignore Pain's own sentence, published beside the resolved state.  It names
# what the deferral does rather than the item that carries it, because the
# citation beside it already names the item.
IGNORE_PAIN_NOTE = (
    "{owner} Ignore Pain defers the sourced fraction of each "
    "post-mitigation physical or magic packet; Defy clears the "
    "remaining store and heals after a qualifying champion takedown."
)

# Which resolved field each of the deferral's sourced keys lands in, and
# which of them are counts.  A table rather than seven statements saying the
# same thing seven times — and the melee/ranged pair is deliberately absent,
# because which of the two is read is a property of the *subject* and is
# decided below.
_DEFERRAL_SCHEDULE: tuple[tuple[str, DefenseField], ...] = (
    ("damage_deferral_duration", DefenseField.DAMAGE_DEFERRAL_DURATION),
    ("damage_deferral_ticks", DefenseField.DAMAGE_DEFERRAL_TICKS),
    ("defy_window", DefenseField.DEFY_WINDOW),
    ("defy_heal_bonus_ad_ratio", DefenseField.DEFY_HEAL_BONUS_AD_RATIO),
    ("defy_heal_duration", DefenseField.DEFY_HEAL_DURATION),
    ("defy_heal_ticks", DefenseField.DEFY_HEAL_TICKS),
)

_INTEGER_FIELDS = frozenset(
    {DefenseField.DAMAGE_DEFERRAL_TICKS, DefenseField.DEFY_HEAL_TICKS}
)


class DamageRoutingInterpretationError(ValueError):
    """A routing rule was asked something its payload does not answer."""


class DamageRoutingPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the two target-side routing rules."""

    FAMILY = RuleFamily.DAMAGE_ROUTING
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The sourced numbers one routing declaration resolves to.

        The melee/ranged share is chosen here, from the build context's own
        range class, because that choice is made once per build and not per
        event — the same reason the magnitude carries a split rather than the
        typing carrying an attack class.
        """

        def field(name: str, value: float) -> KernelField:
            return KernelField(
                name=name,
                value=value,
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            )

        payload = rule.payload
        if isinstance(payload, ExecuteRule):
            return (
                field(EXECUTE_THRESHOLD_FIELD, resolve(payload.threshold, ctx.level)),
            )
        if not isinstance(payload, ShieldBypassRule):
            raise DamageRoutingInterpretationError(
                f"{rule.mechanic_id} is priced on the pair lane and is neither "
                "an execution nor a shield bypass; the deferral is built by the "
                "defensive resolver, not here"
            )
        share = (
            payload.fraction.melee if ctx.holder_is_melee else payload.fraction.ranged
        )
        return (
            field(SHIELD_BYPASS_FRACTION_FIELD, resolve(share, ctx.level)),
            field(SHIELD_BYPASS_DURATION_FIELD, resolve(payload.duration, ctx.level)),
        )


class DamageRoutingResolverInterpreter:  # pylint: disable=too-few-public-methods
    """The defensive resolver's answer for the deferral."""

    FAMILY = RuleFamily.DAMAGE_ROUTING
    LANES = frozenset({EngineLane.DEFENSE_RESOLVER})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape the deferral compiles to, at build time."""
        return defense_state.compiled_shape(rule, ctx.level)

    def resolve(self, rule: BehaviorRule, subject: DefenseSubject) -> DefenseOutcome:
        """The deferral schedule, against the subject that will pay it."""
        slot = DefenseSlot(rule)
        if slot.mechanic is not DefenseMechanic.IGNORE_PAIN:
            raise DefenseInterpretationError(
                f"{rule.mechanic_id} declares damage_routing at the resolver "
                "and this interpreter has no branch for it; a schedule with no "
                "arithmetic is a mechanic that would silently do nothing"
            )
        deferred_key = (
            "damage_deferral_melee" if subject.is_melee else "damage_deferral_ranged"
        )
        fields = [
            slot.grant(DefenseField.DAMAGE_DEFERRAL_FRACTION, slot.value(deferred_key))
        ]
        fields.extend(
            slot.grant(
                field,
                int(slot.value(key)) if field in _INTEGER_FIELDS else slot.value(key),
            )
            for key, field in _DEFERRAL_SCHEDULE
        )
        return DefenseOutcome(
            fields=tuple(fields),
            notes=(IGNORE_PAIN_NOTE.format(owner=slot.owner),),
        )


PAIR_INTERPRETER = DamageRoutingPairInterpreter()
RESOLVER_INTERPRETER = DamageRoutingResolverInterpreter()


@dataclass(frozen=True, slots=True)
class Execution:
    """One build's declared execution threshold, and the item that carries it."""

    owner: str
    threshold: float


@dataclass(frozen=True, slots=True)
class ShieldBypass:
    """One build's declared shield bypass, resolved for its holder's range."""

    owner: str
    fraction: float
    duration: float


def routing_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every pair-priced routing rule *owners* bring, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.DAMAGE_ROUTING
        and isinstance(rule.payload, (ExecuteRule, ShieldBypassRule))
    )


def _field(fields: tuple[KernelField, ...], name: str) -> float:
    """One compiled field by name, or a stop naming the question asked."""
    for compiled in fields:
        if compiled.name == name:
            return float(compiled.value)
    raise DamageRoutingInterpretationError(
        f"no routing field named {name!r} was compiled; the engine asked a "
        "declaration a question it does not answer"
    )


def resolve_execution(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> Execution | None:
    """This build's execution threshold, or ``None`` if nobody declares one.

    ``None`` is an answer and not a zero: no holder executes, so no rule ran
    and no health share is low enough to finish the target.
    """
    found = [
        rule for rule in routing_rules(owners) if isinstance(rule.payload, ExecuteRule)
    ]
    if not found:
        return None
    if len(found) > 1:
        raise DamageRoutingInterpretationError(
            f"{[rule.owner for rule in found]} all declare an execution and no "
            "rule declares how two thresholds combine; the slice that declares "
            "a second one owns the fold"
        )
    rule = found[0]
    fields = PAIR_INTERPRETER.compile(
        rule,
        build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        ),
    )
    return Execution(
        owner=rule.owner, threshold=_field(fields, EXECUTE_THRESHOLD_FIELD)
    )


def resolve_shield_bypass(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> ShieldBypass | None:
    """This build's shield bypass, or ``None`` if nobody declares one."""
    found = [
        rule
        for rule in routing_rules(owners)
        if isinstance(rule.payload, ShieldBypassRule)
    ]
    if not found:
        return None
    if len(found) > 1:
        raise DamageRoutingInterpretationError(
            f"{[rule.owner for rule in found]} all declare a shield bypass and "
            "no rule declares how two of them compose; the slice that declares "
            "a second one owns the fold"
        )
    rule = found[0]
    fields = PAIR_INTERPRETER.compile(
        rule,
        build_context(
            rule.owner,
            level,
            fight_duration_seconds=fight_duration_seconds,
            target_bonus_health=target_bonus_health,
            holder_is_melee=holder_is_melee,
        ),
    )
    return ShieldBypass(
        owner=rule.owner,
        fraction=_field(fields, SHIELD_BYPASS_FRACTION_FIELD),
        duration=_field(fields, SHIELD_BYPASS_DURATION_FIELD),
    )


__all__ = [
    "DamageRoutingInterpretationError",
    "DamageRoutingPairInterpreter",
    "DamageRoutingResolverInterpreter",
    "EXECUTE_THRESHOLD_FIELD",
    "Execution",
    "IGNORE_PAIN_NOTE",
    "PAIR_INTERPRETER",
    "RESOLVER_INTERPRETER",
    "SHIELD_BYPASS_DURATION_FIELD",
    "SHIELD_BYPASS_FRACTION_FIELD",
    "ShieldBypass",
    "resolve_execution",
    "resolve_shield_bypass",
    "routing_rules",
]
