"""On-hit strikes, interpreted: a declared formula becomes the engine's row.

Eight items add damage to every on-hit application of a basic attack, and
until this module the shape of that damage lived as a six-branch formula
ladder inside the number registry.  The registry now owns the numbers and the
declaration owns the shape: :func:`per_hit_effects` reads what a build
declares and hands the fight engine the same ``PerHitEffect`` records it has
always consumed, built from the declaration rather than from a formula name.

Two facts the engine used to infer are now read off the declaration:

* whether the strike is re-priced as the target's health falls — it was
  ``formula == "current_hp"``, a string comparison that would have kept being
  true of one name while a second grew the same basis;
* whether an ability that carries the on-hit application pays this number or
  the item's ability-hit number instead.

Nothing here is memoized, deliberately and for the same reason the catalog is
not: ``refresh_item_effects()`` has to move the answer, and a build projection
cached across a patch-day refresh is the stale literal one layer up.  The
amp chain resolves its slots per fight on exactly this basis.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    EngineLane,
    KernelField,
    OnHitStrikeRule,
    RuleFamily,
)
from ..item_behavior_catalog import behavior_rules, build_context
from ..item_effects import PerHitEffect, damage_source
from . import damage_formula

# The field a strike rule compiles to for inspection: its term count.  A
# strike's *number* is not a build-time value — it depends on the target's
# live pools — so what the lane can compile is the formula's shape, and
# claiming otherwise would be a build-time number the mechanic cannot have.
STRIKE_TERM_COUNT_FIELD = "strike_terms"

# How an on-hit strike's breakdown row is named.  Presentation, kept beside
# the interpreter that builds the row rather than in the registry.
ON_HIT_SUFFIX = "on-hit"
ON_HIT_BREAKDOWN_PREFIX = "on_hit_"


class OnHitStrikeInterpretationError(ValueError):
    """A rule reached this interpreter that is not an on-hit strike."""


class OnHitStrikePairInterpreter:  # pylint: disable=too-few-public-methods
    """The pair engine's answer for the ``on_hit_strike`` family."""

    FAMILY = RuleFamily.ON_HIT_STRIKE
    LANES = frozenset({EngineLane.PAIR_ENGINE})

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """The shape a strike compiles to, and the proof its bases resolve.

        Compiling here is what makes a formula's *build-time* failures — a
        missing registry key, a basis with no reading — surface when the build
        is made rather than on whichever event first asks for the number.
        """
        payload = rule.payload
        if not isinstance(payload, OnHitStrikeRule):
            raise OnHitStrikeInterpretationError(
                f"{rule.mechanic_id} is not an on-hit strike rule"
            )
        damage_formula.compile_formula(payload.formula, ctx)
        return (
            KernelField(
                name=STRIKE_TERM_COUNT_FIELD,
                value=len(payload.formula.terms),
                lane=EngineLane.PAIR_ENGINE,
                rule_id=rule.mechanic_id,
            ),
        )


PAIR_INTERPRETER = OnHitStrikePairInterpreter()


def per_hit_effect(rule: BehaviorRule, ctx: BuildContext) -> PerHitEffect:
    """One declared strike as the record the fight engine consumes."""
    payload = rule.payload
    if not isinstance(payload, OnHitStrikeRule):
        raise OnHitStrikeInterpretationError(
            f"{rule.mechanic_id} is not an on-hit strike rule"
        )
    return PerHitEffect(
        damage_source(
            rule.owner,
            payload.formula.damage_class.value,
            damage_formula.compile_formula(payload.formula, ctx),
            suffix=ON_HIT_SUFFIX,
            breakdown_key=f"{ON_HIT_BREAKDOWN_PREFIX}{rule.owner}",
        ),
        tracks_current_health=damage_formula.reads_target_current_health(
            payload.formula
        ),
        superseded_by_ability_proc=payload.superseded_by_ability_proc,
    )


def strike_rules(owners: Sequence[str]) -> tuple[BehaviorRule, ...]:
    """Every on-hit strike *owners* declare, in build order."""
    return tuple(
        rule
        for owner in owners
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.ON_HIT_STRIKE
    )


def per_hit_effects(
    owners: Sequence[str],
    *,
    level: int,
    fight_duration_seconds: float,
    target_bonus_health: float,
    holder_is_melee: bool,
) -> tuple[PerHitEffect, ...]:
    """Every on-hit strike this build declares, in build order.

    Build order is the order the items were bought, which is the order the
    registry's own loop appended them in, which is the order the engine's
    breakdown rows come out in.  Preserving it is what makes the migration
    provably neutral rather than merely equivalent.

    The fight facts are the build context's required fields and are threaded
    through rather than defaulted, even though no on-hit coefficient reads
    one: a placeholder here would be exactly the silent default the context's
    requiredness exists to prevent, and a strike whose *rate* depended on the
    fight would be a different mechanic.
    """
    return tuple(
        per_hit_effect(
            rule,
            build_context(
                rule.owner,
                level,
                fight_duration_seconds=fight_duration_seconds,
                target_bonus_health=target_bonus_health,
                holder_is_melee=holder_is_melee,
            ),
        )
        for rule in strike_rules(owners)
    )


__all__ = [
    "ON_HIT_BREAKDOWN_PREFIX",
    "ON_HIT_SUFFIX",
    "STRIKE_TERM_COUNT_FIELD",
    "OnHitStrikeInterpretationError",
    "OnHitStrikePairInterpreter",
    "PAIR_INTERPRETER",
    "per_hit_effect",
    "per_hit_effects",
    "strike_rules",
]
