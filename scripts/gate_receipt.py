"""Shared CI gate receipt schema.

Every gate script (acceptance_matrix, full_entry_audit, item_umbrella_audit,
champion_optimizer_matrix) serializes the same envelope: a strict boolean
``passed`` plus integer counts that satisfy the invariants
``passed + failed == total`` and ``passed == (failed == 0)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = 1


def build_receipt(
    *,
    matrix: str,
    passed: bool,
    passed_count: int,
    failed_count: int,
    total_count: int,
    withheld_count: int = 0,
    failures: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a validated gate receipt envelope."""
    if type(passed) is not bool:
        raise TypeError(f"passed must be a real bool, got {type(passed).__name__}")
    if passed_count < 0 or failed_count < 0 or total_count < 0 or withheld_count < 0:
        raise ValueError("counts must be non-negative")
    if passed_count + failed_count != total_count:
        raise ValueError(
            f"passed({passed_count}) + failed({failed_count}) != total({total_count})"
        )
    if passed != (failed_count == 0):
        raise ValueError("passed must equal (failed_count == 0)")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "matrix": matrix,
        "passed": passed,
        "counts": {
            "passed": passed_count,
            "failed": failed_count,
            "total": total_count,
            "withheld": withheld_count,
        },
        "failures": failures or [],
    }
    if extra:
        receipt.update(extra)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    """Raise ValueError when the envelope violates the shared contract."""
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    passed = receipt.get("passed")
    if type(passed) is not bool:
        raise ValueError(f"passed must be boolean, got {type(passed).__name__}")
    counts = receipt.get("counts") or {}
    for key in ("passed", "failed", "total", "withheld"):
        if key not in counts:
            raise ValueError(f"counts.{key} missing")
        if type(counts[key]) is not int or counts[key] < 0:
            raise ValueError(f"counts.{key} must be a non-negative int")
    if counts["passed"] + counts["failed"] != counts["total"]:
        raise ValueError("passed + failed must equal total")
    if passed != (counts["failed"] == 0):
        raise ValueError("passed must equal (failed == 0)")
    if not isinstance(receipt.get("failures"), list):
        raise ValueError("failures must be a list")
