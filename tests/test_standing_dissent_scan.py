"""R-19's blocking half, gated — repo-wide rather than at one boundary.

The escalation this file answers measured the state: 51 standing adverse
oracle verdicts, and *nothing in R-01 would go red if a future capture pinned
over one*.  Two scans read adverse verdicts before this, and both were scoped
to the Phase 4 boundary — one keyed on one entry's own leaf list, the other on
a filename prefix — so every dissent from Phase 0B, Phase 3 and Phase 5 was
invisible to every gate.

``scripts/standing_dissent_scan.py`` is the repo-wide join and this is what
runs it.  The load-bearing test is
``test_a_capture_that_pins_over_a_dissent_is_reported`` -- named rather than
placed, because "the last one" stopped being true the moment a test landed
after it: a fabricated capture that pins over a standing verdict is reported,
so "no gate would move" stops being true of the campaign's own strongest rule.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs" / "receipts" / "standing-dissent-adjudications.json"


@pytest.fixture(name="scan", scope="module")
def _scan():
    """The instrument, imported by path exactly as its siblings are."""
    spec = importlib.util.spec_from_file_location(
        "standing_dissent_scan", ROOT / "scripts" / "standing_dissent_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("standing_dissent_scan", module)
    spec.loader.exec_module(module)
    return module


def _block() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_declares_what_it_is_and_what_gates_it() -> None:
    block = _block()
    assert block["artifact"] == "standing_dissent_adjudications"
    assert block["gate"] == "tests/test_standing_dissent_scan.py"
    assert block["rule"].strip() and block["what_this_file_does_not_do"].strip()


def test_every_blocking_dissent_carries_an_adjudication(scan) -> None:
    """The gate: R-19's blocking half, over every committed receipt."""
    report = scan.report()
    assert report["unadjudicated"] == []
    assert report["stale_rows"] == []


def test_the_recorded_counts_reproduce(scan) -> None:
    """A receipt that records a number nobody recomputes is prose."""
    report = scan.report()
    recorded = _block()["measured_on_the_commit_that_lands_this"]
    for key in ("oracle_receipts", "adverse_verdicts", "standing", "blocking"):
        assert report[key] == recorded[key], key
    assert report["by_kind"] == recorded["by_kind"]


def test_every_row_is_one_of_the_two_kinds_and_says_something(scan) -> None:
    """There is no third kind, because "we looked at it" is not a verdict."""
    for row in _block()["adjudications"]:
        assert row["kind"] in scan.ADJUDICATION_KINDS, row["receipt"]
        if row["kind"] == "citation":
            assert row["cited_ruling"].strip()
            assert row["the_declared_change"].strip()
            assert row["why_no_oracle_could_answer_it"].strip()
            # Clause 3 of the R-15/R-18 amendment forbids editing or deleting a
            # filed receipt, and a citation is the one kind that adjudicates a
            # receipt without superseding it.  Saying so is what stops the row
            # from being read as a supersession, so it is required of the kind
            # rather than left to whichever row happens to carry it.
            assert row["the_receipt_is_not_deleted"].strip()
        else:
            assert row["what_is_owed"].strip()
            assert row["why_it_is_a_debt_and_not_a_citation"].strip()
            assert row["carried_by"].strip()


@pytest.mark.parametrize(
    "row", _block()["adjudications"], ids=lambda row: row["receipt"]
)
def test_every_row_answers_a_receipt_that_exists(row) -> None:
    """A row adjudicating nothing is an exception with a filename."""
    assert (ROOT / "docs" / "receipts" / row["receipt"]).exists()


def test_an_open_debt_names_an_artifact_that_exists(scan) -> None:
    """The half that keeps a debt from being a place work goes to stop."""
    for row in _block()["adjudications"]:
        if row["kind"] != "open_debt":
            continue
        path, _, _rest = row["carried_by"].partition(",")
        assert (ROOT / path.strip()).exists(), row["receipt"]


#: The oracle receipt an escalation's ``adjudication_row`` pointer names.
POINTED_RECEIPT = re.compile(r"oracle-[A-Za-z0-9._\-/]*\.json")


def _pointers_from_escalations() -> list[tuple[str, str, str]]:
    """Every ``(escalation path, entry id, oracle receipt)`` an escalation spells.

    Derived by walking each ``escalated-defects-*.json``'s open entries for the
    key rather than by naming the entries that carry one, so a pointer written
    into a new escalation joins this gate on the commit that writes it.
    """

    def walk(node: object) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "adjudication_row" and isinstance(value, str):
                    if RECEIPT.name in value:
                        found.extend(POINTED_RECEIPT.findall(value))
                else:
                    found.extend(walk(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(walk(item))
        return found

    out: list[tuple[str, str, str]] = []
    for path in sorted((ROOT / "docs" / "receipts").glob("escalated-defects-*.json")):
        block = json.loads(path.read_text(encoding="utf-8"))
        for entry in block.get("defects", ()):
            for receipt in walk(entry):
                out.append((path.relative_to(ROOT).as_posix(), entry["id"], receipt))
    return out


def _one_way_joins(rows: dict, pointers: list[tuple[str, str, str]]) -> tuple[str, ...]:
    """Pointers an escalation spells that the row it names does not spell back."""
    broken: list[str] = []
    for escalation, entry_id, receipt in pointers:
        row = rows.get(receipt)
        if row is None:
            broken.append(f"{escalation}/{entry_id} names no row: {receipt}")
            continue
        carried = row.get("carried_by", "")
        if escalation not in carried or entry_id not in carried:
            broken.append(f"{receipt} does not name {escalation}/{entry_id} back")
    return tuple(broken)


def test_a_row_an_open_escalation_names_names_it_back(scan) -> None:
    """The join runs both ways, or the reader who arrives first is stranded.

    An open escalation entry that points at a row here by name is the half
    that already held.  The other half is ``carried_by`` on the row it points
    at, and it went missing at ``ac4bb2c`` when that row turned from an
    ``open_debt`` into a ``citation`` -- a kind whose fields nothing required
    it of -- leaving a reader who arrived at the still-open escalation able to
    reach the row and a reader who arrived at the row unable to reach the
    escalation carrying it.  This is what makes that one-way state red instead
    of invisible.
    """
    pointers = _pointers_from_escalations()
    assert pointers, "no escalation names an adjudication row; the join is unread"
    rows = {row["receipt"]: row for row in _block()["adjudications"]}
    assert _one_way_joins(rows, pointers) == ()


def test_a_row_that_drops_its_pointer_back_is_reported() -> None:
    """R-05's red for the join, injected the way the field was actually lost.

    ``ac4bb2c`` did not delete a row -- it re-kinded one and dropped the
    field.  So the red is a row that is present, adjudicates the receipt the
    escalation names, and carries no ``carried_by``: exactly the state that
    stood in the tree from 2026-08-15 until ``08afece`` restored it.

    The assertion **names** the breaks the injection causes instead of
    counting them.  A count of one was coupled to there being exactly one
    escalation pointer in the tree, and the companion test above advertises
    the opposite as the point of deriving the pointers -- "a pointer written
    into a new escalation joins the gate on the commit that writes it".  Under
    that growth a second escalation naming this same oracle receipt breaks two
    joins at once, and the fixed count fails on the arithmetic rather than on
    the defect -- a red that reports the wrong thing.  So the expectation is
    derived from the pointer set: every pointer AT THIS RECEIPT breaks, and
    nothing else does.
    """
    pointers = _pointers_from_escalations()
    rows = {row["receipt"]: dict(row) for row in _block()["adjudications"]}
    _escalation, _entry_id, receipt = pointers[0]
    standing = set(_one_way_joins(rows, pointers))
    rows[receipt].pop("carried_by", None)
    broken_by_the_injection = {
        f"{receipt} does not name {escalation}/{entry_id} back"
        for escalation, entry_id, pointed_at in pointers
        if pointed_at == receipt
    }
    assert broken_by_the_injection
    assert set(_one_way_joins(rows, pointers)) == standing | broken_by_the_injection


def test_a_capture_that_pins_over_a_dissent_is_reported(scan) -> None:
    """The load-bearing negative (R-05), injected at the predicate.

    This is the sentence the escalation wrote and the campaign could not
    check: *nothing in R-01 would go red if a future capture pinned over a
    standing verdict*.  A fabricated member with no committed row is
    reported, so the sentence is now false by test rather than by assurance.
    """
    fabricated = scan.Pinned(
        receipt="oracle-a-capture-nobody-adjudicated.json",
        baseline="coupled_golden",
        address="/coupled_scenarios/x/combat/events[0]/damage",
        certified=100.0,
        committed=0.0,
    )
    rows = scan.load_adjudications()
    assert scan.unadjudicated((fabricated,), rows) == (fabricated.receipt,)
    # ...and a real member is not reported, so the red above is the injection
    # rather than the predicate rejecting everything it is handed.
    admitted = scan.Pinned(
        receipt=next(iter(rows)),
        baseline="coupled_golden",
        address="x",
        certified=1.0,
        committed=2.0,
    )
    assert scan.unadjudicated((admitted,), rows) == ()


def test_a_row_that_outlives_its_dissent_is_reported(scan) -> None:
    """An exception list nobody re-reads is the shape this campaign refuses."""
    rows = dict(scan.load_adjudications())
    rows["oracle-a-dissent-that-has-since-cleared.json"] = {"kind": "citation"}
    assert scan.stale_rows((), rows) == tuple(sorted(rows))


def test_the_standing_set_the_scan_reads_is_the_pinned_one(scan) -> None:
    """One home for the standing set, shared with the population's own gate.

    ``tests/test_standing_oracle_dissents.py`` pins the 51 by name.  This
    asserts the scan derives the same set rather than a second one: two
    definitions of "standing" would let a dissent be blocking under one and
    cleared under the other, which is precisely the drift the join exists to
    remove.
    """
    ledger = json.loads(
        (
            ROOT / "docs" / "receipts" / "escalated-defects-P4-integration-final.json"
        ).read_text(encoding="utf-8")
    )
    pinned = set(ledger["defects"][0]["standing_receipts"])
    assert set(scan.standing_dissents(scan.oracle_receipts())) == pinned


def test_a_receipt_is_read_at_the_value_it_certified(scan) -> None:
    """``old_value`` certifies for one verdict and the scan used it for all.

    ``old_value_correct`` is the verdict that certifies ``old_value``.  A
    ``both_wrong`` receipt certifies *neither* committed side and writes the
    number its whole-series computation reached under ``oracle_correct_value``,
    so reading ``old_value`` there asked whether the baseline held a value the
    receipt had refuted.
    """
    refuted_only = {"verdict": "both_wrong", "old_value": 100.0, "new_value": 0.0}
    computed = dict(refuted_only, oracle_correct_value=60.0)
    assert scan.certified_value(refuted_only) == 100.0
    assert scan.certified_value(computed) == 60.0


def test_a_baseline_holding_a_refuted_value_is_reported(scan) -> None:
    """R-05's red for the reading above, and it is the direction that mattered.

    Under ``certified = old_value`` a baseline still pinned at the number a
    ``both_wrong`` receipt refuted compared *equal* to it and left the blocking
    population silently — an absorption the scan existed to catch, invisible to
    the scan.  Both directions are asserted here, so the fix cannot be read as
    the check merely becoming quieter.
    """
    receipts = {
        "oracle-fabricated-both-wrong.json": {
            "verdict": "both_wrong",
            "leaf_path": "coupled_scenarios/x/combat/events[0]/damage",
            "old_value": 100.0,
            "new_value": 0.0,
            "oracle_correct_value": 60.0,
        }
    }
    body = receipts["oracle-fabricated-both-wrong.json"]
    assert not scan._same(100.0, scan.certified_value(body))  # the refuted value
    assert not scan._same(0.0, scan.certified_value(body))  # the other refuted one
    assert scan._same(60.0, scan.certified_value(body))  # what it computed


def test_a_certified_number_is_read_through_its_spelling(scan) -> None:
    """Filed receipts spell a certified number both ways, and both are numbers.

    Clause 3 forbids editing a filed receipt into a house style, so ``"60.0"``
    and ``60.0`` have to compare as the one number they are — five committed
    adverse receipts spell theirs as a string.  A value that is not a number
    is still compared as the string it is.
    """
    assert scan._same(60.0, "60.0")
    assert scan._same("34", 34)
    assert not scan._same(60.0, "61.0")
    assert not scan._same("a reason string", "a different reason string")


def test_a_declared_supersession_answers_a_dissent(scan) -> None:
    """Clause 3's supersession, which the scan could only ever infer.

    :func:`standing_dissents` reads supersession off a later same-leaf
    ``new_value_correct`` verdict.  Clause 3 states it explicitly instead —
    the filing names the receipt it replaces and the defect in that receipt's
    brief — and a clause-2 re-adjudication never carries the verdict word the
    inferred reading looks for.
    """
    receipts = {
        "oracle-superseded.json": {"verdict": "old_value_correct", "old_value": 1.0},
        "oracle-reposed.json": {
            "date": "2026-08-15",
            "verdict": "both_wrong",
            "supersedes": "oracle-superseded.json",
            "superseded_brief_defect": "the brief priced a member of an inserted series",
        },
    }
    pinned = (scan.Pinned("oracle-superseded.json", "coupled_golden", "x", 1.0, 2.0),)
    assert scan.superseded_by(receipts) == {
        "oracle-superseded.json": ("oracle-reposed.json",)
    }
    assert scan.answered_by_a_supersession(receipts, pinned) == (
        "oracle-superseded.json",
    )


def test_a_supersession_by_a_still_pinned_filing_answers_nothing(scan) -> None:
    """R-05's red for the arm above — the guard that keeps it from being a door.

    A chain of dissents must never retire a live pin.  The filing that
    supersedes has to be out of the blocking population itself, which means
    the committed baseline already holds what the current reading certifies;
    while it does not, the superseded receipt keeps its row.  The two other
    guards are asserted in the same shape: a filing that names no defect in
    the brief it replaces is oracle shopping and supersedes nothing, and one
    dated earlier than the receipt it names does not supersede it (R-19).
    """
    receipts = {
        "oracle-superseded.json": {
            "date": "2026-08-14",
            "verdict": "old_value_correct",
            "old_value": 1.0,
        },
        "oracle-reposed.json": {
            "date": "2026-08-15",
            "verdict": "both_wrong",
            "supersedes": "oracle-superseded.json",
            "superseded_brief_defect": "the brief priced a member of an inserted series",
        },
    }
    both_pinned = (
        scan.Pinned("oracle-superseded.json", "coupled_golden", "x", 1.0, 2.0),
        scan.Pinned("oracle-reposed.json", "coupled_golden", "x", 3.0, 2.0),
    )
    assert scan.answered_by_a_supersession(receipts, both_pinned) == ()

    no_defect = json.loads(json.dumps(receipts))
    no_defect["oracle-reposed.json"].pop("superseded_brief_defect")
    assert scan.superseded_by(no_defect) == {}

    dated_earlier = json.loads(json.dumps(receipts))
    dated_earlier["oracle-reposed.json"]["date"] = "2026-08-13"
    only_the_dissent = (both_pinned[0],)
    assert scan.answered_by_a_supersession(dated_earlier, only_the_dissent) == ()
