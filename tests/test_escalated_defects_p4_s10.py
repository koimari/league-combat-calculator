"""S10's escalation, gated: the two deletion-frontier rows cleanup cannot close.

An escalation living only in a commit body is absorbed by the next baseline
re-capture, which is why the runbook makes it an artifact (R-16 Shape).  An
artifact nothing runs is prose in a JSON file, which is why it has this.

Each defect declares a reproducer and each reproducer runs here.  The day
somebody authors ``CcScope``, the matching test goes red -- which is the
point: an entry retires *with* the inversion of its own test, never by being
deleted.

One entry has since done exactly that.  S10 unified the compiler's two row
readers after an R-35 verifier reported criterion 2 undischarged on them,
and the entry moved to ``retired`` carrying what the lane measured; the test
that reproduced it is inverted below rather than removed, so the artifact
and the tree still say the same thing about a row whose answer changed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P4-S10.json"
SRC = ROOT / "src" / "calculator"


def receipt() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_declares_what_it_is_and_what_gates_it() -> None:
    block = receipt()
    assert block["artifact"] == "escalated_defects"
    assert block["slice"] == "P4-S10"
    assert block["gate"] == "tests/test_escalated_defects_p4_s10.py"


def test_every_open_defect_carries_a_reproducer_and_a_date() -> None:
    """An entry without a reproducer is an opinion with a filename."""
    for defect in receipt()["defects"]:
        assert defect["id"] and defect["dated"]
        assert defect["reproducer"] and defect["reproducer_after_closure"]
        assert defect["why_this_lane_may_not_fix_it"]
        assert defect["for_the_phase_owner"]


def test_the_open_defects_are_the_ones_this_file_reproduces() -> None:
    """A gate that drifted off its entries is a gate for nothing."""
    assert [defect["id"] for defect in receipt()["defects"]] == [
        "the_first_defender_scan_survives_because_ccscope_was_never_authored",
        "no_production_path_emits_a_non_measured_disposition_consumption_half_closed",
    ]


def test_a_retired_entry_says_how_it_closed_and_what_gates_it_now() -> None:
    """Retirement is a record, not a deletion — the artifact's own rule."""
    retired = receipt()["retired"]
    assert [entry["id"] for entry in retired] == [
        "walk_compilers_two_row_readers_are_not_the_duplication_the_frontier_names"
    ]
    for entry in retired:
        assert entry["retired"] and entry["retired_by"]
        assert entry["how_it_closed"] and entry["what_the_lane_measured"]
        assert entry["gate_after_closure"]
        # The reproducer it declared has to be the one that stopped
        # reproducing, so the entry still names it.
        assert entry["reproducer"] and entry["reproducer_after_closure"]


# --- the first-defender scan -------------------------------------------------


def _source(*parts: str) -> str:
    return (SRC.joinpath(*parts)).read_text(encoding="utf-8")


def test_no_cc_scope_vocabulary_exists_in_src() -> None:
    """The shipped H2 default is a construction, and it is not constructed."""
    holders = {
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if "CcScope" in path.read_text(encoding="utf-8")
    }
    tree_defines_it = any(
        isinstance(node, ast.ClassDef) and node.name == "CcScope"
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )
    assert holders, "the entry claims two mentions; zero would mean it drifted"
    assert not tree_defines_it


def test_the_first_defender_scan_is_still_defined_and_called() -> None:
    """The row is open, and this is the shape that says so."""
    timeline = _source("participant_timeline.py")
    tree = ast.parse(timeline)
    defined = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_first_pair_defender_id"
    ]
    called = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_first_pair_defender_id"
    ]
    assert len(defined) == 1
    assert called


def test_the_score_paths_support_scan_still_indexes_pair_zero() -> None:
    """The other half of the same convention, in the other composition."""
    assert "context.main_pair_params[0][0].participant_id" in _source(
        "participant_timeline.py"
    )


# --- the compiler's two row readers, retired ---------------------------------


def test_the_compiler_still_knows_which_row_shape_it_holds() -> None:
    """Retiring the row did not delete the light ledger, and must not.

    The entry's own ``reproducer_after_closure`` offers two inversions --
    "reads one row shape, **or** the frontier row names the constructor".
    What landed is neither restatement: one loop, one tail, and a two-arm
    read of the two representations.  ``damage_events_tuple`` is therefore
    still consulted, exactly once, and a reader that stopped consulting it
    would be compiling light rows as dicts.
    """
    compiler = _source("program", "compile.py")
    assert compiler.count('result.get("damage_events_tuple")') == 1


def test_the_row_shapes_no_longer_have_a_loop_each() -> None:
    """The inversion: one damage loop, where the entry reproduced two."""
    tree = ast.parse(_source("program", "compile.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "add_engine_result"
    )
    loops = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.For)
        and "damage_events" in ast.dump(node.iter)
        and "damage_events_tuple" not in ast.dump(node.iter)
    ]
    assert len(loops) == 1


def test_the_one_loop_ends_in_the_one_constructor() -> None:
    """The half S4 did close, asserted so the entry cannot overstate itself."""
    tree = ast.parse(_source("program", "compile.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "add_engine_result"
    )
    builders = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "compiled_damage_action" in builders


# --- the consumption half S10 closed -----------------------------------------


def test_the_ranking_surface_rebuilds_its_operand_from_the_payloads_entry() -> None:
    """The half that was implementable as cleanup, asserted as closed."""
    assert "published_quantity(dispositions, path, value" in _source("bis.py")


def test_and_nothing_in_src_still_produces_a_withheld_quantity() -> None:
    """The half that is not: no producer, so the backstop injects its member."""
    producers = {
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Withheld"
    }
    assert producers <= {"ability_spec.py", "program/views/__init__.py"}
