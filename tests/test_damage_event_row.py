"""Which damage-event keys may be read fail-closed, re-derived not asserted.

The module under test claims four keys are on every damage event and the
rest are legitimately optional. That claim decides whether a conversion of
a given site is a fix or a new crash, so it is measured here rather than
trusted: from the committed coupled baseline, and from
``docs/receipts/internal-row-census.json`` for the keys publication drops.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.calculator.damage_event_row import (
    REQUIRED_FIELDS,
    event_cc_duration,
    event_damage,
    event_damage_type,
    event_execute_threshold_ratio,
    event_phase,
    event_precision,
    event_raw_damage,
    event_source,
    event_time,
)

BASELINE = Path("scripts/golden_coupled_baseline.json")
INTERNAL_CENSUS = Path("docs/receipts/internal-row-census.json")

#: Every optional reader, the key it takes and a stamp of the shape a
#: producer writes.  Each key is measured below before it is read here.
OPTIONAL_READERS = (
    (event_raw_damage, "raw_damage", 180.0),
    (event_precision, "event_precision", "exact"),
    (event_execute_threshold_ratio, "execute_threshold_ratio", 0.2),
    (event_phase, "phase", "ability"),
    (event_cc_duration, "cc_duration", 1.25),
)

ROW = {
    "time": 4.5,
    "damage": 120.5,
    "damage_type": "physical",
    "source": "auto_attacks",
    "raw_damage": 180.0,
}


def _baseline_rows() -> list[dict]:
    """Every damage and combat event row the committed baseline holds."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for scenario in snapshot["coupled_scenarios"].values():
        rows += list((scenario.get("combat") or {}).get("events") or ())
        for fight in (scenario.get("fights") or {}).values():
            rows += list(fight.get("damage_events") or ())
    return rows


class TestTheRequiredSetIsMeasured:
    """The split is evidence, and it is re-derived on every run."""

    def test_the_baseline_has_rows_to_measure(self):
        """A vacuous corpus would make every claim below pass by emptiness."""
        assert len(_baseline_rows()) > 2000

    def test_every_declared_required_key_is_on_every_row(self):
        rows = _baseline_rows()
        for field in REQUIRED_FIELDS:
            absent = [row for row in rows if field not in row]
            assert absent == [], (
                f"{field} is declared required and is missing from "
                f"{len(absent)} of {len(rows)} rows"
            )

    def test_no_other_key_is_universal(self):
        """The reverse: a key that IS universal belongs in the declared set.

        Without this the module could under-claim forever, leaving a
        fail-closed read available and unused.
        """
        rows = _baseline_rows()
        counts = Counter(key for row in rows for key in row)
        universal = {key for key, count in counts.items() if count == len(rows)}
        assert universal == set(REQUIRED_FIELDS)

    def test_the_optional_keys_really_are_sometimes_absent(self):
        """Named because bulk-converting these is the trap this module exists
        to stop: they are on about two thirds of rows, not all."""
        rows = _baseline_rows()
        counts = Counter(key for row in rows for key in row)
        for field in (
            "raw_damage",
            "sequence",
            "attacker",
            "phase",
            "event_precision",
            "cc_duration",
        ):
            assert 0 < counts[field] < len(rows), field

    def test_the_execute_ratio_is_measured_where_it_survives(self):
        """No published row carries it, so the published corpus cannot say
        whether it is optional; the internal census walks the rows the
        engine reads and it is on a handful of them."""
        counts = Counter(key for row in _baseline_rows() for key in row)
        assert counts["execute_threshold_ratio"] == 0
        census = json.loads(INTERNAL_CENSUS.read_text(encoding="utf-8"))
        stream = census["streams"]["damage_events"]
        assert 0 < stream["keys"]["execute_threshold_ratio"] < stream["rows"]

    def test_the_packets_a_breakdown_row_authors_are_a_third_population(self):
        """The required set is licensed for the streams above, and the
        packets a breakdown row carries are not one of them: ``source`` is
        not on all of those, so ``event_source`` may not read one."""
        census = json.loads(INTERNAL_CENSUS.read_text(encoding="utf-8"))
        authored = census["streams"]["breakdown_damage_events"]
        assert authored["rows"] > 1000
        assert "source" not in authored["universal"]
        assert "sequence" not in authored["universal"]


class TestTheOptionalReadersAnswerNoneRatherThanASubstitute:
    """The optional half: a caller branches on ``None``, so a reader that
    substituted anything would hide the absence the corpus above measures."""

    @pytest.mark.parametrize(
        ("reader", "key", "stamp"),
        OPTIONAL_READERS,
        ids=[key for _reader, key, _stamp in OPTIONAL_READERS],
    )
    def test_a_stamped_field_reads_back_as_itself(self, reader, key, stamp):
        assert reader({**ROW, key: stamp}) == stamp

    @pytest.mark.parametrize(
        ("reader", "key", "stamp"),
        OPTIONAL_READERS,
        ids=[key for _reader, key, _stamp in OPTIONAL_READERS],
    )
    def test_an_unstamped_field_reads_as_none(self, reader, key, stamp):
        assert (
            reader({name: value for name, value in ROW.items() if name != key}) is None
        )


class TestTheReadersRefuseAnAbsentRequiredKey:
    @pytest.mark.parametrize(
        ("field", "reader"),
        [
            ("time", event_time),
            ("damage", event_damage),
            ("damage_type", event_damage_type),
            ("source", event_source),
        ],
    )
    def test_each_reader_raises_and_names_its_field(self, field, reader):
        row = {key: value for key, value in ROW.items() if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    def test_a_stamped_row_reads_its_own_values(self):
        assert event_time(ROW) == 4.5
        assert event_damage(ROW) == 120.5
        assert event_damage_type(ROW) == "physical"
        assert event_source(ROW) == "auto_attacks"

    @pytest.mark.parametrize("field", ["time", "damage"])
    def test_zero_is_a_reading_and_not_an_absence(self, field):
        """Both defaults this replaces were ``0.0``, and both are real values:
        the fight's own origin, and a packet fully absorbed."""
        reader = {"time": event_time, "damage": event_damage}[field]
        assert reader({**ROW, field: 0.0}) == 0.0
