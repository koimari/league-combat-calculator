"""What every ``pipeline.run_fight`` result carries, in either mode.

``run_fight`` answers with one ``dict`` whose membership depends on
``score_only``: the scoring fast path drops the display splits and the
one-pair shield outcome. The accessors below take the set both modes carry,
so a composition step may require them whichever mode produced its result,
and a reader wanting ``target_ending_health`` or a damage split still asks
with its own default because the scoring mode publishes neither.

``damage_events`` comes back as the engine's light ledger tuple when the
scoring fast path set ``damage_events_tuple``; the key is there either way,
and which shape it holds is the caller's to know.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any

from .event_row_field import required_field

__all__ = [
    "FIGHT_RESULT_REQUIRED_FIELDS",
    "result_breakdown",
    "result_cast_timeline",
    "result_control_events",
    "result_damage_events",
    "result_keystone",
    "result_keystone_state_events",
    "result_self_healing_events",
    "result_self_state_events",
    "result_timeline_coverage",
    "result_total_damage",
]

#: The keys a fight result carries whether or not it was scored only.
FIGHT_RESULT_REQUIRED_FIELDS = (
    "breakdown",
    "cast_timeline",
    "control_events",
    "damage_events",
    "keystone",
    "keystone_state_events",
    "self_healing_events",
    "self_state_events",
    "timeline_coverage",
    "total_damage",
)


_required = partial(required_field, kind="fight result", stamper="pipeline.run_fight")


def result_damage_events(  # sightline-ok: 1 - three row shapes, one key
    result: Mapping[str, Any],
) -> Sequence[Any]:
    """Every damage packet the fight priced, in engine order."""
    return _required(result, "damage_events")


def result_cast_timeline(result: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """Every cast the rotation placed, in cast order."""
    return _required(result, "cast_timeline")


def result_control_events(
    result: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    """Every crowd-control application the fight landed, in engine order."""
    return _required(result, "control_events")


def result_self_healing_events(
    result: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    """Every recovery the attacker paid itself."""
    return _required(result, "self_healing_events")


def result_self_state_events(
    result: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    """Every self-state packet a champion module authored for this fight."""
    return _required(result, "self_state_events")


def result_keystone_state_events(
    result: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    """Every self-state packet the selected keystone authored."""
    return _required(result, "keystone_state_events")


def result_breakdown(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Per-source damage totals, keyed the way ``source_key`` names them."""
    return _required(result, "breakdown")


def result_total_damage(result: Mapping[str, Any]) -> float:
    """The mitigated total this fight dealt."""
    return float(_required(result, "total_damage"))


def result_timeline_coverage(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """How much of this fight's timeline the engine certified exactly."""
    return _required(result, "timeline_coverage")


def result_keystone(result: Mapping[str, Any]) -> str:
    """Which keystone the fight ran with; empty names none."""
    return str(_required(result, "keystone"))
