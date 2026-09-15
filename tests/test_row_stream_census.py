"""Which keys every row of each published stream carries, measured.

ER5's remaining tail is mostly ``row.get(key, <literal>)`` on published
rows, and whether converting one is a fix or a new crash depends entirely
on whether that stream stamps the key on every row. This is that table, and
it is re-derived from the committed coupled baseline on every run rather
than written down once.

The trap it exists to stop is POOLING. A first pass at the damage row
measured ``combat/events`` and ``fights/damage_events`` together, concluded
that only four keys were universal, and recorded that ``raw_damage`` sat on
1,706 of 2,458 rows. Both streams are internally consistent: ``raw_damage``
is on every ``combat/events`` row and on no fight row. Pooling two shapes
manufactures an optional field out of two required ones, and the conclusion
it invites, that some producer stamps inconsistently, is false.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

BASELINE = Path("scripts/golden_coupled_baseline.json")

#: ``stream -> (row count, the keys on EVERY row of it)``. Regenerate with
#: ``test_the_census_is_current`` when a producer starts or stops stamping
#: a field; that test prints the table it expected.
CENSUS: dict[str, tuple[int, tuple[str, ...]]] = {
    "combat/events": (
        1706,
        (
            "attacker",
            "damage",
            "damage_type",
            "event_id",
            "event_precision",
            "overkill",
            "pair_damage",
            "raw_damage",
            "sequence",
            "source",
            "target",
            "time",
        ),
    ),
    "combat/healing_events": (
        909,
        (
            "amount",
            "applied_amount",
            "attacker",
            "event_id",
            "healing_reduction_factor",
            "overheal",
            "raw_amount",
            "reduced_amount",
            "source",
            "temporary_health",
            "time",
        ),
    ),
    "combat/breakdown": (
        77,
        (
            "champion",
            "death_time",
            "effective_health",
            "healing_output",
            "healing_received",
            "healing_reduced",
            "health_damage",
            "incoming_damage",
            "outgoing_damage_before_death",
            "participant_id",
            "shield_absorbed",
            "sources",
            "support_shield_received",
            "support_value",
            "survived_window",
            "team",
            "total_damage",
        ),
    ),
    "combat/item_denial_receipts": (
        5,
        (
            "attacker",
            "event_id",
            "kind",
            "reason",
            "source",
            "target",
            "time",
        ),
    ),
    "combat/participants": (
        77,
        (
            "champion",
            "level",
            "participant_id",
            "survival",
            "team",
        ),
    ),
    "combat/support_events": (
        70,
        (
            "amount",
            "applied_amount",
            "attacker",
            "duration",
            "event_id",
            "kind",
            "raw_amount",
            "recipient",
            "reduced_amount",
            "source",
            "target",
            "target_policy",
            "target_scope",
            "target_selection_key",
            "time",
        ),
    ),
    "fights/cast_timeline": (
        207,
        (
            "cast_id",
            "name",
            "ordinal",
            "resource_after",
            "resource_before",
            "resource_cost",
            "resource_restored",
            "slot",
            "target_id",
            "time",
        ),
    ),
    "fights/damage_events": (752, ("damage", "damage_type", "phase", "source", "time")),
    "fights/self_healing_events": (252, ("amount", "kind", "source", "time")),
}


def _streams() -> dict[str, list[dict]]:
    """Every published row stream the committed baseline holds."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    streams: dict[str, list[dict]] = {}
    for scenario in snapshot["coupled_scenarios"].values():
        for key, value in (scenario.get("combat") or {}).items():
            if _is_row_list(value):
                streams.setdefault(f"combat/{key}", []).extend(value)
        for fight in (scenario.get("fights") or {}).values():
            for key, value in fight.items():
                if _is_row_list(value):
                    streams.setdefault(f"fights/{key}", []).extend(value)
    return streams


def _is_row_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(row, dict) for row in value)
    )


def _universal(rows: list[dict]) -> tuple[str, ...]:
    counts = Counter(key for row in rows for key in row)
    return tuple(sorted(key for key, count in counts.items() if count == len(rows)))


@pytest.mark.parametrize("stream", sorted(CENSUS))
def test_the_census_is_current(stream):
    """A producer that starts or stops stamping a field turns this red.

    Red here is not automatically a defect: a new optional field is normal.
    It is a prompt to re-read the row's module before any fail-closed reader
    is widened or narrowed on the strength of the old table.
    """
    rows = _streams().get(stream, [])
    expected_count, expected_keys = CENSUS[stream]
    assert len(rows) == expected_count, stream
    assert (
        _universal(rows) == expected_keys
    ), f"{stream}'s universal key set moved; measured {_universal(rows)}"


def test_every_published_row_stream_is_in_the_census():
    """A stream nobody measured is a stream nobody can safely convert."""
    assert set(_streams()) - set(CENSUS) == set()


def test_pooling_two_streams_manufactures_an_optional_field():
    """The permanent negative: the mistake this table exists to prevent.

    Asserted rather than described, so the reasoning cannot quietly rot back
    into the pooled reading that produced the wrong figure the first time.
    """
    streams = _streams()
    combat = streams["combat/events"]
    fights = streams["fights/damage_events"]
    assert "raw_damage" in _universal(combat)
    assert "raw_damage" not in _universal(fights)
    assert all("raw_damage" not in row for row in fights)
    # Pooled, a key that is required in one shape and absent from the other
    # reads as merely optional, which is the false conclusion.
    assert "raw_damage" not in _universal(combat + fights)
