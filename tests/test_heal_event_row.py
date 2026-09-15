"""Which heal-event keys may be read fail-closed, re-derived not asserted.

The same measurement the damage row gets, for the same reason: the claim
decides whether converting a site is a fix or a new crash, so it is taken
from the committed baseline on every run.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from src.calculator.heal_event_row import (
    HEAL_REQUIRED_FIELDS,
    healed_amount,
    healed_source,
    healed_time,
)

BASELINE = Path("scripts/golden_coupled_baseline.json")

ROW = {"time": 2.0, "amount": 45.0, "source": "lifesteal", "raw_amount": 60.0}


def _baseline_rows() -> list[dict]:
    """Every healing row the committed baseline holds."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for scenario in snapshot["coupled_scenarios"].values():
        rows += list((scenario.get("combat") or {}).get("healing_events") or ())
        for fight in (scenario.get("fights") or {}).values():
            rows += list(fight.get("self_healing_events") or ())
    return rows


class TestTheRequiredSetIsMeasured:
    def test_the_baseline_has_rows_to_measure(self):
        """A vacuous corpus would make every claim below pass by emptiness."""
        assert len(_baseline_rows()) > 1000

    def test_every_declared_required_key_is_on_every_row(self):
        rows = _baseline_rows()
        for field in HEAL_REQUIRED_FIELDS:
            absent = [row for row in rows if field not in row]
            assert absent == [], (
                f"{field} is declared required and is missing from "
                f"{len(absent)} of {len(rows)} rows"
            )

    def test_no_other_key_is_universal(self):
        """A key that HAS become universal belongs in the declared set."""
        rows = _baseline_rows()
        counts = Counter(key for row in rows for key in row)
        universal = {key for key, count in counts.items() if count == len(rows)}
        assert universal == set(HEAL_REQUIRED_FIELDS)

    def test_the_optional_keys_really_are_sometimes_absent(self):
        """Bulk-converting these is the trap the measurement exists to stop."""
        rows = _baseline_rows()
        counts = Counter(key for row in rows for key in row)
        for field in ("raw_amount", "overheal", "attacker", "kind"):
            assert 0 < counts[field] < len(rows), field


class TestTheReadersRefuseAnAbsentRequiredKey:
    @pytest.mark.parametrize(
        ("field", "reader"),
        [
            ("time", healed_time),
            ("amount", healed_amount),
            ("source", healed_source),
        ],
    )
    def test_each_reader_raises_and_names_its_field(self, field, reader):
        row = {key: value for key, value in ROW.items() if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    def test_a_stamped_row_reads_its_own_values(self):
        assert healed_time(ROW) == 2.0
        assert healed_amount(ROW) == 45.0
        assert healed_source(ROW) == "lifesteal"

    def test_a_fully_overhealed_packet_is_a_reading_and_not_an_absence(self):
        """``amount`` of zero is what a heal at full health really did."""
        assert healed_amount({**ROW, "amount": 0.0}) == 0.0


def test_the_accessors_do_not_collide_with_the_local_names_they_join():
    """Why these are ``healed_*`` and not ``heal_*``.

    ``heal_time`` and ``heal_amount`` are already local variables in the
    modules that read these rows. An import that shadows a local is how two
    earlier slices of this campaign broke, once for 230 tests, so the names
    are chosen to make that impossible rather than to be caught later.
    """
    import re

    names = {"healed_time", "healed_amount", "healed_source"}
    for module in Path("src/calculator").rglob("*.py"):
        source = module.read_text(encoding="utf-8")
        for name in names:
            assert not re.search(rf"^\s*{name}\s*=", source, re.M), (
                f"{module} binds {name} as a local, which an import of the "
                "accessor would shadow"
            )
