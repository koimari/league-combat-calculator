"""A declared sum of sourced shares, turned into the engine's raw formula.

Every strike family answers the same question — *how much* — and answered it,
until this module, with a ladder of formula names inside the number registry.
``"flat_bonus_ad_ap"`` meant something in exactly one function, and a reader
who wanted to know what a number was made of had to go and read that
function's branch.

:class:`~..item_behavior.DamageFormula` says it instead: a tuple of terms,
each a sourced coefficient times a named :class:`~..item_behavior.Basis`.
This module is the one place a term becomes arithmetic, so every strike family
shares one evaluator rather than each re-implementing "a share of the target's
current health".

**Coefficients resolve once, at build time.**  The closure the engine calls
per event closes over floats, never over references: the registries are read
when the build is compiled, exactly as the registry's own compilers read them,
so this migration costs no per-event dictionary lookups.  A range-split
coefficient resolves *both* rates at build time and the closure picks between
them, because the pair engine's ``DamageInputs`` is what knows whether the
holder is melee at the moment the number is wanted.

The fold order is the declaration's term order and the sum starts at zero.
That is load-bearing rather than stylistic: floating-point addition is not
associative, and the registry's compilers summed their terms in the order
their formula names spelled them.  A declaration whose terms are in that same
order therefore reproduces the same float, which is what lets this migration
claim no number moved rather than no number moved much.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..item_behavior import (
    AtLeast,
    Basis,
    BuildContext,
    DamageFormula,
    LevelSteppedRate,
    MeleeRangedSplit,
    NoFloor,
    NoScaling,
    Term,
    TimesMissingHealth,
    TimesValue,
)
from ..item_effects import DamageInputs
from ..value_ref import resolve

# What each basis reads, keyed by the enum member.  Every entry is a
# ``DamageInputs`` reading, which is what makes the union closed: a basis
# nothing can read is a member nobody may declare.
_STAT_BASES: Mapping[Basis, str] = {
    Basis.ABILITY_POWER: "ability_power",
    Basis.BASE_ATTACK_DAMAGE: "base_attack_damage",
    Basis.BONUS_ATTACK_DAMAGE: "bonus_attack_damage",
    Basis.TOTAL_ATTACK_DAMAGE: "attack_damage",
    Basis.LETHALITY: "lethality",
    Basis.HOLDER_MAX_HEALTH: "health",
    Basis.HOLDER_MAX_MANA: "max_mana",
    Basis.HOLDER_BONUS_HEALTH: "bonus_health",
}


class DamageFormulaError(ValueError):
    """A formula reached this evaluator with no arithmetic for one of its bases."""


def basis_value(basis: Basis, inputs: DamageInputs) -> float:
    """What *basis* is worth for one event.

    One branch per member, and the branches are grouped by where the number
    comes from: the holder's stat block, the target's pools, the holder's
    level, or the constant one that makes a flat term a term like any other.
    """
    stat = _STAT_BASES.get(basis)
    if stat is not None:
        return float(inputs.champion_stats.get(stat, 0.0))
    if basis is Basis.FLAT:
        return 1.0
    if basis is Basis.PER_LEVEL:
        return float(inputs.level)
    if basis is Basis.HOLDER_CRIT_FRACTION:
        return min(
            float(inputs.champion_stats.get("critical_strike_chance", 0.0)) / 100.0, 1.0
        )
    if basis is Basis.TARGET_MAX_HEALTH:
        return float(inputs.target_max_health)
    if basis is Basis.TARGET_CURRENT_HEALTH:
        return float(inputs.target_current_health)
    if basis is Basis.TARGET_MISSING_HEALTH:
        return max(0.0, float(inputs.target_max_health - inputs.target_current_health))
    raise DamageFormulaError(
        f"{basis.value} has no reading in DamageInputs; a new basis is a new "
        "branch here, never a silent zero"
    )


def _split_rates(coefficient: object, ctx: BuildContext) -> tuple[float, float]:
    """A reference or a range split as ``(melee, ranged)``, read at build time."""
    if isinstance(coefficient, MeleeRangedSplit):
        return (
            resolve(coefficient.melee, ctx.level),
            resolve(coefficient.ranged, ctx.level),
        )
    rate = resolve(coefficient, ctx.level)  # type: ignore[arg-type]
    return (rate, rate)


def _stepped_rates(stepped: LevelSteppedRate, ctx: BuildContext) -> tuple[float, float]:
    """A level-stepped rate's ``(melee, ranged)`` values at the build's level.

    Flat below the declared level and growing by one step per level from it
    upwards, counting the threshold level itself as the first step — which is
    the arithmetic the registry compiler wrote and the reason this is not a
    two-ended ramp.
    """
    threshold = int(resolve(stepped.from_level, ctx.level))
    bases = _split_rates(stepped.base, ctx)
    if ctx.level < threshold:
        return bases
    steps = ctx.level - threshold + 1
    per_level = _split_rates(stepped.per_level, ctx)
    return (bases[0] + per_level[0] * steps, bases[1] + per_level[1] * steps)


def _resolved_coefficient(term: Term, ctx: BuildContext) -> tuple[float, float]:
    """One term's ``(melee, ranged)`` rates; a single reference resolves twice."""
    if isinstance(term.coefficient, LevelSteppedRate):
        return _stepped_rates(term.coefficient, ctx)
    return _split_rates(term.coefficient, ctx)


# A zero-valued reading used only to prove every declared basis has one, at
# build time.  It is never handed to a formula's arithmetic.
_PROBE_INPUTS = DamageInputs(
    champion_stats={},
    level=1,
    is_melee=True,
    target_max_health=0.0,
    target_current_health=0.0,
)


def compile_formula(
    formula: DamageFormula, ctx: BuildContext
) -> Callable[[DamageInputs], float]:
    """The engine's raw-damage closure for one declared formula.

    The returned callable is the *only* thing that crosses into the fight
    loop, and it holds floats and enum members — no references, no registry,
    no declaration.  That is what keeps a per-event path free of the
    declaration layer's cost.
    """
    resolved: tuple[tuple[float, float, Basis], ...] = tuple(
        (*_resolved_coefficient(term, ctx), term.basis) for term in formula.terms
    )
    for _, _, basis in resolved:
        # Fail at build time, not on the first event: a basis with no reading
        # is a programming error and must not wait for a fight to surface.
        basis_value(basis, _PROBE_INPUTS)
    floor = formula.floor
    minimum = resolve(floor.value, ctx.level) if isinstance(floor, AtLeast) else None
    if minimum is None and not isinstance(floor, NoFloor):
        raise DamageFormulaError(
            f"{ctx.owner}: {type(floor).__name__} is not a declared floor shape"
        )
    factor = _scaling_factor(formula, ctx)
    missing_health_bonus = (
        resolve(formula.scaling.bonus_at_full_missing, ctx.level)
        if isinstance(formula.scaling, TimesMissingHealth)
        else None
    )

    def raw(inputs: DamageInputs) -> float:
        total = 0.0
        for melee_rate, ranged_rate, basis in resolved:
            rate = melee_rate if inputs.is_melee else ranged_rate
            total += rate * basis_value(basis, inputs)
        if factor is not None:
            total *= factor
        if missing_health_bonus is not None:
            missing = max(
                0.0, 1.0 - inputs.target_current_health / inputs.target_max_health
            )
            total *= 1.0 + missing_health_bonus * missing
        if minimum is None:
            return total
        return max(minimum, total)

    return raw


def _scaling_factor(formula: DamageFormula, ctx: BuildContext) -> float | None:
    """The factor a declared scaling multiplies the whole sum by.

    ``None`` for an unscaled formula, so the closure skips a multiplication it
    would otherwise perform against a 1.0 nobody declared — the sum has to
    reproduce the registry compiler's float exactly, and ``x * 1.0`` is only
    incidentally harmless.
    """
    scaling = formula.scaling
    if isinstance(scaling, (NoScaling, TimesMissingHealth)):
        # A missing-health factor is not a build-time number: it is read per
        # event from the target's live pools, so the closure computes it and
        # this function has nothing to hand back.
        return None
    if isinstance(scaling, TimesValue):
        return resolve(scaling.factor, ctx.level)
    raise DamageFormulaError(
        f"{ctx.owner}: {type(scaling).__name__} is not a declared scaling shape; "
        "a new member is a new branch here, never a silently unscaled sum"
    )


def reads_target_current_health(formula: DamageFormula) -> bool:
    """Whether any term of *formula* is a share of the target's live health,
    which the engine re-prices as health falls rather than once at build time.
    """
    if isinstance(formula.scaling, TimesMissingHealth):
        return True
    return any(term.basis is Basis.TARGET_CURRENT_HEALTH for term in formula.terms)


__all__ = [
    "DamageFormulaError",
    "basis_value",
    "compile_formula",
    "reads_target_current_health",
]
