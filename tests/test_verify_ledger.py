"""The R-35 verdict ledger, gated: a verdict is a row, not a memory.

Runbook criterion 11 has three clauses.  Every slice has a recorded
``verify-<slice>`` verdict; no barrier is crossed with an open
``NOT DISCHARGED``; and every "behaviour the commit bodies do not mention"
finding is either documented or reverted.

The mechanism was real and used all campaign -- commit bodies cite verifier
findings and answer them by name -- but the verdicts lived only in those
bodies, so the first clause could not be checked from the repository at all.
This file checks the ledger that starts fixing that: every row carries a
verdict from the closed set, a disposition from the closed set, at least one
answering commit that exists, and a note.  A row claiming ``fixed`` names an
artifact that is really there.

What it deliberately does **not** assert is that the ledger is complete.  It
is not, the ledger says so in its own words, and a test asserting completeness
over a file that starts mid-campaign would be the claim-outruns-code shape the
campaign exists to remove.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "receipts" / "verify-ledger.json"


def ledger() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def rows() -> list[tuple[str, dict]]:
    """Every criterion row and every finding row, with its pass id."""
    out: list[tuple[str, dict]] = []
    for block in ledger()["passes"]:
        for row in block["criteria"] + block["unmentioned_behaviour"]:
            out.append((block["slice_group"], row))
    return out


def test_the_ledger_declares_what_it_is_and_what_gates_it() -> None:
    block = ledger()
    assert block["artifact"] == "verify_ledger"
    assert block["gate"] == "tests/test_verify_ledger.py"
    assert block["what_this_ledger_does_not_hold"]


def test_every_pass_names_the_commits_it_verified_and_the_ones_that_answered() -> None:
    for block in ledger()["passes"]:
        assert block["dated"] and block["slice_group"]
        assert block["verified_commits"] and block["answered_by"]


def test_every_criterion_row_carries_a_verdict_from_the_closed_set() -> None:
    allowed = set(ledger()["verdict_vocabulary"])
    for block in ledger()["passes"]:
        for row in block["criteria"]:
            assert row["verdict"] in allowed, row["id"]
            assert row["what_was_found"]


def test_every_row_carries_a_disposition_from_the_closed_set() -> None:
    """Documented or reverted, per the criterion's third clause."""
    allowed = set(ledger()["disposition_vocabulary"])
    for _pass, row in rows():
        assert row["disposition"] in allowed, row
        assert row["note"], row


def test_no_row_is_answered_by_a_commit_that_does_not_exist() -> None:
    """A verdict answered by a sha nobody can open is a verdict answered by prose."""
    shas = {sha for _pass, row in rows() for sha in row["answered_at"]}
    shas |= {sha for block in ledger()["passes"] for sha in block["answered_by"]}
    shas |= {sha for block in ledger()["passes"] for sha in block["verified_commits"]}
    assert shas
    for sha in sorted(shas):
        resolved = subprocess.run(
            ["git", "cat-file", "-t", sha],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        assert resolved.returncode == 0, sha
        assert resolved.stdout.strip() == "commit", sha


def test_every_fixed_row_names_an_artifact_that_is_there() -> None:
    """The difference between a fix and a claim is a path a reader can open."""
    for _pass, row in rows():
        if not row["disposition"].startswith("fixed"):
            continue
        artifact = row.get("artifact")
        assert artifact, row
        assert (ROOT / artifact).exists(), artifact


def test_an_open_row_names_where_it_is_carried() -> None:
    """``documented_open`` means documented somewhere, and says where."""
    for _pass, row in rows():
        if row["disposition"] != "documented_open":
            continue
        assert row["note"], row
        artifact = row.get("artifact")
        if artifact:
            assert (ROOT / artifact).exists(), artifact


def test_nothing_is_recorded_as_reverted_without_saying_what() -> None:
    """The other half of the third clause, so the vocabulary is not decorative."""
    for _pass, row in rows():
        if row["disposition"] == "reverted":
            assert row["answered_at"], row


@pytest.mark.parametrize(
    "criterion",
    [
        "umbrella-1",
        "umbrella-4",
        "umbrella-5",
        "umbrella-7",
        "umbrella-8",
        "umbrella-11",
        "runbook-2",
        "runbook-6",
        "runbook-11",
    ],
)
def test_the_campaign_close_pass_answers_every_criterion_it_was_handed(
    criterion: str,
) -> None:
    """A pass that quietly drops one of its verdicts is the shape being checked."""
    block = next(
        item for item in ledger()["passes"] if item["slice_group"] == "campaign-close"
    )
    assert criterion in {row["id"] for row in block["criteria"]}


def _slice_group_tags() -> tuple[list[str], int]:
    """The campaign's own slice labels, read from commit subjects.

    The first element of each subject's trailing parenthetical.  This is a
    derivation, not a second authored list: the population criterion 11's
    first clause quantifies over has to come from the tree or it is whatever
    the ledger says it is.
    """
    out = subprocess.run(
        ["git", "log", "--format=%h\x1f%s\x1e", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    pattern = re.compile(r"\(([^()]*)\)\s*$")
    tags: list[str] = []
    untagged = 0
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        _sha, subject = chunk.split("\x1f", 1)
        match = pattern.search(subject)
        if match is None:
            untagged += 1
            continue
        tag = match.group(1).split(",")[0].strip()
        if tag not in tags:
            tags.append(tag)
    return tags, untagged


class TestTheCoverageBlockIsTheClauseSDenominator:
    """Criterion 11's first clause, given something to quantify over.

    "Every slice has a recorded verdict" bounded nothing a machine could
    read, so a ledger with one pass and a ledger with forty looked the same
    to every gate.  The coverage block is the denominator, derived from the
    campaign's own slice labels; these tests are what stop it from being a
    third authored list.
    """

    @property
    def coverage(self) -> dict:
        return ledger()["coverage"]

    def test_the_two_lists_partition_the_derived_population(self) -> None:
        tags, _untagged = _slice_group_tags()
        recorded = self.coverage["slice_groups_with_a_verdict_in_this_ledger"]
        missing = self.coverage["slice_groups_without_one"]
        assert set(recorded) | set(missing) == set(tags)
        assert not set(recorded) & set(missing)

    def test_a_group_listed_as_covered_really_has_a_pass(self) -> None:
        passes = {block["slice_group"] for block in ledger()["passes"]}
        assert (
            set(self.coverage["slice_groups_with_a_verdict_in_this_ledger"]) == passes
        )

    def test_the_residue_and_the_untagged_count_are_the_measured_ones(self) -> None:
        """The gap is a number, so it cannot grow in silence."""
        tags, untagged = _slice_group_tags()
        assert self.coverage["residue"] == len(
            self.coverage["slice_groups_without_one"]
        )
        assert self.coverage["untagged_commits"] == untagged
        assert self.coverage["residue"] < len(tags)

    def test_the_block_says_what_it_refuses_to_do(self) -> None:
        """It does not reconstruct a verdict, and says so where a reader is."""
        assert (
            "does not reconstruct a verdict"
            in self.coverage["what_this_block_does_not_do"]
        )
        assert self.coverage["why_the_residue_cannot_be_closed_retroactively"].strip()
