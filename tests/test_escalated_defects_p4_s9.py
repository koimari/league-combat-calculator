"""S9's escalation, gated: the four-disposition wire shape is not operational.

An escalation living only in a commit body is absorbed by the next baseline
re-capture, which is why the runbook makes it an artifact (R-16 Shape).  An
artifact nothing runs is prose in a JSON file, which is why it has this.

Each defect declares a reproducer, and each reproducer runs here.  The day
somebody wires the outcome ledger into the walk these go red -- which is the
point: the entry retires *with* the inversion of its own test, not by being
deleted.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P4-S9.json"
SRC = ROOT / "src" / "calculator"


def receipt() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_declares_what_it_is_and_what_gates_it() -> None:
    block = receipt()
    assert block["artifact"] == "escalated_defects"
    assert block["slice"] == "P4-S9"
    assert block["gate"] == "tests/test_escalated_defects_p4_s9.py"


def test_every_open_defect_carries_a_reproducer_and_a_date() -> None:
    """An entry without a reproducer is an opinion with a filename."""
    for defect in receipt()["defects"]:
        assert defect["id"] and defect["dated"]
        assert defect["reproducer"] and defect["reproducer_after_closure"]
        assert defect["why_this_lane_may_not_fix_it"]


def test_the_open_defect_is_the_one_this_file_reproduces() -> None:
    """A gate that drifted off its entry is a gate for nothing."""
    assert [defect["id"] for defect in receipt()["defects"]] == [
        "no_production_path_emits_a_non_measured_disposition"
    ]


def _golden_snapshot():
    """The capture instrument, imported by path exactly as its own tests do."""
    spec = importlib.util.spec_from_file_location(
        "golden_snapshot", ROOT / "scripts" / "golden_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("golden_snapshot", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "scenario", ("mandate_abyssal_curse_roster", "cleaver_bloodsong_roster")
)
def test_every_published_disposition_is_measured(scenario: str) -> None:
    """The first half of the reproducer, against a live run.

    Red on this test means a production path finally emits a disposition
    that is not ``MEASURED`` -- which is the defect closing, not a
    regression.  Retire the entry and invert this assertion.
    """
    snapshot = _golden_snapshot()
    definition = next(
        item for item in snapshot.COUPLED_SCENARIOS if item.name == scenario
    )
    combat = snapshot.coupled_entry(definition)["combat"]
    assert combat["dispositions"], "a vacuous map proves nothing either way"
    assert {entry["disposition"] for entry in combat["dispositions"].values()} == {
        "MEASURED"
    }


def test_the_outcome_ledger_is_constructed_nowhere_but_its_own_module() -> None:
    """The second half: the one component that produces the other three.

    ``OutcomeLedger.quantity`` answers ``StructuralZero`` for a refused
    transition and ``Starved`` for one nothing wrote.  No walk runs on it, so
    those answers reach no payload.
    """
    sites = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "OutcomeLedger"
        )
        if count:
            sites[path.relative_to(SRC).as_posix()] = count
    assert sites == {}


def test_the_serializer_can_nevertheless_express_all_four() -> None:
    """The gap is reach, not shape — and the receipt says so.

    Without this the entry would read as "the wire shape is broken", which
    is a different and false claim.
    """
    from src.calculator.ability_spec import Disposition, StructuralZero, Withheld
    from src.calculator.program.views import ViewTag, serialize_leaf

    withheld = serialize_leaf(
        "x", Withheld(receipts=("coverage refused",)), ViewTag.APPLIED
    )
    assert withheld.present is False
    assert withheld.entry["disposition"] == Disposition.WITHHELD.value
    zero = serialize_leaf("y", StructuralZero(reason="declared"), ViewTag.APPLIED)
    assert (zero.value, zero.entry["disposition"]) == (
        0.0,
        Disposition.STRUCTURAL_ZERO.value,
    )
