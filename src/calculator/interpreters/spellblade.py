"""Spellblades, interpreted: one mechanic, seven items, three formulas.

An ability cast arms the next basic attack.  Seven items share that mechanic
and differ only in how much the empowered attack deals and in which *sibling*
mechanic rides along — Lich Bane's attack-speed burst, Essence Reaver's mana
refund, Dusk and Dawn's self-heal.  Until this module the registry compiler
decided which item carried which by comparing item names against a table
inside itself, and read every other sibling through a
``values.get(key, 0.0)``-shaped fallback.

The declaration decides it now, from the entry's own keys, and each sibling
group is declared whole or not at all — so a parse that dropped half of the
mana refund is a stop rather than a quietly weaker item, which is exactly what
the name table bought and what the fallback undid.

**Only the first declared spellblade is armed.**  That is the engine's
standing rule, kept here rather than re-derived: the mechanics are mutually
exclusive in game, and a build holding Sheen and Trinity Force arms one.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    RuleFamily,
    SpellbladeRule,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import SpellbladeEffect, damage_source
from ..value_ref import AnyValueRef, resolve
from . import damage_formula

# The field a spellblade compiles to: the seconds before it can arm again.
SPELLBLADE_COOLDOWN_FIELD = "spellblade_cooldown"

# How a spellblade's breakdown row is named.  Presentation, kept beside the
# interpreter that builds the row rather than in the registry.
SPELLBLADE_SUFFIX = "Spellblade"
SPELLBLADE_BREAKDOWN_PREFIX = "spellblade_"

# What a spellblade with no sibling mechanic hands the engine.  The engine's
# own spelling for "this sibling does not exist"; written here, once, so the
# declaration can say *nothing* rather than say zero.
NO_SIBLING = 0.0


class SpellbladeInterpretationError(ValueError):
    """A rule reached this interpreter that is not a spellblade."""


def _payload(rule: BehaviorRule) -> SpellbladeRule:
    """*rule*'s spellblade payload, or a stop."""
    payload = rule.payload
    if not isinstance(payload, SpellbladeRule):
        raise SpellbladeInterpretationError(
            f"{rule.mechanic_id} is not a spellblade rule"
        )
    return payload


def _sibling(reference: AnyValueRef | None, level: int) -> float:
    """A declared sibling's number, or the engine's "no sibling" spelling."""
    return NO_SIBLING if reference is None else resolve(reference, level)


class SpellbladePairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``spellblade`` family."""

    FAMILY = RuleFamily.SPELLBLADE
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The cooldown this spellblade compiles to, plus its bases' proof."""
        payload = _payload(rule)
        damage_formula.compile_formula(payload.formula, ctx)
        return (
            KernelField(
                name=SPELLBLADE_COOLDOWN_FIELD,
                value=resolve(payload.cooldown, ctx.level),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            ),
        )


PAIR_INTERPRETER = SpellbladePairInterpreter()


def spellblade_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every spellblade *owners* declare, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.SPELLBLADE
    )


def declares_self_heal(owners: Sequence[str]) -> bool:
    """Whether the spellblade this build arms heals its holder.

    Answered from the declaration alone, with no build context, and only of
    the spellblade the build actually arms — a second, unarmed one heals
    nobody, so counting it would make the tuple ledger refuse a fight that is
    heal-free.
    """
    armed = spellblade_rules(owners)[:1]
    return any(
        _payload(rule).self_heal_ap_ratio is not None
        or _payload(rule).self_heal_bonus_health_ratio is not None
        for rule in armed
    )


def spellblade_effect(rule: BehaviorRule, ctx: BuildContext) -> SpellbladeEffect:
    """One declared spellblade as the record the fight engine consumes."""
    payload = _payload(rule)
    return SpellbladeEffect(
        source=damage_source(
            rule.owner,
            payload.formula.damage_class.value,
            damage_formula.compile_formula(payload.formula, ctx),
            suffix=SPELLBLADE_SUFFIX,
            breakdown_key=f"{SPELLBLADE_BREAKDOWN_PREFIX}{rule.owner}",
        ),
        cooldown=resolve(payload.cooldown, ctx.level),
        weave_delay=resolve(payload.weave_delay, ctx.level),
        double_on_hit=payload.double_on_hit,
        bonus_attack_speed_percent=_sibling(
            payload.bonus_attack_speed_percent, ctx.level
        ),
        mana_restore_base_ad_ratio=_sibling(
            payload.mana_restore_base_ad_ratio, ctx.level
        ),
        mana_restore_crit_ratio=_sibling(payload.mana_restore_crit_ratio, ctx.level),
        self_heal_ap_ratio=_sibling(payload.self_heal_ap_ratio, ctx.level),
        self_heal_bonus_health_ratio=_sibling(
            payload.self_heal_bonus_health_ratio, ctx.level
        ),
    )


def resolve_slot(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> SpellbladeEffect | None:
    """The one spellblade this build arms, or ``None`` if it declares none.

    Build order decides which: the engine has always armed the first
    spellblade a build carries and ignored the rest, because the mechanics are
    mutually exclusive.
    """
    for rule in spellblade_rules(owners)[:1]:
        return spellblade_effect(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
        )
    return None


__all__ = [
    "NO_SIBLING",
    "PAIR_INTERPRETER",
    "SPELLBLADE_BREAKDOWN_PREFIX",
    "SPELLBLADE_COOLDOWN_FIELD",
    "SPELLBLADE_SUFFIX",
    "SpellbladeInterpretationError",
    "SpellbladePairInterpreter",
    "declares_self_heal",
    "resolve_slot",
    "spellblade_effect",
    "spellblade_rules",
]
