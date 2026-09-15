"""Which damage-event keys may be read fail-closed, re-derived not asserted.

The module under test claims four keys are on every damage event and the
rest are legitimately optional. That claim decides whether an ER5 conversion
of a given site is a fix or a new crash, so it is measured here from the
committed coupled baseline rather than trusted.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.calculator.damage_event_row import (
    REQUIRED_FIELDS,
    event_damage,
    event_damage_type,
    event_source,
    event_time,
)

BASELINE = Path("scripts/golden_coupled_baseline.json")

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
        for field in ("raw_damage", "sequence", "attacker", "phase"):
            assert 0 < counts[field] < len(rows), field


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
