"""One damage source's breakdown row: what it carries, and which stream it rides.

``state.breakdown`` is keyed by source and every step of a fight writes its
own rows into it as dict literals, so what a row carries depends on what
produced it rather than on one schema. That is measured, not asserted:
``scripts/internal_row_census.py`` walks one timed fight per registered
champion and ``docs/receipts/internal-row-census.json`` holds how many of
its ``breakdown`` rows carry each key. Only ``name`` carries on all of
them, so every reader below is optional and answers ``None`` where no
producer stamped the field, and none of them may become a required read.

A caller states for itself what a source with no such reading contributes,
instead of each one spelling a zero that would also hide a producer that
broke. ``tests/test_ledger_breakdown_row.py`` holds both halves of that
against the census: which fields are optional, and the one stamp no reader
accepts, a ``total_damage`` that is not a number.
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
    """The mitigated damage this source dealt; ``None`` from an informational
    row.  A stamp that is not a number is refused by name rather than
    coerced: ``float(True)`` is ``1.0``, which would price a broken row at a
    point of damage, and ``float("x")`` raises naming neither row nor key."""
    if source_total_damage_is_malformed(row):
        raise ValueError(
            f"a breakdown row stamped total_damage={row['total_damage']!r}; "
            "every fight step that prices a row computes that total "
            f"arithmetically, so this row ({sorted(row)}) came from a "
            "producer that broke"
        )
    return optional_field(row, "total_damage", float)


def source_total_damage_is_malformed(row: Mapping[str, Any]) -> bool:
    """Whether the row stamped a total :func:`source_total_damage` refuses.
    The question a caller that withholds its own item asks first, so a
    producer break costs that item and not the whole request."""
    if "total_damage" not in row:
        return False
    value = row["total_damage"]
    return isinstance(value, bool) or not isinstance(value, (int, float))


def source_damage_type(row: Mapping[str, Any]) -> str | None:
    """Which resistance its damage met; ``None`` from the same rows."""
    return optional_field(row, "damage_type", str)


def source_casts(row: Mapping[str, Any]) -> int | None:
    """How many casts authored it; ``None`` from a row no cast authored."""
    return optional_field(row, "casts", int)


def source_total_raw(row: Mapping[str, Any]) -> float | None:
    """Its pre-mitigation total; ``None`` from a row no cast authored."""
    return optional_field(row, "total_raw", float)


def source_damage_events(  # sightline-ok: 1 - the packet shapes a producer may author
    row: Mapping[str, Any],
) -> Sequence[Any] | None:
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
