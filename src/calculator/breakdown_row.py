"""The two books one participant's published breakdown row is folded from.

``combat/breakdown`` is one row per participant, and three producers fill
it. ``timeline.records.Ledgers.empty`` opens the ledger half with its
default factory, so every row in that book carries the identity triple, the
running total and the per-source map from the moment it exists, and
``program.views.breakdown`` writes the same five on the published side.
``program.views.survival.survival_leaves`` writes the survival half in one
straight-line pass, so every row it returns carries each measure below.

``tests/test_row_stream_census.py`` measures the published join of the two,
77 rows, and finds every field here on all of them.

The survival measures are handed back exactly as the walk rounded them: a
published zero's type is part of what the coupled baseline pins, so nothing
here re-coerces one.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

from .event_row_field import required_field

__all__ = [
    "breakdown_champion",
    "breakdown_participant_id",
    "breakdown_sources",
    "breakdown_team",
    "breakdown_total_damage",
    "survival_effective_health",
    "survival_healing_received",
    "survival_healing_reduced",
    "survival_health_damage",
    "survival_shield_absorbed",
    "survival_support_shield_received",
]


_ledger = partial(
    required_field,
    kind="breakdown row",
    stamper="Ledgers.empty and program.views.breakdown",
)

_survival = partial(
    required_field,
    kind="survival row",
    stamper="program.views.survival.survival_leaves",
)


def breakdown_participant_id(row: Mapping[str, Any]) -> str:
    """Which participant this row totals."""
    return str(_ledger(row, "participant_id"))


def breakdown_team(row: Mapping[str, Any]) -> str:
    """Which side that participant fought on."""
    return str(_ledger(row, "team"))


def breakdown_champion(row: Mapping[str, Any]) -> str:
    """Which champion that participant played."""
    return str(_ledger(row, "champion"))


def breakdown_total_damage(row: Mapping[str, Any]) -> Any:
    """The mitigated damage this participant dealt before its own death."""
    return _ledger(row, "total_damage")


def breakdown_sources(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Its per-source totals, keyed the way ``source_key`` names them."""
    return _ledger(row, "sources")


def survival_health_damage(row: Mapping[str, Any]) -> Any:
    """Damage that reached health rather than a shield."""
    return _survival(row, "health_damage")


def survival_shield_absorbed(row: Mapping[str, Any]) -> Any:
    """Damage a shield took instead."""
    return _survival(row, "shield_absorbed")


def survival_effective_health(row: Mapping[str, Any]) -> Any:
    """How much damage this participant could still have taken."""
    return _survival(row, "effective_health")


def survival_healing_received(row: Mapping[str, Any]) -> Any:
    """Health restored to it, after any reduction."""
    return _survival(row, "healing_received")


def survival_healing_reduced(row: Mapping[str, Any]) -> Any:
    """Health a Grievous window kept it from restoring."""
    return _survival(row, "healing_reduced")


def survival_support_shield_received(row: Mapping[str, Any]) -> Any:
    """Shielding an ally granted it."""
    return _survival(row, "support_shield_received")
