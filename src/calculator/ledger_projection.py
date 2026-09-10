"""Which narrowing of a pair fight's result its readers can still be served.

A score-only fight is allowed to return less than a full one: the damage
ledger may come back as positional 6-tuples instead of dict rows, and the
one-pair shield outcome may be skipped entirely.  Both narrowings are
**projections** of the same fight, and both are safe only while every reader
the fight arms can still answer its question off what the projection keeps.

Each clause is an :class:`AdequacyCondition` with a declared reader, the stat
fields it is derived from, and the reason it exists.  A projection declares
which conditions it **cannot** serve, and satisfaction is the question "does
this fight arm a reader my projection would starve".  A conjunction spelled
at the call sites would compute the same answer while naming no reader, so a
clause deleted by accident would price a heal at zero and say nothing.  Both
call sites read the answer from here and hold no clause of their own.

Three properties are asserted at import rather than reviewed:

* every condition has exactly one declaration and exactly one probe;
* the two projections' unserved sets cover every condition, and overlap on
  exactly :attr:`AdequacyCondition.TARGET_THRESHOLD_HEAL` — the one clause
  both gates read, which is now one function called twice rather than one
  sentence written twice;
* a probe that reads a champion stat reads it through
  :meth:`LedgerInputs.raw_stat`, which refuses any field the condition did
  not declare in ``requires_fields``.

This module is a leaf on purpose.  It imports the interpreters, the
capability projections and the rune compiler the two gates already consumed,
and nothing else, so both the pipeline (above the engine) and the damage
engine itself can ask it without a cycle.  In particular it never imports the
champion healing registry: ``healing.self_heal_rule_owner`` hands it a typed
:class:`~.trigger_stream.ChampionSlotOwner` instead, which is also what makes
the champion half of the answer a declaration rather than a name set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from .ledger_adequacy import (
    _empowered_auto_owners,
    _execute_threshold_owners,
    _item_health_regen_owners,
    _item_self_heal_owners,
    _keystone_self_heal_owners,
    _lifesteal_owners,
    _omnivamp_owners,
    _ordered_interaction_owners,
    _pair_outcome_owners,
    _raw_row_stream_owners,
    _saturating_omnivamp_owners,
    _self_heal_rule_owners,
    _self_shield_proc_owners,
    _threshold_heal_owners,
)
from .ledger_declarations import (
    _DECLARATIONS,
    DECLARATIONS,
    AdequacyCondition,
    LedgerDemand,
)
from .ledger_inputs import LedgerInputs, ResultProjection, ShieldOutcomeInputs
from .trigger_stream import MechanicOwner

_LEDGER_PROBES: Mapping[
    AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]
] = MappingProxyType(
    {
        AdequacyCondition.TARGET_THRESHOLD_HEAL: _threshold_heal_owners,
        AdequacyCondition.CHAMPION_SELF_HEAL_RULE: _self_heal_rule_owners,
        AdequacyCondition.ITEM_SELF_HEAL_PACKETS: _item_self_heal_owners,
        AdequacyCondition.ITEM_HEALTH_REGEN: _item_health_regen_owners,
        AdequacyCondition.LIFESTEAL_STAT: _lifesteal_owners,
        AdequacyCondition.OMNIVAMP_STAT: _omnivamp_owners,
        AdequacyCondition.SATURATING_OMNIVAMP: _saturating_omnivamp_owners,
        AdequacyCondition.KEYSTONE_SELF_HEAL: _keystone_self_heal_owners,
        AdequacyCondition.EMPOWERED_BASIC_ATTACK: _empowered_auto_owners,
        AdequacyCondition.RAW_ROW_STREAM_HOLDER: _raw_row_stream_owners,
        AdequacyCondition.EXECUTE_THRESHOLD_STAMP: _execute_threshold_owners,
        AdequacyCondition.ORDERED_INTERACTION_METADATA: _ordered_interaction_owners,
        AdequacyCondition.SELF_SHIELD_PROC: _self_shield_proc_owners,
    }
)

_SHIELD_PROBES: Mapping[
    AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]
] = MappingProxyType(
    {
        AdequacyCondition.TARGET_THRESHOLD_HEAL: _threshold_heal_owners,
        AdequacyCondition.PAIR_OUTCOME_STREAM: _pair_outcome_owners,
    }
)

# Declaration order is evaluation order, so a caller that stops at the first
# demand always does the same work in the same order.
LEDGER_CONDITIONS: tuple[AdequacyCondition, ...] = tuple(_LEDGER_PROBES)
SHIELD_OUTCOME_CONDITIONS: tuple[AdequacyCondition, ...] = tuple(_SHIELD_PROBES)

_UNSERVED: Mapping[ResultProjection, frozenset[AdequacyCondition]] = MappingProxyType(
    {
        ResultProjection.LIGHT_TUPLE_LEDGER: frozenset(LEDGER_CONDITIONS),
        ResultProjection.DICT_ROW_LEDGER: frozenset(),
        ResultProjection.SKIPPED_SHIELD_OUTCOME: frozenset(SHIELD_OUTCOME_CONDITIONS),
        ResultProjection.RESOLVED_SHIELD_OUTCOME: frozenset(),
    }
)


class ProjectionRegistryError(RuntimeError):
    """A projection or condition declaration is structurally invalid."""


def _validate_declarations() -> None:
    """Structural cross-check of this module's four tables, at import.

    Four claims, each of which a later edit could break silently: every
    condition is declared exactly once; every condition has exactly one
    probe across the two gates; the two gates' unserved sets cover the enum
    and overlap on exactly the shared clause; and that shared clause is
    literally one function object in both registries rather than two
    functions that happen to agree today.
    """
    if len(DECLARATIONS) != len(_DECLARATIONS):
        raise ProjectionRegistryError("two declarations name one condition")
    missing = set(AdequacyCondition) - set(DECLARATIONS)
    if missing:
        raise ProjectionRegistryError(
            "undeclared adequacy conditions: "
            + ", ".join(sorted(condition.value for condition in missing))
        )
    if set(_UNSERVED) != set(ResultProjection):
        raise ProjectionRegistryError("a projection declares no unserved set")
    probed = frozenset(LEDGER_CONDITIONS) | frozenset(SHIELD_OUTCOME_CONDITIONS)
    if probed != set(AdequacyCondition):
        raise ProjectionRegistryError(
            "every condition needs a probe on the gate that reads it"
        )
    shared = frozenset(LEDGER_CONDITIONS) & frozenset(SHIELD_OUTCOME_CONDITIONS)
    if shared != {AdequacyCondition.TARGET_THRESHOLD_HEAL}:
        raise ProjectionRegistryError(
            "the two gates share exactly the threshold-heal clause; "
            f"they now share {sorted(condition.value for condition in shared)}"
        )
    for condition in shared:
        if _LEDGER_PROBES[condition] is not _SHIELD_PROBES[condition]:
            raise ProjectionRegistryError(
                f"{condition.value} is read by two functions, not one; a "
                "mirrored clause is a clause that can diverge"
            )


_validate_declarations()


def unserved_conditions(
    projection: ResultProjection,
) -> frozenset[AdequacyCondition]:
    """The conditions ``projection`` cannot answer for its readers."""
    return _UNSERVED[projection]


def _demands(
    conditions: Sequence[AdequacyCondition],
    probes: Mapping[AdequacyCondition, Callable[[Any], tuple[MechanicOwner, ...]]],
    inputs: Any,
    *,
    stop_at_first: bool,
) -> tuple[LedgerDemand, ...]:
    """Every reader this fight arms among ``conditions``, in declared order."""
    found: list[LedgerDemand] = []
    for condition in conditions:
        declaration = DECLARATIONS[condition]
        found.extend(
            LedgerDemand(
                condition=condition,
                owner=owner,
                reader=declaration.reader,
                reason=declaration.reason,
            )
            for owner in probes[condition](inputs)
        )
        if found and stop_at_first:
            break
    return tuple(found)


def ledger_demands(inputs: LedgerInputs) -> tuple[LedgerDemand, ...]:
    """Every damage-ledger reader this fight arms, as named receipts."""
    return _demands(LEDGER_CONDITIONS, _LEDGER_PROBES, inputs, stop_at_first=False)


def shield_outcome_demands(inputs: ShieldOutcomeInputs) -> tuple[LedgerDemand, ...]:
    """Every shield-outcome reader this fight arms, as named receipts."""
    return _demands(
        SHIELD_OUTCOME_CONDITIONS, _SHIELD_PROBES, inputs, stop_at_first=False
    )


def ledger_projection(inputs: LedgerInputs) -> ResultProjection:
    """The narrowest damage-ledger shape that still serves every reader.

    Stops at the first demand: one starved reader settles the projection.
    """
    starved = _demands(LEDGER_CONDITIONS, _LEDGER_PROBES, inputs, stop_at_first=True)
    if starved:
        return ResultProjection.DICT_ROW_LEDGER
    return ResultProjection.LIGHT_TUPLE_LEDGER


def shield_outcome_projection(inputs: ShieldOutcomeInputs) -> ResultProjection:
    """Whether the one-pair shield outcome may be skipped for this fight."""
    starved = _demands(
        SHIELD_OUTCOME_CONDITIONS, _SHIELD_PROBES, inputs, stop_at_first=True
    )
    if starved:
        return ResultProjection.RESOLVED_SHIELD_OUTCOME
    return ResultProjection.SKIPPED_SHIELD_OUTCOME


__all__ = [
    "LEDGER_CONDITIONS",
    "SHIELD_OUTCOME_CONDITIONS",
    "ProjectionRegistryError",
    "ledger_demands",
    "ledger_projection",
    "shield_outcome_demands",
    "shield_outcome_projection",
    "unserved_conditions",
]
