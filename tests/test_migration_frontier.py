"""The migration frontier's own gate: does it measure, and can it fail?

Phase 4 counters 5-7 (D-40, R-36).  Three properties matter here and each
one is a test rather than a reading of the script:

* the counters reproduce the baselines the phase declared, so the figures in
  ``docs/migration-frontier.json`` have a producer rather than an author;
* the committed receipt equals the tree, which is what makes a counter move
  a diff somebody explains;
* the gate can be made to fail on demand (R-05) — a check that has never
  been seen red is indistinguishable from a check that cannot go red, which
  is the campaign's own thesis applied to the campaign's own instrument.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import migration_frontier  # noqa: E402  pylint: disable=C0413


def test_the_three_counters_reproduce_the_declared_baselines() -> None:
    """D-71 and criterion 2's figures, measured rather than quoted.

    Counter 5's 9 and counter 6's 118 are the numbers Phase 4 declared before
    its first commit; counter 7's baseline is measured by this script on its
    first run by rule, so what is asserted here is that it is positive — a
    counter whose target is 0 and whose baseline is 0 states nothing.
    """
    report = migration_frontier.scan()
    assert report.counter_5 == 9
    assert report.counter_6_kernel <= migration_frontier.COUNTER_6_KERNEL_BASELINE
    assert report.counter_6_program == 0
    assert report.counter_7 > 0


def test_counter_6_counts_text_and_records_the_ast_call_count_beside_it() -> None:
    """The 118 includes one occurrence that is prose, and the receipt says so.

    ``score_state.py`` explains in a comment why the score ledger pays for no
    rounding.  A counter that counted calls would read 117 against a plan that
    says 118; a counter that counted only text could be driven down by
    deleting a comment.  Recording both is what makes either move visible.
    """
    report = migration_frontier.scan()
    prose_only = {
        path: text - report.round_calls[path]
        for path, text in report.round_text.items()
        if text != report.round_calls[path]
    }
    assert prose_only == {"calculator/survival/score_state.py": 1}


def test_the_committed_receipt_equals_the_tree() -> None:
    """``--check``'s pass condition, as a test rather than as a CI step."""
    assert migration_frontier.check(migration_frontier.scan()) == ()


def test_the_receipt_on_disk_is_what_the_script_would_write() -> None:
    """No hand edit survives in the receipt: it is generated, byte for byte."""
    fresh = migration_frontier.build_receipt(migration_frontier.scan())
    committed = json.loads(migration_frontier.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert committed == fresh


def test_every_preserved_defect_row_carries_a_reason_and_a_ruling() -> None:
    """A preserved defect is a receipt, not a suppression."""
    for row in migration_frontier.PRESERVED_DEFECTS:
        assert row["name"].strip()
        assert row["what"].strip()
        assert row["why"].strip()
        assert row["declined_by"].strip()
        assert row["ruling"].strip()


def test_late_barrier_is_one_of_them() -> None:
    """Criterion 18 names it; this is where the naming is checked."""
    assert "LATE_BARRIER" in {
        row["name"] for row in migration_frontier.PRESERVED_DEFECTS
    }


def test_the_gate_reports_a_counter_that_moved() -> None:
    """R-05's permanent red: the committed value and the tree disagree."""
    report = migration_frontier.scan()
    committed = migration_frontier.build_receipt(report)
    committed["counters"]["counter_6"]["kernel_value"] = 0
    committed["counters"]["counter_6"]["kernel_by_file"] = {}
    failures = migration_frontier.check(report, committed)
    assert any("counter_6.kernel_value" in failure for failure in failures)


def test_the_gate_reports_an_exclusion_set_that_moved() -> None:
    """D-40's whole point: the exclusions are diffed, not trusted."""
    report = migration_frontier.scan()
    committed = migration_frontier.build_receipt(report)
    committed["exclusions"]["counter_7_value_derived_cache_keys"] = {
        "calculator/stats.py": "argued away in the receipt instead of in code",
    }
    failures = migration_frontier.check(report, committed)
    assert any("counter_7_value_derived_cache_keys" in failure for failure in failures)


def test_the_gate_reports_a_preserved_defect_that_vanished() -> None:
    """Dropping a defect row is a diff, so it cannot be dropped in silence."""
    report = migration_frontier.scan()
    committed = migration_frontier.build_receipt(report)
    committed["preserved_defects"] = []
    failures = migration_frontier.check(report, committed)
    assert any("preserved_defects" in failure for failure in failures)


def test_the_gate_reports_a_missing_receipt() -> None:
    """An absent receipt is a failure, never an empty pass."""
    assert migration_frontier.check(migration_frontier.scan(), {}) == (
        "migration-frontier.json is missing; run --write",
    )
