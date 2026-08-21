"""Regression tests for the CP20 runtime item-coverage audit."""

import json

from scripts.item_umbrella_audit import RECEIPT_PATH, receipt_diff, run_audit


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


def test_the_committed_receipt_is_what_a_fresh_audit_produces():
    """The published receipt and the runtime answer, held together.

    ``docs/item-umbrella-audit.json`` is refreshed by hand — no gate script
    writes it and, until this test, nothing compared it to a run.  It went
    stale exactly that way during 3.8: the target-lane flip moved 11 statuses
    and 211 reasons inside it while its counts stayed identical, so every
    commit body could truthfully say "209/209, target_blocked 0" and no gate
    anywhere could see that the committed file no longer matched the code.
    R-36 wants a machine-derived receipt to move **with** the slice that moves
    it, and this is what makes that a rule rather than a habit.
    """
    committed = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    assert receipt_diff(committed, run_audit()) == ()


def test_the_receipt_gate_names_the_field_that_moved():
    """R-05's red for that gate, permanent and on demand.

    A comparison's negative is a comparison: the committed receipt with one
    entry's reason perturbed **in memory**, nothing written and the file on
    disk untouched.  The path is keyed by item name rather than by list
    position, which is the property that keeps a real failure readable.
    """
    committed = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    perturbed = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    entry = min(perturbed["entries"], key=lambda row: row["name"])
    entry["attacker"]["reason"] = "a reason nobody published"

    assert receipt_diff(committed, perturbed) == (
        (
            f"entries.{entry['name']}.attacker.reason",
            committed["entries"][0]["attacker"]["reason"],
            "a reason nobody published",
        ),
    )
