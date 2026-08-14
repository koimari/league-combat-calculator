"""Every adverse oracle verdict in the repo, counted once and pinned.

R-19 says a baseline does not move while a qualifying occurrence lacks a
receipt, and the R-15/R-18 amendment says a dissent clears by supersession and
never by revision.  Until this module neither was enforced repo-wide: the only
machine checks that read an adverse verdict are the two scans in
``tests/test_escalated_defects_p4_boundary.py``, one keyed on that entry's own
``dissenting_population`` and the other on the ``oracle-P4B-`` filename prefix.
Every dissent outside those two sets was invisible to R-01 — including one
filed at the Phase 4 boundary itself.

The gate is a frontier with a committed list, the idiom D-40/R-36 already use:
the standing set is enumerated into
``docs/receipts/escalated-defects-P4-integration-final.json`` and asserted
equal, so a new dissent stops the next commit instead of the next baseline.
It is not a tolerance and not a waiver — the pinned list names every member.

Reading a receipt's leaf address is the part that has to be right.  Three
schemas are in the tree: a string under ``leaf_path``, a string under ``leaf``,
and an object under either carrying ``path``.  A scan written against one of
them silently misses the other two, which is exactly how this escalation's own
first enumeration read 64 standing dissents where the truth is 51.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = REPO_ROOT / "docs" / "receipts"
LEDGER = RECEIPTS / "escalated-defects-P4-integration-final.json"

ADVERSE_VERDICTS = frozenset({"old_value_correct", "both_wrong"})


def leaf_address(body: dict) -> str | None:
    """The leaf a receipt adjudicates, across all three committed schemas."""
    for key in ("leaf_path", "leaf"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value["path"]
    return None


_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def receipt_date(body: dict) -> str | None:
    """The earliest ISO date this receipt carries, whatever it calls the key.

    Derived rather than listed, for the same reason :func:`leaf_address` reads
    three schemas: a scan written against one spelling silently misses the
    others, and *silently* is the whole problem — an undated dissent is
    treated as cleared by any same-leaf answer, so a receipt whose date this
    function cannot see falls into the population the ledger itself calls the
    rule's weakest.  Reading ``date`` alone put **eleven** spellings in that
    population: ``date``, ``dated``, ``generated``, ``generated_at``,
    ``generated_utc``, ``generated_at_utc``, ``investigated_at``,
    ``investigated_utc_date``, ``adjudicated_at``, ``checked_at``,
    ``produced_at`` and ``created`` are all live in ``docs/receipts/``.

    So the rule is a *value* rule and not a key rule: any top-level string
    beginning with an ISO date is one, and the earliest is the receipt's.  A
    twelfth spelling is read the day somebody writes it.  ``generated_by`` and
    the other author fields are excluded by the same rule rather than by a
    block list — a name is not a date.
    """
    found = sorted(
        match.group(1)
        for value in body.values()
        if isinstance(value, str) and (match := _ISO_DATE.match(value))
    )
    return found[0] if found else None


def oracle_receipts() -> dict[str, dict]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RECEIPTS.glob("oracle-*.json"))
    }


def standing_dissents(receipts: dict[str, dict]) -> list[str]:
    """Adverse verdicts no later same-leaf ``new_value_correct`` receipt answers.

    A supersession that *predates* the dissent it supposedly answers does not
    supersede: that is what a dissent filed against an already-pinned leaf
    looks like, and it is the shape the R-35 pass found at the Phase 4
    boundary.  An undated dissent is treated as cleared by any same-leaf
    answer, because nothing orders it — the ledger records how large that
    population is rather than pretending the rule is total.
    """
    by_leaf: dict[str | None, list[dict]] = defaultdict(list)
    for body in receipts.values():
        by_leaf[leaf_address(body)].append(body)

    standing = []
    for name, body in sorted(receipts.items()):
        if body.get("verdict") not in ADVERSE_VERDICTS:
            continue
        answers = [
            other
            for other in by_leaf[leaf_address(body)]
            if other.get("verdict") == "new_value_correct"
        ]
        if not answers:
            standing.append(name)
            continue
        dissent_date = receipt_date(body)
        if dissent_date is None:
            continue
        if not any((receipt_date(other) or "") >= dissent_date for other in answers):
            standing.append(name)
    return standing


def entry() -> dict:
    body = json.loads(LEDGER.read_text(encoding="utf-8"))
    return body["defects"][0]


class TestEveryReceiptIsReadable:
    """A receipt the scan cannot address is a dissent the scan cannot count."""

    def test_every_oracle_receipt_carries_a_leaf_address(self):
        unreadable = [
            name
            for name, body in oracle_receipts().items()
            if leaf_address(body) is None
        ]
        assert unreadable == []

    def test_every_oracle_receipt_carries_a_verdict_from_the_closed_set(self):
        allowed = ADVERSE_VERDICTS | {"new_value_correct"}
        rogue = {
            name: body.get("verdict")
            for name, body in oracle_receipts().items()
            if body.get("verdict") not in allowed
        }
        assert rogue == {}


class TestTheStandingSetIsPinned:
    """The escalation's own reproducer, run as a gate."""

    def test_the_standing_set_is_exactly_the_pinned_one(self):
        assert standing_dissents(oracle_receipts()) == entry()["standing_receipts"]

    def test_the_recorded_counts_reproduce(self):
        receipts = oracle_receipts()
        measured = entry()["measured"]
        adverse = [
            name
            for name, body in receipts.items()
            if body.get("verdict") in ADVERSE_VERDICTS
        ]
        assert measured["oracle_receipts"] == len(receipts)
        assert measured["adverse_verdicts"] == len(adverse)
        assert measured["standing"] == len(entry()["standing_receipts"])
        families = Counter(
            name.split("-leaf")[0] for name in entry()["standing_receipts"]
        )
        assert measured["by_family"] == dict(sorted(families.items()))

    def test_a_new_adverse_verdict_would_turn_the_gate_red(self):
        """R-05's permanent negative: the seam is one injected receipt."""
        receipts = dict(oracle_receipts())
        receipts["oracle-INJECTED-leaf0.json"] = {
            "leaf_path": "/coupled_scenarios/nowhere/combat/injected",
            "verdict": "old_value_correct",
            "date": "2099-01-01",
        }
        assert standing_dissents(receipts) != entry()["standing_receipts"]

    def test_a_supersession_that_predates_its_dissent_does_not_clear_it(self):
        """The clause that puts the Phase 4 member in the list, isolated."""
        receipts = {
            "oracle-X-leaf0.json": {
                "leaf": "/a/b",
                "verdict": "new_value_correct",
                "date": "2026-01-01",
            },
            "oracle-X-leaf1.json": {
                "leaf": "/a/b",
                "verdict": "old_value_correct",
                "date": "2026-02-01",
            },
        }
        assert standing_dissents(receipts) == ["oracle-X-leaf1.json"]
        receipts["oracle-X-leaf0.json"]["date"] = "2026-03-01"
        assert standing_dissents(receipts) == []


class TestThePhase4MemberIsDescribedAsItIs:
    """The one standing dissent this phase owns, joined to its own facts."""

    def test_the_named_receipt_is_in_the_standing_set_and_says_what_the_entry_says(
        self,
    ):
        member = entry()["the_phase_4_member"]
        assert member["receipt"] in entry()["standing_receipts"]
        body = json.loads((RECEIPTS / member["receipt"]).read_text(encoding="utf-8"))
        assert body["verdict"] == member["verdict"]
        assert leaf_address(body) == member["leaf"]

    def test_its_leaf_is_a_membership_transition_the_amendment_adjudicates_by_citation(
        self,
    ):
        """``absent_to_value`` on a block that did not exist: no verdict is owed."""
        member = entry()["the_phase_4_member"]
        body = json.loads((RECEIPTS / member["receipt"]).read_text(encoding="utf-8"))
        assert str(body["old_value"]).startswith("<absent>")
        citations = [
            RECEIPTS / f"expected-golden-diff-P4-S9-{name}.json"
            for name in ("dispositions", "coverage", "score-map")
        ]
        assert all(path.exists() for path in citations)

    def test_the_entry_is_open_dated_and_gated(self):
        assert entry()["dated"]
        assert json.loads(LEDGER.read_text(encoding="utf-8"))["retired"] == []
        assert json.loads(LEDGER.read_text(encoding="utf-8"))["gate"] == (
            "tests/test_standing_oracle_dissents.py"
        )


@pytest.mark.parametrize("name", entry()["standing_receipts"])
def test_every_pinned_standing_receipt_exists(name):
    """A pinned list that names a file that is gone is a stale waiver."""
    assert (RECEIPTS / name).exists()


class TestTheDateIsReadHoweverItIsSpelled:
    """The supersession rule orders receipts, so it has to be able to read them.

    An undated dissent is cleared by any same-leaf answer, which makes "this
    receipt looks undated" the quietest way to clear one.  Before the value
    rule, eleven live spellings looked undated.
    """

    def test_the_spellings_in_the_tree_are_all_read(self):
        """Every key an oracle receipt dates itself under, enumerated live."""
        spellings = {
            key
            for body in oracle_receipts().values()
            for key, value in body.items()
            if isinstance(value, str) and _ISO_DATE.match(value)
        }
        assert len(spellings) >= 11, spellings
        assert {"date", "generated_at", "generated_utc"} <= spellings
        for body in oracle_receipts().values():
            for key, value in body.items():
                if isinstance(value, str) and _ISO_DATE.match(value):
                    assert receipt_date(body) is not None, key

    def test_a_novel_spelling_still_orders_a_dissent(self):
        """The seam: a receipt dated under a key nobody has used yet."""
        receipts = {
            "oracle-X-leaf0.json": {
                "leaf": "/a/b",
                "verdict": "new_value_correct",
                "date": "2026-01-01",
            },
            "oracle-X-leaf1.json": {
                "leaf": "/a/b",
                "verdict": "old_value_correct",
                "signed_off_on": "2026-02-01T09:00:00Z",
            },
        }
        assert standing_dissents(receipts) == ["oracle-X-leaf1.json"]

    def test_an_author_field_is_not_a_date(self):
        """``generated_by`` and its kin are excluded by the rule, not by a list."""
        assert receipt_date({"generated_by": "Opus 5", "verdict": "x"}) is None

    def test_the_undated_population_is_the_one_the_ledger_records(self):
        """The rule's weakest ground, counted rather than described."""
        receipts = oracle_receipts()
        undated = [
            name for name, body in receipts.items() if receipt_date(body) is None
        ]
        assert str(len(undated)) in entry()["measured"]["rule"]
        assert str(len(receipts)) in entry()["measured"]["rule"]
