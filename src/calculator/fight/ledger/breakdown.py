"""One damage source's breakdown row: what it carries, and which stream it rides.

``state.breakdown`` is keyed by source and every step of a fight writes its
own rows into it as dict literals, so what a row carries depends on what
produced it rather than on one schema. That is measured, not assumed: one
timed fight per registered champion (the probe
``scripts/internal_row_census.py`` states) produces 960 rows, and only
``name`` is on all of them.

``total_damage`` and ``damage_type`` are on 958 of the 960. The two without
them are the stack-state rows a champion publishes for display, which carry
``informational`` and price nothing. ``casts`` and ``total_raw`` are on the
686 an ability cast authored; ``damage_events`` on 781 and ``event_phase``
on 777, the rows whose producer authored an event list; ``count`` and
``damage_per_hit`` on the auto-attack rows alone.

So every reader below is optional and answers ``None`` where no producer
stamped the field. A caller states for itself what a source with no such
reading contributes, instead of each one spelling a zero that would also
hide a producer that broke.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from ...event_row_field import optional_field


def _is_auto_stream_key(key: str) -> bool:
    """Whether a breakdown key belongs to the auto-attack damage stream.
    The stream and champion riders on it (Corki's true-damage instance) share
    the ``auto_attacks`` prefix; on-hit, spellblade and Fiendhunter rows ride
    the swings too."""
    return (
        key.startswith(("auto_attacks", "on_hit_", "spellblade_"))
        or key == "fiendhunter_true_damage"
    )


def source_total_damage(row: Mapping[str, Any]) -> float | None:
    """The mitigated damage this source dealt; ``None`` from an informational row."""
    return optional_field(row, "total_damage", float)


def source_damage_type(row: Mapping[str, Any]) -> str | None:
    """Which resistance its damage met; ``None`` from the same rows."""
    return optional_field(row, "damage_type", str)


def source_casts(row: Mapping[str, Any]) -> int | None:
    """How many casts authored it; ``None`` from a row no cast authored."""
    return optional_field(row, "casts", int)


def source_total_raw(row: Mapping[str, Any]) -> float | None:
    """Its pre-mitigation total; ``None`` from a row no cast authored."""
    return optional_field(row, "total_raw", float)


def source_damage_events(row: Mapping[str, Any]) -> Sequence[Any] | None:
    """The packets it authored, as its producer left them; ``None`` where none."""
    return row.get("damage_events")


def source_event_phase(row: Mapping[str, Any]) -> str | None:
    """Which phase its packets sort into; ``None`` where none was stamped."""
    return optional_field(row, "event_phase", str)


def source_hit_count(row: Mapping[str, Any]) -> int | None:
    """How many swings it counts; ``None`` off the auto-attack stream."""
    return optional_field(row, "count", int)


def source_damage_per_hit(row: Mapping[str, Any]) -> float | None:
    """What one of those swings was worth; ``None`` off that stream."""
    return optional_field(row, "damage_per_hit", float)
