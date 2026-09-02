"""Gate receipt schema contract (issue #139)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import acceptance_matrix, champion_optimizer_matrix
from scripts.gate_receipt import (
    SCHEMA_VERSION,
    build_receipt,
    validate_receipt,
)

ROOT = Path(__file__).resolve().parents[1]

# ── canned endpoint responses ────────────────────────────────────────────────
# The two matrices take their ``post`` as a parameter, so an envelope test
# needs no server: one certified answer and one withheld answer exercise both
# branches of every count the envelope carries.

_CERTIFIED_OPTIMIZE = {
    "items": ["Kraken Slayer"],
    "boots": None,
    "is_certified_best": True,
    "search_timeline_coverage": {"complete": True},
}
_WITHHELD_OPTIMIZE = {
    "items": None,
    "boots": None,
    "is_certified_best": False,
    "error": "no certified build",
    "search_timeline_coverage": {"complete": True, "note": "withheld"},
}
_CALCULATE_OK = {"timeline_coverage": {"complete": True}, "participants": []}


def _canned_acceptance_results(post, *, origin="local:test_client"):
    """One certified and one withheld scenario, through the real summarizer."""
    scenarios = list(acceptance_matrix.SCENARIOS.items())[:2]
    optimize_bodies = (_CERTIFIED_OPTIMIZE, _WITHHELD_OPTIMIZE)
    return [
        acceptance_matrix._summarize(
            name,
            payload,
            (200, _CALCULATE_OK),
            (200, body),
            origin=origin,
        )
        for (name, payload), body in zip(scenarios, optimize_bodies, strict=False)
    ]


def _canned_optimize_post(_path, _payload):
    return 200, dict(_CERTIFIED_OPTIMIZE, search_timeline_coverage={"complete": True})


def test_build_receipt_requires_real_bool():
    with pytest.raises(TypeError):
        build_receipt(
            matrix="m", passed=3, passed_count=3, failed_count=0, total_count=3
        )


def test_build_receipt_enforces_count_invariants():
    # consistent: failed=1 with passed=False
    build_receipt(
        matrix="m", passed=False, passed_count=2, failed_count=1, total_count=3
    )
    # inconsistent: failed=1 claims passed=True
    with pytest.raises(ValueError, match="passed"):
        build_receipt(
            matrix="m", passed=True, passed_count=2, failed_count=1, total_count=3
        )
    # inconsistent: sums do not match total
    with pytest.raises(ValueError, match="total"):
        build_receipt(
            matrix="m", passed=True, passed_count=2, failed_count=2, total_count=3
        )


def test_acceptance_matrix_emits_boolean_passed(capsys, monkeypatch):
    """The concrete bug: acceptance_matrix serialized the count (int) as passed.

    Driven over canned endpoint responses rather than the live matrix: the
    envelope is built by the same ``main()`` code either way, and running the
    real scenarios cost 31 s of the suite's parallel wall to re-measure what
    the endpoint suites already cover.
    """
    # ``main()`` imports ``gate_receipt`` the way a script run resolves it.
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setattr(acceptance_matrix, "run_matrix", _canned_acceptance_results)
    monkeypatch.setattr(sys, "argv", ["acceptance_matrix.py", "--json"])
    acceptance_matrix.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["schema_version"] == SCHEMA_VERSION
    validate_receipt(receipt)
    assert type(receipt["passed"]) is bool
    # One certified and one withheld scenario: the counts are the matrix's
    # own arithmetic over them, not a restatement of the envelope.
    assert receipt["passed"] is True
    assert receipt["counts"] == {"passed": 2, "failed": 0, "total": 2, "withheld": 1}


def test_validate_rejects_int_passed():
    with pytest.raises(ValueError, match="boolean"):
        validate_receipt(
            {"schema_version": 1, "passed": 5, "counts": {}, "failures": []}
        )


def test_validate_rejects_string_and_falsy_int_passed():
    # bool is a subclass of int in Python, so `type(x) is bool` is the strict
    # check: "true" and 0 must be rejected just like 3.
    for bad in ("true", 0, 1):
        with pytest.raises(ValueError, match="boolean"):
            validate_receipt(
                {
                    "schema_version": 1,
                    "passed": bad,
                    "counts": {"passed": 0, "failed": 0, "total": 0, "withheld": 0},
                    "failures": [],
                }
            )


def test_validate_rejects_count_invariant_violations():
    base = {"schema_version": 1, "passed": False, "failures": []}
    with pytest.raises(ValueError, match=r"passed \+ failed"):
        validate_receipt(
            {
                **base,
                "counts": {"passed": 7, "failed": 3, "total": 9, "withheld": 0},
            }
        )
    with pytest.raises(ValueError, match="passed must equal"):
        validate_receipt(
            {
                **base,
                "passed": True,  # failed=3 must never serialize as passed=True
                "counts": {"passed": 10, "failed": 3, "total": 13, "withheld": 0},
            }
        )
    with pytest.raises(ValueError, match=re.escape("counts.failed")):
        validate_receipt(
            {
                **base,
                "counts": {"passed": 7, "failed": "3", "total": 10, "withheld": 0},
            }
        )
    with pytest.raises(ValueError, match="failures"):
        validate_receipt(
            {
                **base,
                "passed": True,  # failed=0, so the boolean must be True here
                "counts": {"passed": 10, "failed": 0, "total": 10, "withheld": 0},
                "failures": "not-a-list",
            }
        )


def test_zero_result_envelope_is_valid():
    """total=0 with passed=True preserves the acceptance matrix's all([]) semantics."""
    receipt = build_receipt(
        matrix="m", passed=True, passed_count=0, failed_count=0, total_count=0
    )
    validate_receipt(receipt)
    assert receipt["counts"]["total"] == 0


def test_partial_envelope_is_valid_with_failed_count():
    receipt = build_receipt(
        matrix="m",
        passed=False,
        passed_count=7,
        failed_count=3,
        total_count=10,
        failures=[{"name": "x", "reason": "r"}],
    )
    validate_receipt(receipt)
    assert receipt["passed"] is False
    assert receipt["counts"] == {"passed": 7, "failed": 3, "total": 10, "withheld": 0}


def test_validate_receipt_cli(tmp_path):
    """The CI validator exits 0 on valid receipts and 1 on malformed ones."""
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            build_receipt(
                matrix="m", passed=True, passed_count=1, failed_count=0, total_count=1
            )
        )
    )
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"passed": 3, "counts": {}}))
    ok = subprocess.run(
        [sys.executable, "scripts/validate_receipt.py", str(good)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert ok.returncode == 0
    assert "ok" in ok.stdout
    fail = subprocess.run(
        [sys.executable, "scripts/validate_receipt.py", str(bad)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert fail.returncode == 1
    assert "FAIL" in fail.stdout


def test_champion_optimizer_matrix_emits_boolean_envelope():
    """The optimizer matrix's envelope must validate like its siblings.

    Over a canned ``post`` rather than the live all-champion smoke run,
    which is the optimizer suite's job and cost 7.5 s here to repeat.
    """
    names = ["Ahri", "Aatrox"]
    report = champion_optimizer_matrix.run_matrix(_canned_optimize_post, names)
    receipt = champion_optimizer_matrix.build_gate_report(report, names)
    assert receipt["schema_version"] == SCHEMA_VERSION
    validate_receipt(receipt)
    assert type(receipt["passed"]) is bool
    assert receipt["counts"]["total"] == len(names)


def test_ci_validates_every_receipt_it_emits():
    """A new matrix cannot ship an unchecked artifact (the issue #139 TODO)."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    written = set(re.findall(r">\s*(artifacts/backend/\S+\.json)", workflow))
    # status.json carries the two exit codes, not a gate receipt envelope.
    written.discard("artifacts/backend/status.json")
    validated = set(
        re.findall(
            r"(artifacts/backend/\S+\.json)",
            next(
                line for line in workflow.splitlines() if "validate_receipt.py" in line
            ),
        )
    )
    assert written
    assert written == validated


def test_item_umbrella_audit_emits_boolean_envelope():
    """The umbrella gate's envelope must validate like its siblings."""
    import json as _json

    result = subprocess.run(
        [sys.executable, "scripts/item_umbrella_audit.py", "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    receipt = _json.loads(result.stdout)
    assert receipt["schema_version"] == SCHEMA_VERSION
    validate_receipt(receipt)
    assert type(receipt["passed"]) is bool
