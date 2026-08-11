"""Item actives, interpreted: a declared formula becomes the engine's row.

Six items deal damage when the player presses them, and until this module the
shape of that damage lived as a three-branch formula ladder inside the number
registry.  The registry now owns the numbers and the declaration owns the
shape: :func:`active_sources` reads what a build declares and hands the fight
engine the same :class:`~..item_effects.DamageSource` rows it has always
consumed.

The active is the one strike whose trigger is the *player* rather than an
event the fight produces, which is why the declaration carries a cooldown and
no trigger at all.  ``lifesteal_effectiveness`` is a declared absence rather
than a defaulted zero: an active that inherits no life steal and an active
that inherits it at zero effectiveness are two different claims about the
item, and only one of them is true of Ravenous Hydra's siblings.

Nothing here is memoized, for the same reason the catalog is not:
``refresh_item_effects()`` has to move the answer.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..item_behavior import (
    ActiveCastRule,
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import DamageSource, damage_source
from ..value_ref import resolve
from . import damage_formula

# The field an active compiles to for inspection: the seconds before the
# holder could press it again.  Unlike a strike's damage, a cooldown really is
# a build-time number, so this lane can compile it rather than only its shape.
ACTIVE_COOLDOWN_FIELD = "active_cooldown"

# How an active's breakdown row is named.  Presentation, kept beside the
# interpreter that builds the row rather than in the registry.
ACTIVE_SUFFIX = "active"
ACTIVE_BREAKDOWN_PREFIX = "active_"

# What an active with no declared life-steal inheritance hands the engine.
# The engine's own spelling for "no life-steal sibling is eligible"; it is
# written here, once, so the declaration can say *nothing* instead of saying
# zero.
NO_INHERITED_LIFESTEAL = 0.0


class ActiveCastInterpretationError(ValueError):
    """A rule reached this interpreter that is not an item active."""


def _payload(rule: BehaviorRule) -> ActiveCastRule:
    """*rule*'s active payload, or a stop."""
    payload = rule.payload
    if not isinstance(payload, ActiveCastRule):
        raise ActiveCastInterpretationError(f"{rule.mechanic_id} is not an active rule")
    return payload


class ActiveCastPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``active_cast`` family."""

    FAMILY = RuleFamily.ACTIVE_CAST
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The cooldown this active compiles to, and the proof its bases resolve.

        Compiling the formula here is what makes a missing registry key or a
        basis with no reading surface when the build is made rather than on
        whichever event first asks for the number.
        """
        payload = _payload(rule)
        damage_formula.compile_formula(payload.formula, ctx)
        return (
            KernelField(
                name=ACTIVE_COOLDOWN_FIELD,
                value=resolve(payload.cooldown, ctx.level),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            ),
        )


PAIR_INTERPRETER = ActiveCastPairInterpreter()


def active_source(rule: BehaviorRule, ctx: BuildContext) -> DamageSource:
    """One declared active as the row the fight engine consumes."""
    payload = _payload(rule)
    inherited = payload.lifesteal_effectiveness
    return damage_source(
        rule.owner,
        payload.formula.damage_class.value,
        damage_formula.compile_formula(payload.formula, ctx),
        suffix=ACTIVE_SUFFIX,
        breakdown_key=f"{ACTIVE_BREAKDOWN_PREFIX}{rule.owner}",
        lifesteal_effectiveness=(
            NO_INHERITED_LIFESTEAL
            if inherited is None
            else resolve(inherited, ctx.level)
        ),
    )


def active_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every active *owners* declare, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.ACTIVE_CAST
    )


def active_sources(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> tuple[DamageSource, ...]:
    """Every active this build declares, in build order.

    Build order is the order the items were bought, which is the order the
    registry's own loop appended them in, which is the order the engine's
    breakdown rows come out in.  Preserving it is what makes the migration
    provably neutral rather than merely equivalent.
    """
    return tuple(
        active_source(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
        )
        for rule in active_rules(owners)
    )


__all__ = [
    "ACTIVE_BREAKDOWN_PREFIX",
    "ACTIVE_COOLDOWN_FIELD",
    "ACTIVE_SUFFIX",
    "ActiveCastInterpretationError",
    "ActiveCastPairInterpreter",
    "NO_INHERITED_LIFESTEAL",
    "PAIR_INTERPRETER",
    "active_rules",
    "active_source",
    "active_sources",
]
