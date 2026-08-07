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
    assert receipt["counts"]["failed"] == 0
    assert receipt["counts"]["passed"] == receipt["counts"]["total"]


def test_item_umbrella_audit_emits_the_gate_receipt_envelope():
    """The umbrella receipt carries the shared envelope (issue #139)."""
    from scripts.gate_receipt import SCHEMA_VERSION, validate_receipt

    receipt = run_audit()
    validate_receipt(receipt)
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert type(receipt["passed"]) is bool
    assert isinstance(receipt["failures"], list)
    # Every ordinary item is a covered unit.
    assert receipt["counts"]["total"] == receipt["counts"]["ordinary_source_items"]
