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


#: The trailing parenthetical every lane stamps on a commit subject.
TRAILING_TAG = r"\(([^()]*)\)\s*$"

#: What an R-35 citation in a commit body has to name to count.
MECHANISM_NAMES = r"R-35|verify-[A-Za-z0-9.\-/]+|verifier|sign-?off"
VERDICT_WORDS = r"\bNOT DISCHARGED\b|\bDISCHARGED\b|\bverdict\b"


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
    pattern = re.compile(TRAILING_TAG)
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


def _groups_citing_a_verdict_in_a_commit_body() -> list[str]:
    """Slice groups whose own commits record an R-35 verdict.

    Names rather than shas, and the reason is the one this ledger keeps
    running into: it is committed *inside* the commit it would be recording,
    so a sha here is stale the moment that commit is amended or rebased.

    A third coverage state, derived rather than authored, and deliberately
    weaker than a recorded verdict: a commit body is the *lane's*
    transcription of the verifier's answer, not the verifier's artifact.  It
    is surfaced anyway because "a citation somebody can go and read" and
    "nothing at all" are different states of one clause, and collapsing them is what made
    a ledger holding one pass and a ledger holding forty look alike to every
    gate.

    The rule is a conjunction so a passing mention cannot qualify: the body
    must name the mechanism -- R-35, a ``verify-`` agent, a verifier or a
    sign-off -- **and** carry a verdict word from R-35's own brief.
    """
    unit, record = chr(31), chr(30)
    out = subprocess.run(
        ["git", "log", f"--format=%h{unit}%s{unit}%b{record}", "584071e..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout
    tag_pattern = re.compile(TRAILING_TAG)
    mechanism = re.compile(MECHANISM_NAMES, re.I)
    verdict = re.compile(VERDICT_WORDS, re.I)
    cited: list[str] = []
    for chunk in out.split(record):
        chunk = chunk.strip()
        if not chunk:
            continue
        _sha, subject, commit_body = chunk.split(unit, 2)
        match = tag_pattern.search(subject)
        if match is None:
            continue
        tag = match.group(1).split(",")[0].strip()
        if tag in cited:
            continue
        if mechanism.search(commit_body) and verdict.search(commit_body):
            cited.append(tag)
    return sorted(cited)


#: A bare integer -- not the 35 of ``R-35``, not the 11 of a criterion id, not a
#: path fragment.  What it matches is a count somebody wrote down.
_BARE_INTEGER = re.compile(r"(?<![\w.\-/])\d+")


def _undated_counts(note: str) -> list[str]:
    """Sentences of ``note`` that state a count before any date is in force."""
    offending: list[str] = []
    dated = False
    for sentence in note.split(". "):
        if "2026-" in sentence:
            dated = True
        if _BARE_INTEGER.search(sentence) and not dated:
            offending.append(sentence)
    return offending


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

    def test_the_citation_state_is_derived_and_not_authored(self) -> None:
        """The third state: a verdict a reader can open, in a commit body.

        Recorded with its sha so the citation is a link rather than a claim,
        and re-derived here so the ledger cannot list a group whose commits
        say nothing.  It is a strict subset of the groups with no verdict in
        this ledger: a citation is the lane's transcription of a verifier's
        answer and is not the artifact the clause asks for.
        """
        cited = self.coverage["slice_groups_citing_a_verdict_in_a_commit_body"]
        assert cited == _groups_citing_a_verdict_in_a_commit_body()
        # Names and not shas: a sha is a locator, and the ledger sits inside
        # the commit whose sha it would have to record, so any rewrite of that
        # commit would leave the file describing a commit that no longer
        # exists.  ``git log --grep`` finds a named group's commits.
        # A group can be both: the pass recorded here also cited itself in the
        # commit that landed it.  What the residue subtracts is the overlap,
        # so a citation never counts as a verdict and never double-counts one.
        assert set(cited) <= set(self.coverage["slice_groups_without_one"]) | set(
            self.coverage["slice_groups_with_a_verdict_in_this_ledger"]
        )
        assert self.coverage["residue_with_no_verdict_anywhere"] == len(
            set(self.coverage["slice_groups_without_one"]) - set(cited)
        )

    def test_the_block_says_what_it_refuses_to_do(self) -> None:
        """It does not reconstruct a verdict, and says so where a reader is."""
        assert (
            "does not reconstruct a verdict"
            in self.coverage["what_this_block_does_not_do"]
        )
        assert self.coverage["why_the_residue_cannot_be_closed_retroactively"].strip()

    def test_every_count_the_residue_note_states_is_dated(self) -> None:
        """The note may reason freely; it may not carry an undated count.

        Round 129's first finding is that this note went on stating a population
        -- "10 of the groups ... cite one in a commit body", "60-odd fresh R-35
        passes" -- that the backfill had already made false, and that nothing in
        the tree would catch it.  The counters beside it are derived and gated;
        the note is prose, and prose that restates a derived number is the second
        home criterion 4 exists to forbid.

        So the rule is the weakest one that would have caught it: a count in
        this note must sit inside a **dated clause**.  The note is an undated
        preamble -- the reasoning, which has no number in it and needs none --
        followed by clauses each opening with the date it was measured on.  A
        count a reader can date is a reading; a count in the preamble is a claim
        about now, and about now the derived counters beside it are the
        authority.

        What it does not catch, said plainly rather than left to be discovered:
        a count appended to an already-dated clause takes that clause's date.
        That is still a date a reader can place, which is the property being
        gated; a stronger rule would have to know which sentence arrived last.
        """
        note = self.coverage["why_the_residue_cannot_be_closed_retroactively"]
        assert _undated_counts(note) == []

    def test_the_dated_count_rule_has_a_red_it_can_reproduce(self) -> None:
        """R-05, on the shape the finding actually had: an undated count."""
        note = self.coverage["why_the_residue_cannot_be_closed_retroactively"]
        doctored = "Closing those is 60-odd fresh R-35 passes. " + note
        assert _undated_counts(doctored)


def _pass(round_number: int) -> dict:
    return next(
        block for block in ledger()["passes"] if block.get("round") == round_number
    )


@pytest.mark.parametrize(
    "criterion",
    [
        "umbrella-1",
        "umbrella-4",
        "umbrella-7",
        "runbook-2",
        "runbook-11",
        "runbook-12",
    ],
)
def test_the_second_round_answers_every_criterion_it_was_handed(
    criterion: str,
) -> None:
    """The same clause as round 1's, over the pass that followed it.

    Written per round rather than once over all passes: a pass answers the
    criteria *its* verifier returned, and a rule quantified over the union
    would demand round 2 re-answer verdicts round 1 already closed.
    """
    assert criterion in {row["id"] for row in _pass(2)["criteria"]}


def test_every_pass_is_numbered_and_the_numbering_has_no_holes() -> None:
    """Rounds are how two passes over one slice group stay distinguishable."""
    rounds = [block["round"] for block in ledger()["passes"]]
    assert rounds == list(range(1, len(rounds) + 1))


def test_round_two_carries_the_six_findings_its_verifier_returned() -> None:
    """The third clause, per round: documented or reverted, none dropped."""
    findings = _pass(2)["unmentioned_behaviour"]
    assert len(findings) == 6
    assert {row["disposition"] for row in findings} <= set(
        ledger()["disposition_vocabulary"]
    )
    assert any(row["disposition"] == "reverted" for row in findings)
