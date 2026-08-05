"""Regression tests for the CP20 runtime item-coverage audit."""

from scripts.item_umbrella_audit import run_audit


def test_item_umbrella_audit_has_no_unexplained_runtime_gaps():
    receipt = run_audit()

    assert receipt["passed"] is True
    assert receipt["review_pending"] == []
    assert receipt["unexplained_blocks"] == []
    assert receipt["path_mismatches"] == []
    assert receipt["unresolved_source_conflicts"] == []
    assert receipt["counts"]["ordinary_source_items"] > 0
