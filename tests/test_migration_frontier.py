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
    first run by rule, and S10 re-keyed the three sites it found onto values,
    so the counter is asserted at its target *and* its recorded baseline is
    asserted positive — a counter whose target is 0 and whose baseline is 0
    states nothing.

    Counter 5 is asserted at its **target** rather than at its baseline
    since Phase 4 S4 moved the eight remaining construction expressions into
    ``program/compile.py``.  Asserting the baseline after that would be
    asserting the tree had not been migrated, which is the opposite of what
    the counter is for; the move itself is the diff in
    ``docs/migration-frontier.json``, where the per-file tally went from
    three files to one.
    """
    report = migration_frontier.scan()
    assert report.counter_5 == migration_frontier.COUNTER_5_TARGET
    assert report.counter_6_kernel <= migration_frontier.COUNTER_6_KERNEL_BASELINE
    assert report.counter_6_program == 0
    assert report.counter_7 == migration_frontier.COUNTER_7_TARGET
    assert migration_frontier.COUNTER_7_BASELINE > 0


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


# --------------------------------------------------------------------------
# A counter that moves names its cause.
#
# R-36 puts the regenerated receipt in the commit whose counters it records,
# which makes every movement a diff.  What it does not do is make the movement
# *explained*: a certification reviewer read the close report's section 5,
# which states counter 6's kernel value as of the tip that wrote it, measured
# the tip at a higher value, and found the difference carried no cause anywhere
# a reader of the closing artifacts would look.
#
# So the property is asserted instead of relied on, and asserted against the
# tree rather than against a walk of the history: the movement ledger records
# every move since the report's tip with the cause its commit stated, and the
# committed receipt must sit at the ledger's endpoint.  A move that lands
# without a row is red on the commit that lands it, which is the difference
# between a cause the campaign happened to write and a cause it cannot omit.
# --------------------------------------------------------------------------

#: The derived ledger of counter movements since the close report's tip.
MOVEMENTS = ROOT / "docs" / "receipts" / "migration-frontier-movements.json"

#: The receipt the movements are measured over.
RECEIPT_IN_TREE = ROOT / "docs" / "migration-frontier.json"

#: ``(counter, the key holding its value)`` — every scalar a movement can be
#: measured over.  Read from the receipt rather than from the script's
#: constants, because the receipt is what a commit carries.
COUNTER_VALUES = (
    ("counter_5", "value"),
    ("counter_6", "kernel_value"),
    ("counter_6", "program_value"),
    ("counter_7", "value"),
)

#: How a body names a counter.  The campaign's commits write "counter 6", the
#: receipt keys it ``counter_6``; both spellings are accepted so a cause is not
#: required to quote a JSON key at a reader.
_COUNTER_SPELLINGS = {
    "counter_5": ("counter 5", "counter_5"),
    "counter_6": ("counter 6", "counter_6"),
    "counter_7": ("counter 7", "counter_7"),
}

#: How a cause spells a move.  Both arrows the repository uses, plus the English.
_ARROWS = ("->", "→", "to")


def movement_ledger() -> dict:
    """The committed ledger of counter movements since the report's tip."""
    return json.loads(MOVEMENTS.read_text(encoding="utf-8"))


def _values(receipt: dict) -> dict[str, int]:
    """``"counter.key" -> value`` for every scalar a movement is measured over."""
    counters = receipt.get("counters", {})
    return {
        f"{counter}.{key}": counters[counter][key]
        for counter, key in COUNTER_VALUES
        if counter in counters and key in counters[counter]
    }


def states_the_move(cause: str, counter: str, old: int, new: int) -> bool:
    """Whether a recorded cause names this counter and the move it made.

    The pure predicate, so the red below is a seam rather than a commit
    somebody has to remember making (R-05).
    """
    spoken = cause.lower()
    if not any(name in spoken for name in _COUNTER_SPELLINGS[counter]):
        return False
    return any(f"{old} {arrow} {new}" in spoken for arrow in _ARROWS)


def test_every_counter_movement_since_the_report_names_its_cause() -> None:
    """The property the reviewer's minor asks for, as a check and not a habit."""
    unexplained = [
        row
        for row in movement_ledger()["movements"]
        if not states_the_move(row["cause"], row["counter"], row["from"], row["to"])
    ]
    assert unexplained == []


def test_the_named_cause_check_has_a_red_it_can_reproduce() -> None:
    """R-05, through the predicate's own seam.

    Three causes: one that names neither, one that names the counter and not
    the move — the shape a body takes when a receipt is regenerated as
    housekeeping — and one that names both, which is what the ledger carries.
    """
    assert not states_the_move("regenerated the receipt", "counter_6", 75, 78)
    assert not states_the_move("counter 6 is unchanged here", "counter_6", 75, 78)
    assert states_the_move(
        "`docs/migration-frontier.json` counter 6 moves 75 -> 78: the three "
        "`round(..., 6)` calls in the new receipt",
        "counter_6",
        75,
        78,
    )


def test_the_committed_receipt_sits_at_the_ledgers_endpoint() -> None:
    """The tooth: an unrecorded movement is red on the commit that lands it.

    The ledger is a chain, not a list somebody remembered to append to — the
    report tip's values plus every recorded move must be the values the tree
    carries, so a counter that moves without a row leaves the two apart.
    """
    ledger = movement_ledger()
    walked = dict(ledger["at_report_tip"])
    for row in ledger["movements"]:
        key = f"{row['counter']}.{row['key']}"
        assert walked[key] == row["from"], f"{row['sha']} moves {key} from elsewhere"
        walked[key] = row["to"]
    assert walked == _values(json.loads(RECEIPT_IN_TREE.read_text(encoding="utf-8")))


def test_the_ledger_records_a_movement_the_report_can_be_read_against() -> None:
    """A ledger that recorded nothing would pass the two checks above by default."""
    ledger = movement_ledger()
    assert ledger["movements"], "the ledger is empty and asserts nothing"
    for row in ledger["movements"]:
        assert row["from"] != row["to"], row["sha"]
        assert (row["counter"], row["key"]) in COUNTER_VALUES, row["sha"]
        assert row["sha"] and row["subject"], row["sha"]
