"""One interpreter per family per engine lane, and the gates over that map.

A declared behaviour is only worth something if some engine runs it.  This
package is where that is decided and, more importantly, where *not* deciding
it becomes visible: :func:`compilability_for` refuses to call an owner
compilable while any of its rules is receipt-only, and
:func:`reachability_report` names both a declaration no interpreter reaches
and an interpreter branch no declaration reaches (D-51).  Both directions
have live motivating cases, which is why neither is dropped as theoretical.

**Interpreters run at build time.**  A walk-lane interpreter emits
``KernelField``s — value-typed fields the kernel already understands — rather
than being called from inside the walk, so the dependency stays one-way:
``interpreters/`` may read ``survival/``'s vocabulary and nothing under
``survival/`` imports this package.  A source assertion in the test front
door pins that, because an interpreter that touched ``SurvivalAction`` and
was called from ``survival/transitions.py`` would close exactly the cycle the
leaf-ness of ``item_behavior`` does not cover.

There is one interpreter module per family and never a single dispatch file:
an eighteen-branch god module cannot carry eighteen test front doors, and the
derived front-door check (D-95) is what would notice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ..ability_spec import Authority
from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    Compilability,
    Compilable,
    EngineLane,
    KernelField,
    ReceiptOnly,
    RuleFamily,
    SUBJECT_AUTHORITY,
)
from ..item_behavior_catalog import behavior_rules, registry_entries, registry_owners
from ..trigger_stream import CAPABILITIES
from . import delta_amp


class InterpreterRegistryError(RuntimeError):
    """The (family, lane) map does not say what it claims to say."""


class Interpreter(Protocol):  # pylint: disable=too-few-public-methods
    """What every family's interpreter module exposes.

    ``compile`` is build-time only and returns value-typed fields; it is
    handed a :class:`~..item_behavior.BuildContext`, which carries a level, an
    owner and a data version and deliberately carries no walk state.
    """

    FAMILY: RuleFamily
    LANES: frozenset[EngineLane]

    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]:
        """Emit this rule's kernel fields for the lanes this interpreter serves."""


# Which lanes must be able to answer for each family, declared rather than
# inferred from what happens to be registered — otherwise "every family is
# interpreted" would be true of an empty registry.  Counter 4 is the size of
# the gap between this table and INTERPRETERS.
#
#   PAIR_ENGINE          the one-attacker damage model
#   RECEIPT_WALK         the coupled roster walk that serves receipts
#   COMPILED_SCORE_WALK  the compiled kernel the optimizer scores through
#   DEFENSE_RESOLVER     the defensive-effects build, before any walk
#   STAT_RESOLVER        the stat build, before any damage exists
_FAMILY_LANES: Mapping[RuleFamily, frozenset[EngineLane]] = {
    # Strike and pricing families produce damage, so all three damage lanes
    # owe an answer.
    RuleFamily.ON_HIT_STRIKE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.CHARGED_STRIKE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.SPELLBLADE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.CAST_PROC: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.PERIODIC: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.ACTIVE_CAST: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # A second target only exists where there is a roster to hit; the
    # compiled kernel prices one pair and has nowhere to put it.
    RuleFamily.SECONDARY_TARGET: frozenset(
        {EngineLane.PAIR_ENGINE, EngineLane.RECEIPT_WALK}
    ),
    RuleFamily.DELTA_AMP: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.RESISTANCE_SHRED: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.CRIT_PROFILE: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.DAMAGE_ROUTING: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # Defence families are built by the defensive resolver and then have to
    # survive both walks; the pair engine reads the resolver's output rather
    # than the rule.
    RuleFamily.OPENING_DEFENSE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.THRESHOLD_DEFENSE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.COMBAT_STATE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.REACTIVE: frozenset(
        {
            EngineLane.DEFENSE_RESOLVER,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    RuleFamily.SUSTAIN: frozenset(
        {
            EngineLane.PAIR_ENGINE,
            EngineLane.RECEIPT_WALK,
            EngineLane.COMPILED_SCORE_WALK,
        }
    ),
    # A derived stat is resolved before any damage exists, and the pair
    # engine reads the resolved stat block.
    RuleFamily.STAT_DERIVATION: frozenset(
        {EngineLane.STAT_RESOLVER, EngineLane.PAIR_ENGINE}
    ),
    # An ally packet is a roster fact; the pair engine has no ally.
    RuleFamily.ALLY_PACKET: frozenset(
        {EngineLane.RECEIPT_WALK, EngineLane.COMPILED_SCORE_WALK}
    ),
}


# The registry itself.  One entry per family per lane, filled by the slice
# that migrates it; every remaining gap is counted by the frontier's counter
# 4 rather than being an absence nobody measures.  ``delta_amp`` serves the
# pair engine only — H5 is descoped, so no amp is compilable, and the
# receipt-walk half arrives with the amps the coupled walk owns.
INTERPRETERS: Mapping[tuple[RuleFamily, EngineLane], Interpreter] = {
    (RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): delta_amp.PAIR_INTERPRETER,
}


def lanes_for(family: RuleFamily) -> frozenset[EngineLane]:
    """The lanes that owe *family* an interpreter."""
    lanes = _FAMILY_LANES.get(family)
    if lanes is None:
        raise InterpreterRegistryError(
            f"{family.value} declares no lanes; every family says which engines "
            "have to answer for it"
        )
    return lanes


def declared_pairs() -> frozenset[tuple[RuleFamily, EngineLane]]:
    """Every (family, lane) an interpreter is owed for."""
    return frozenset(
        (family, lane) for family in RuleFamily for lane in lanes_for(family)
    )


def uninterpreted_pairs() -> tuple[tuple[RuleFamily, EngineLane], ...]:
    """Counter 4's population: declared pairs with no registered interpreter."""
    return tuple(
        sorted(
            (pair for pair in declared_pairs() if pair not in INTERPRETERS),
            key=lambda pair: (pair[0].value, pair[1].value),
        )
    )


def compilability_for(owner: str) -> Compilability:
    """One owner's compiled-lane answer, folded from its rules (D-43).

    ``ReceiptOnly`` wins and its reasons concatenate in declaration order;
    ``Compilable`` only when every rule is.  An owner the registries know but
    no rule declares is **not** compilable: its behaviour is still engine
    code, so claiming the kernel can represent it would be a promise made by
    an absence.  An owner no registry knows has nothing to represent and is
    compilable.

    This is the successor to ``COMPILED_WALK_UNREPRESENTABLE_ITEMS`` — a
    per-item question needs a per-item answer, which is why the fold lives
    here rather than being left to each caller.
    """
    rules = behavior_rules(owner)
    if not rules:
        if registry_entries(owner):
            return ReceiptOnly(
                f"{owner}: the registry declares behaviour that no BehaviorRule "
                "models yet, so the compiled kernel has nothing to represent it "
                "with (Phase 3 migration frontier)"
            )
        return Compilable()
    reasons = [
        rule.compilability.reason
        for rule in rules
        if isinstance(rule.compilability, ReceiptOnly)
    ]
    if reasons:
        return ReceiptOnly("; ".join(reasons))
    return Compilable()


@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    """D-51's two directions as data.

    ``unreached_declarations`` are rules whose (family, lane) no interpreter
    serves; ``orphan_branches`` are registered interpreters no declaration
    reaches.  Empty tuples are the pass condition, and both halves are real:
    one branch exists today that no champion reaches, and one packet spelling
    would orphan its enum if it changed.
    """

    unreached_declarations: tuple[str, ...]
    orphan_branches: tuple[str, ...]


def reachability_report(owners: frozenset[str] | None = None) -> ReachabilityReport:
    """Walk both directions between declarations and interpreters."""
    subjects = registry_owners() if owners is None else owners
    unreached: list[str] = []
    reached: set[tuple[RuleFamily, EngineLane]] = set()
    for owner in sorted(subjects):
        for rule in behavior_rules(owner):
            for lane in lanes_for(rule.family):
                pair = (rule.family, lane)
                if pair in INTERPRETERS:
                    reached.add(pair)
                else:
                    unreached.append(
                        f"{rule.mechanic_id} declares {rule.family.value} and no "
                        f"interpreter serves lane {lane.value}"
                    )
    orphans = [
        f"{family.value}/{lane.value} is registered and no declaration reaches it"
        for family, lane in sorted(
            INTERPRETERS, key=lambda pair: (pair[0].value, pair[1].value)
        )
        if (family, lane) not in reached
    ]
    return ReachabilityReport(
        unreached_declarations=tuple(unreached), orphan_branches=tuple(orphans)
    )


def _validate_registry_keys() -> tuple[str, ...]:
    """Every registration's key agrees with the interpreter's own declaration."""
    failures: list[str] = []
    for (family, lane), interpreter in INTERPRETERS.items():
        if getattr(interpreter, "FAMILY", None) is not family:
            failures.append(
                f"{family.value}/{lane.value} is registered under a family its "
                "interpreter does not claim"
            )
        if lane not in getattr(interpreter, "LANES", frozenset()):
            failures.append(
                f"{family.value}/{lane.value} is registered on a lane its "
                "interpreter does not serve"
            )
        if lane not in lanes_for(family):
            failures.append(
                f"{family.value} declares no {lane.value} lane, so an "
                "interpreter registered there can never be reached"
            )
    return tuple(failures)


def _validate_authority_agreement(owners: frozenset[str]) -> tuple[str, ...]:
    """A rule's subject may not contradict its mechanic's declared authority.

    A roster-scoped subject on a ``PAIR_ONLY`` mechanic is the incident's own
    shape: the engine that owns the number cannot see the input the rule
    reads.  A rule with a roster-scoped subject and no capability at all is
    the same failure with the declaration missing entirely.
    """
    failures: list[str] = []
    for owner in sorted(owners):
        for rule in behavior_rules(owner):
            subject = getattr(rule.payload, "subject", None)
            if subject is None:
                continue
            allowed = SUBJECT_AUTHORITY[subject]
            capability = CAPABILITIES.get(rule.mechanic_id)
            if capability is None:
                if allowed != frozenset(Authority):
                    failures.append(
                        f"{rule.mechanic_id} acts on {subject.value} but declares "
                        "no MechanicCapability, so no engine has claimed its "
                        "roster inputs"
                    )
                continue
            if capability.authority not in allowed:
                failures.append(
                    f"{rule.mechanic_id} acts on {subject.value} under authority "
                    f"{capability.authority.value}, which cannot see it"
                )
    return tuple(failures)


def validate_registrations() -> None:
    """Totality, authority agreement and no orphan branch — or raise."""
    owners = registry_owners()
    failures = list(_validate_registry_keys())
    failures.extend(_validate_authority_agreement(owners))
    failures.extend(reachability_report(owners).orphan_branches)
    if failures:
        raise InterpreterRegistryError("; ".join(failures))


validate_registrations()


__all__ = [
    "INTERPRETERS",
    "Interpreter",
    "InterpreterRegistryError",
    "ReachabilityReport",
    "compilability_for",
    "declared_pairs",
    "lanes_for",
    "reachability_report",
    "uninterpreted_pairs",
    "validate_registrations",
]
