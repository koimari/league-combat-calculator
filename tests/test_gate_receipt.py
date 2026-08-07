"""Gate receipt schema contract (issue #139)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.gate_receipt import (
    SCHEMA_VERSION,
    build_receipt,
    dump_receipt,
    validate_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


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


def test_acceptance_matrix_emits_boolean_passed():
    """The concrete bug: acceptance_matrix serialized the count (int) as passed."""
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/acceptance_matrix.py", "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    # exit code may be nonzero for withheld scenarios; the envelope must still validate
    receipt = json.loads(result.stdout)
    assert receipt["schema_version"] == SCHEMA_VERSION
    validate_receipt(receipt)
    assert type(receipt["passed"]) is bool


def test_dump_receipt_is_atomic(tmp_path):
    out = tmp_path / "gate.json"
    dump_receipt(
        build_receipt(
            matrix="m", passed=True, passed_count=1, failed_count=0, total_count=1
        ),
        out,
    )
    assert json.loads(out.read_text())["passed"] is True
    assert not out.with_suffix(".json.tmp").exists()


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
    with pytest.raises(ValueError, match="counts.failed"):
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
    )
    assert ok.returncode == 0
    assert "ok" in ok.stdout
    fail = subprocess.run(
        [sys.executable, "scripts/validate_receipt.py", str(bad)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert fail.returncode == 1
    assert "FAIL" in fail.stdout


def test_item_umbrella_audit_emits_boolean_envelope():
    """The umbrella gate's envelope must validate like its siblings."""
    import json as _json

    result = subprocess.run(
        [sys.executable, "scripts/item_umbrella_audit.py", "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    receipt = _json.loads(result.stdout)
    assert receipt["schema_version"] == SCHEMA_VERSION
    validate_receipt(receipt)
    assert type(receipt["passed"]) is bool
