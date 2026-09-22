"""Which breakdown-row keys may be read fail-closed, re-derived not asserted.

Two books fill one published row, so the claim is checked against the
published join in the committed coupled baseline and against each book's own
producer: the ledger half's default factory and the survival half's writer.
"""

import ast
import json
from pathlib import Path

import pytest

from src.calculator.breakdown_row import (
    breakdown_champion,
    breakdown_participant_id,
    breakdown_sources,
    breakdown_team,
    breakdown_total_damage,
    survival_effective_health,
    survival_healing_received,
    survival_healing_reduced,
    survival_health_damage,
    survival_shield_absorbed,
    survival_support_shield_received,
)
from src.calculator.timeline.records import Ledgers

BASELINE = Path("scripts/golden_coupled_baseline.json")
SURVIVAL_VIEW = Path("src/calculator/program/views/survival.py")

LEDGER_READERS = {
    "participant_id": breakdown_participant_id,
    "team": breakdown_team,
    "champion": breakdown_champion,
    "total_damage": breakdown_total_damage,
    "sources": breakdown_sources,
}

SURVIVAL_READERS = {
    "health_damage": survival_health_damage,
    "shield_absorbed": survival_shield_absorbed,
    "effective_health": survival_effective_health,
    "healing_received": survival_healing_received,
    "healing_reduced": survival_healing_reduced,
    "support_shield_received": survival_support_shield_received,
}

SURVIVAL_ROW = dict.fromkeys(SURVIVAL_READERS, 0.0)


def _published_rows() -> list[dict]:
    """Every ``combat/breakdown`` row the committed baseline holds."""
    snapshot = json.loads(BASELINE.read_text(encoding="utf-8"))
    return [
        row
        for scenario in snapshot["coupled_scenarios"].values()
        for row in (scenario.get("combat") or {}).get("breakdown") or ()
    ]


def _unconditional_measures() -> set[str]:
    """Every field the survival writer names outside any ``if``.

    Read off the writer rather than off a corpus, because that is the half
    of the claim a corpus cannot make: a key on every row of one baseline
    could still be conditional on state no scenario reaches.
    """
    tree = ast.parse(SURVIVAL_VIEW.read_text(encoding="utf-8"))
    guarded = {
        node
        for branch in ast.walk(tree)
        if isinstance(branch, ast.If)
        for node in ast.walk(branch)
    }
    return {
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "measured"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call not in guarded
    }


class TestTheRequiredSetIsMeasured:
    def test_the_baseline_has_rows_to_measure(self):
        assert len(_published_rows()) > 50

    def test_every_declared_key_is_on_every_published_row(self):
        rows = _published_rows()
        for field in (*LEDGER_READERS, *SURVIVAL_READERS):
            absent = [row for row in rows if field not in row]
            assert absent == [], (
                f"{field} is declared required and is missing from "
                f"{len(absent)} of {len(rows)} rows"
            )

    def test_the_ledger_half_is_stamped_by_its_default_factory(self):
        """A row exists in that book only by being made, so the factory is
        the whole of that half's producer."""
        assert set(Ledgers.empty().breakdown["main"]) == set(LEDGER_READERS)

    def test_the_survival_half_is_written_outside_every_branch(self):
        assert set(SURVIVAL_READERS) <= _unconditional_measures()


class TestTheReadersRefuseAnAbsentRequiredKey:
    @pytest.mark.parametrize(("field", "reader"), sorted(LEDGER_READERS.items()))
    def test_each_ledger_reader_raises_and_names_its_field(self, field, reader):
        row = {key: 0.0 for key in LEDGER_READERS if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    @pytest.mark.parametrize(("field", "reader"), sorted(SURVIVAL_READERS.items()))
    def test_each_survival_reader_raises_and_names_its_field(self, field, reader):
        row = {key: 0.0 for key in SURVIVAL_READERS if key != field}
        with pytest.raises(ValueError, match=field):
            reader(row)

    def test_a_survival_measure_keeps_the_type_the_walk_rounded_it_to(self):
        """A published zero's type is part of what the coupled baseline pins,
        so the reader hands back what it found."""
        assert survival_health_damage({**SURVIVAL_ROW, "health_damage": 0}) == 0
        assert isinstance(
            survival_health_damage({**SURVIVAL_ROW, "health_damage": 0}), int
        )

    def test_a_stamped_row_reads_its_own_values(self):
        row = {
            "participant_id": "main",
            "team": "main",
            "champion": "Ahri",
            "total_damage": 1200.5,
            "sources": {"Q": {"total_damage": 300.0}},
        }
        assert breakdown_participant_id(row) == "main"
        assert breakdown_team(row) == "main"
        assert breakdown_champion(row) == "Ahri"
        assert breakdown_total_damage(row) == 1200.5
        assert breakdown_sources(row) == {"Q": {"total_damage": 300.0}}
