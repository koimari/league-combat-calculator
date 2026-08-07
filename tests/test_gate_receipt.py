"""Gate receipt schema contract (issue #139)."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.gate_receipt import SCHEMA_VERSION, build_receipt, dump_receipt, validate_receipt

ROOT = Path(__file__).resolve().parents[1]


def test_build_receipt_requires_real_bool():
    with pytest.raises(TypeError):
        build_receipt(matrix="m", passed=3, passed_count=3, failed_count=0, total_count=3)


def test_build_receipt_enforces_count_invariants():
    # consistent: failed=1 with passed=False
    build_receipt(matrix="m", passed=False, passed_count=2, failed_count=1, total_count=3)
    # inconsistent: failed=1 claims passed=True
    with pytest.raises(ValueError, match="passed"):
        build_receipt(matrix="m", passed=True, passed_count=2, failed_count=1, total_count=3)
    # inconsistent: sums do not match total
    with pytest.raises(ValueError, match="total"):
        build_receipt(matrix="m", passed=True, passed_count=2, failed_count=2, total_count=3)


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
        build_receipt(matrix="m", passed=True, passed_count=1, failed_count=0, total_count=1),
        out,
    )
    assert json.loads(out.read_text())["passed"] is True
    assert not out.with_suffix(".json.tmp").exists()


def test_validate_rejects_int_passed():
    with pytest.raises(ValueError, match="boolean"):
        validate_receipt({"schema_version": 1, "passed": 5, "counts": {}, "failures": []})
