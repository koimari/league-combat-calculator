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


def _active_fields(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """One active's compiled numbers for *lane*.

    The lane is the only thing that varies between the two interpreters
    below.  Sharing the body rather than spelling it twice is what makes
    "the walk reads the same declaration the pair engine reads" a property
    of the tree instead of a claim two functions could drift out of.

    Compiling the formula here is what makes a missing registry key or a
    basis with no reading surface fail when the build is made rather than on
    whichever event first asks for the number.
    """
    payload = _payload(rule)
    damage_formula.compile_formula(payload.formula, ctx)
    return (
        KernelField(
            name=ACTIVE_COOLDOWN_FIELD,
            value=resolve(payload.cooldown, ctx.level),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


class ActiveCastPairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``active_cast`` family.

    Its number is a **preview** since this family retired: every rule below
    declares ``ViewTag.THEORETICAL`` on its pair lane and
    ``damage._add_item_active_damage`` stamps ``pair_preview_of`` on the row
    it authors, so the honest one-attacker figure stays in the pair fight's
    own receipt and leaves every total the roster composes.
    """

    FAMILY = RuleFamily.ACTIVE_CAST
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This active's numbers, resolved for the one-attacker engine."""
        return _active_fields(rule, ctx, EngineLane.PAIR_ENGINE)


class ActiveCastWalkInterpreter:  # pylint: disable=too-few-public-methods
    """The receipt walk's answer for the ``active_cast`` family.

    The half that retires ``active_cast/receipt_walk`` (umbrella
    Amendment F's act, in the lane Amendment K rules and with the whole shape
    Amendment L, Ruling 1 requires).  Before it, the coupled walk consumed
    this family as ``participant_timeline._pair_run_fight``'s already-priced
    rows — the pair engine's mitigation against the pair engine's target —
    which is what the deferral row said in its own words.  Now the pair row
    is a declaration and no price: the walk mitigates the declared magnitude
    itself, at the resistance that packet met, through
    ``survival.pricing.price_declared_packet``.

    It compiles the same fields the pair interpreter does, stamped with its
    own lane.  Two lanes reading one declaration is the shape D-60 asks for;
    two lanes computing one number from two bodies is the shape it forbids.
    """

    FAMILY = RuleFamily.ACTIVE_CAST
    LANES = frozenset({EngineLane.RECEIPT_WALK})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """This active's numbers, resolved for the coupled roster walk."""
        return _active_fields(rule, ctx, EngineLane.RECEIPT_WALK)


PAIR_INTERPRETER = ActiveCastPairInterpreter()
WALK_INTERPRETER = ActiveCastWalkInterpreter()


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


def active_mechanic_id(owner: str) -> str:
    """*owner*'s active mechanic id, or a stop.

    What the pair engine needs to stamp the row it authors with the mechanic
    that row previews: ``damage._add_item_active_damage`` walks
    :class:`~..item_effects.DamageSource` rows, which carry an item name and
    no rule id, and reading the id back off the declaration here is what
    keeps the stamp from being a second spelling of the mechanic slug inside
    the engine.

    A stop rather than a default, for rule 5's reason one layer up: an
    unstamped active row would keep the pair engine's number in every roster
    total *and* leave the walk pricing the declaration, which is the double
    count this family's retirement exists to make unrepresentable.
    """
    rules = active_rules([owner])
    if not rules:
        raise ActiveCastInterpretationError(
            f"{owner} authors an item active and declares no active_cast rule, "
            "so its pair row has no mechanic to be a preview of"
        )
    return rules[0].mechanic_id


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
    "ActiveCastWalkInterpreter",
    "NO_INHERITED_LIFESTEAL",
    "PAIR_INTERPRETER",
    "WALK_INTERPRETER",
    "active_mechanic_id",
    "active_rules",
    "active_source",
    "active_sources",
]
