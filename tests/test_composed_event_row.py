"""Which composed-row keys may be read fail-closed, re-derived not asserted.

The module under test claims seven keys are on every row of a composed
roster book, and those books are in flight rather than published, so no
corpus of published rows licenses one of them by simple presence. What does
license them is HOW ``program.views.receipt`` publishes each: a field it
indexes is a field every row it was handed carried, and a field it publishes
from a plain read is one whose published null would have named the gap.

Both readings are re-derived below, against the committed coupled baseline
and against ``docs/receipts/internal-row-census.json``.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.calculator.composed_event_row import (
    COMPOSED_REQUIRED_FIELDS,
    row_attacker,
    row_damage,
    row_damage_type,
    row_raw_damage,
    row_sequence,
    row_source_key,
    row_target,
    row_time,
)

BASELINE = Path("scripts/golden_coupled_baseline.json")
INTERNAL = Path("docs/receipts/internal-row-census.json")

#: The publisher renames two fields on its way out, so a published name is
#: not always the in-flight one.
PUBLISHED_NAME = {"source_key": "source"}

ROW = {
    "time": 4.5,
    "damage": 120.5,
    "damage_type": "physical",
    "source_key": "auto_attacks",
    "sequence": 3,
    "attacker": "main",
    "target": "enemy1",
    "_event_id": "main:enemy1:7",
}

READERS = {
    "time": row_time,
    "damage": row_damage,
    "damage_type": row_damage_type,
    "source_key": row_source_key,
    "sequence": row_sequence,
    "attacker": row_attacker,
    "target": row_target,
}


def _published_rows() -> list[dict]:
    """``combat/events``: what the publisher made of the composed books."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    return [
        row
        for scenario in snapshot["coupled_scenarios"].values()
        for row in (scenario.get("combat") or {}).get("events") or ()
    ]


def _internal_universal() -> set[str]:
    """The engine's own ``damage_events`` shape, as the committed census has it."""
    census = json.loads(INTERNAL.read_text(encoding="utf-8"))
    return set(census["streams"]["damage_events"]["universal"])


class TestTheRequiredSetIsMeasured:
    def test_the_corpora_have_rows_to_measure(self):
        """A vacuous corpus would make every claim below pass by emptiness."""
        assert len(_published_rows()) > 1000
        census = json.loads(INTERNAL.read_text(encoding="utf-8"))
        assert census["streams"]["damage_events"]["rows"] > 1000

    def test_every_declared_key_reaches_publication_on_every_row(self):
        """The publisher's own reads are the license: it indexes four of
        these and guards ``sequence`` on ``is not None``, so a published row
        missing one could not have been built."""
        rows = _published_rows()
        for field in COMPOSED_REQUIRED_FIELDS:
            published = PUBLISHED_NAME.get(field, field)
            absent = [row for row in rows if published not in row]
            assert absent == [], (
                f"{field} is declared required and reaches publication on "
                f"only {len(rows) - len(absent)} of {len(rows)} rows"
            )

    def test_the_two_fields_published_from_a_plain_read_are_never_null(self):
        """``attacker`` and ``target`` are published with no guard, so a row
        that carried neither would publish a null rather than drop the key."""
        rows = _published_rows()
        for field in ("attacker", "target"):
            null = [row for row in rows if row.get(field) is None]
            assert null == [], f"{field} is null on {len(null)} of {len(rows)} rows"

    def test_the_engine_half_of_the_claim_is_the_internal_census(self):
        """The rows the engine hands the composition are the other producer,
        and the published stream spells ``source_key`` differently."""
        assert {"damage", "damage_type", "sequence", "source_key", "time"} <= (
            _internal_universal()
        )

    def test_no_other_published_key_is_universal_and_unclaimed(self):
        """A universal key left unclaimed is a fail-closed read going unused.

        Each survivor is published from its own default, which
        ``program/views/receipt.py`` states beside the read, so none of them
        speaks for the row in flight.
        """
        rows = _published_rows()
        counts = Counter(key for row in rows for key in row)
        universal = {key for key, count in counts.items() if count == len(rows)}
        claimed = {PUBLISHED_NAME.get(field, field) for field in READERS}
        assert universal - claimed == {
            "event_id",
            "event_precision",
            "overkill",
            "pair_damage",
            "raw_damage",
        }

    def test_the_composition_only_stamps_are_not_claimed(self):
        """``_event_id`` and its siblings are the composition's own, and the
        publisher guards every one, so they keep their own defaults."""
        assert not {"_event_id", "_sk", "ability_instance"} & set(
            COMPOSED_REQUIRED_FIELDS
        )


class TestTheReadersRefuseAnAbsentRequiredKey:
    @pytest.mark.parametrize(("field", "reader"), sorted(READERS.items()))
    def test_each_reader_raises_and_names_its_field(self, field, reader):
        row = {key: value for key, value in ROW.items() if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    def test_a_stamped_row_reads_its_own_values(self):
        assert row_time(ROW) == 4.5
        assert row_damage(ROW) == 120.5
        assert row_damage_type(ROW) == "physical"
        assert row_source_key(ROW) == "auto_attacks"
        assert row_sequence(ROW) == 3
        assert row_attacker(ROW) == "main"
        assert row_target(ROW) == "enemy1"

    def test_the_optional_reader_answers_none_rather_than_a_number(self):
        """``raw_damage`` is on about four fifths of published rows, so its
        absence is a real answer the caller has to state a reading for."""
        assert row_raw_damage(ROW) is None
        assert row_raw_damage({**ROW, "raw_damage": 0.0}) == 0.0
        assert row_raw_damage({**ROW, "raw_damage": 180.0}) == 180.0

    @pytest.mark.parametrize("field", ["time", "damage", "sequence"])
    def test_zero_is_a_reading_and_not_an_absence(self, field):
        """Each default this replaces was a zero, and each zero is a real
        value: the fight's own origin, a fully absorbed packet, and the first
        packet at a timestamp."""
        assert READERS[field]({**ROW, field: 0}) == 0
