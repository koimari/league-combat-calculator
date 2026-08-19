"""The residue of runbook criterion 11's first clause, as startable work.

``docs/receipts/verify-ledger.json``'s coverage block made the clause
measurable: it derives the campaign's slice groups from commit subjects and
records, group by group, whether an R-35 answer exists in the ledger.  What it
records for the residue is a number.  A number is what the clause needed and
it is not what the residue needed, because the ledger's own
``why_the_residue_cannot_be_closed_retroactively`` says the residue closes
"by re-running R-35 over the historical ranges as its own scheduled work with
its own briefs" -- and no range and no brief existed anywhere in the tree.  So
the one open question the campaign routes to its owner --
``rulings-owed.json``'s ``whether_criterion_11s_first_clause_binds_the_campaign_backwards``
-- offered a branch nobody could price beyond "some sixty passes".

This is that branch, priced and prepared.  One row per residue slice group,
every field of it derived from the tree rather than authored: the commits the
group actually spans, the plan documents that mention its tag and therefore
carry the completion criteria a brief has to quote, and whether the group's
own commit bodies cite an R-35 answer.  The brief itself is not restated here
at all -- it is read from R-35 in the runbook at run time, so a backlog can
never hand a verifier a weaker brief than the ruling states.

**What this file is not.**  It is not an answer to the owed ruling, and
nothing in it reads on whether the clause binds backwards.  It is not a
recorded R-35 answer and it may not be mistaken for one: every row here is a
pass that has *not* run.  And it does not shrink the denominator -- the row
set is asserted equal to the ledger's own residue list, so preparing the work
cannot become a way of redefining it.  What it removes is the state the
sign-off review found: a branch of an owed ruling whose cost was an estimate
and whose work nobody could begin.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts"
LEDGER_PATH = RECEIPTS_DIR / "verify-ledger.json"
BACKLOG_PATH = RECEIPTS_DIR / "verify-backlog.json"
RUNBOOK_PATH = REPO_ROOT / "docs" / "plans" / "silent-failure-runbook.md"
PLANS_DIR = REPO_ROOT / "docs" / "plans"

#: The commit the campaign branched from -- the same left-hand end the ledger's
#: own derivation uses, and not a figure about anything.
CAMPAIGN_BASE = "584071e"
# The campaign is closed at this tip; a later campaign carries its own receipt.
CAMPAIGN_TIP = "7e1de9e"

#: The trailing parenthetical every lane stamps on a commit subject.  Spelled
#: the same way the ledger spells it, because the two populations must be the
#: same population or the backlog is preparing work for a different clause.
TRAILING_TAG = re.compile(r"\(([^()]*)\)\s*$")

#: Where R-35's brief lives.  The backlog reads it; it never restates it.
R35_HEADING = "**R-35 —"

_UNIT, _RECORD = chr(31), chr(30)


class BacklogError(RuntimeError):
    """The backlog does not say what the tree says."""


@dataclass(frozen=True, slots=True)
class Commit:
    """One campaign commit, as the backlog needs it."""

    subject: str


def _log(fmt: str) -> str:
    """``git log`` over the campaign range, oldest first."""
    return subprocess.run(
        ["git", "log", "--reverse", f"--format={fmt}", f"{CAMPAIGN_BASE}..HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout


def tag_of(subject: str) -> str | None:
    """The slice-group tag a commit subject carries, or ``None``."""
    match = TRAILING_TAG.search(subject)
    if match is None:
        return None
    return match.group(1).split(",")[0].strip()


def commits_by_tag(pending: Sequence[str] = ()) -> dict[str, list[Commit]]:
    """Every campaign commit, grouped by the slice tag its subject carries.

    Oldest first within a group.  Commits are carried by **subject** and not
    by sha, for the reason the ledger already gives for its own citation
    list: this file is committed *inside* the commit a sha would point at, so
    a sha goes stale the moment that commit is amended or rebased, and a
    backlog that goes red on a rebase is a backlog lanes learn to regenerate
    without reading.  A subject survives both, and it is what
    ``git log --grep`` takes.

    ``pending`` is the subjects of commits about to be made.  A row for the
    slice group that lands this file cannot be derived from a history that
    does not yet hold it; ``--pending`` is how it is written, and ``--check``
    re-derives it from the tree the moment the commit exists, so a pending
    subject that never lands -- or lands reworded -- fails the gate.
    """
    grouped: dict[str, list[Commit]] = {}
    for chunk in _log(f"%h{_UNIT}%s{_RECORD}").split(_RECORD):
        chunk = chunk.strip()
        if not chunk:
            continue
        _sha, subject = chunk.split(_UNIT, 1)
        tag = tag_of(subject)
        if tag is None:
            continue
        grouped.setdefault(tag, []).append(Commit(subject))
    for subject in pending:
        tag = tag_of(subject)
        if tag is None:
            raise BacklogError(
                f"pending subject {subject!r} carries no trailing slice tag; a "
                "commit with no tag is a hole in the convention and cannot be "
                "prepared as a slice group"
            )
        grouped.setdefault(tag, []).append(Commit(subject))
    return grouped


def r35_brief() -> str:
    """R-35's brief, read from the runbook rather than copied into a receipt.

    The blockquote immediately after R-35's heading.  Reading it means a
    backlog row can never quote a brief the ruling does not say -- and means
    the gate over this file fails if somebody edits the brief in one place.
    """
    lines = RUNBOOK_PATH.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(R35_HEADING):
            continue
        quoted: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.startswith(">"):
                quoted.append(candidate.lstrip("> ").rstrip())
            elif quoted:
                break
        if quoted:
            return " ".join(part for part in quoted if part)
    raise BacklogError(
        "R-35's brief is not readable from the runbook; the backlog refuses to "
        "invent one, because a brief a verifier is handed is the ruling's text "
        "and not a receipt's paraphrase"
    )


def tag_pattern(tag: str) -> re.Pattern[str]:
    """A locator match for a slice tag inside a plan document."""
    return re.compile(rf"(?<![\w.\-/]){re.escape(tag)}(?![\w.\-/])")


def documents_mentioning(tag: str) -> tuple[str, ...]:
    """Which plan documents name this tag, repo-relative and sorted.

    A locator and deliberately not an authority: a brief quotes the slice's
    *stated completion criteria*, and finding them is the spawning agent's
    step.  What a machine can settle is which documents are worth opening,
    and a group whose tag appears in none of them is a real finding rather
    than an omission -- it says the criteria live in a commit body.
    """
    pattern = tag_pattern(tag)
    found = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(PLANS_DIR.glob("*.md"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    return tuple(found)


def rows(residue: Sequence[str], pending: Sequence[str] = ()) -> dict[str, Any]:
    """One prepared row per residue slice group."""
    grouped = commits_by_tag(pending)
    cited = set(_ledger()["coverage"]["slice_groups_citing_a_verdict_in_a_commit_body"])
    out: dict[str, dict[str, Any]] = {}
    for tag in sorted(residue):
        commits = grouped.get(tag)
        if not commits:
            raise BacklogError(
                f"slice group {tag!r} is in the ledger's residue and no commit "
                "in the campaign range carries it; the two populations have "
                "drifted apart"
            )
        out[tag] = {
            "commit_count": len(commits),
            "subjects": [commit.subject for commit in commits],
            "criteria_documents": list(documents_mentioning(tag)),
            "cites_an_r35_answer_in_a_commit_body": tag in cited,
        }
    return out


def _ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def backlog(pending: Sequence[str] = ()) -> dict[str, Any]:
    """The whole artifact, derived."""
    coverage = _ledger()["coverage"]
    residue = list(coverage["slice_groups_without_one"])
    prepared = rows(residue, pending)
    return {
        "artifact": "verify_backlog",
        "rule": (
            "The residue of runbook criterion 11's first clause, prepared as "
            "work somebody can start. One row per slice group with no recorded "
            "R-35 answer in docs/receipts/verify-ledger.json: the commits it "
            "spans, the plan documents that carry its stated completion "
            "criteria, and whether its own commit bodies cite an R-35 answer. "
            "The brief is not here -- it is read from R-35 in the runbook, "
            "which stays its one home."
        ),
        "gate": "tests/test_verify_backlog.py",
        "what_this_is_not": (
            "It is not an answer to the owed ruling "
            "whether_criterion_11s_first_clause_binds_the_campaign_backwards, "
            "and no row reads on whether the clause binds backwards. It is not "
            "a recorded R-35 answer: every row is a pass that has NOT run, and "
            "reading it as coverage would be the unverifiable claim about the "
            "past this campaign outlaws. And it does not shrink the "
            "denominator -- the row set is asserted equal to the ledger's own "
            "residue list, so preparing the work cannot become a way of "
            "redefining it."
        ),
        "why_a_lane_may_write_this": (
            "Every field is read from the commit tree, from the committed "
            "ledger, or from R-35 itself. Naming the commits a slice spans and "
            "the documents its criteria live in is a statement about the "
            "QUESTION a verifier would be handed, never about the answer -- "
            "the same line the standing-dissent docket draws for an "
            "investigator's brief."
        ),
        "how_a_row_is_discharged": (
            "A fresh read-only agent that has not read the implementation plan "
            "is handed R-35's brief with this row's commit range and the "
            "criteria quoted out of its criteria_documents. What it returns is "
            "recorded as a pass in verify-ledger.json, and this row goes away "
            "because the ledger's residue list no longer holds the tag."
        ),
        "how_to_enumerate_a_range": (
            "git log --reverse --format='%h %s' 584071e..7e1de9e, keeping the "
            "commits whose subject's trailing parenthetical begins with the "
            "group's tag. The rows carry subjects rather than shas on purpose: "
            "this file is committed inside the commit a sha would point at, so "
            "a sha goes stale on the first amend or rebase, and a gate that "
            "goes red on a rebase is a gate lanes learn to regenerate without "
            "reading. The subjects are exact and git log --grep takes them."
        ),
        "brief_source": {
            "ruling": "R-35",
            "document": RUNBOOK_PATH.relative_to(REPO_ROOT).as_posix(),
            "text": r35_brief(),
            "why_it_is_read_and_not_stored": (
                "A brief copied into a receipt is a second home for the "
                "ruling's own words, and the weakening nobody would notice is "
                "a brief that quietly drops 'Do not read the implementation "
                "plan'. Reading it means this file cannot disagree with R-35."
            ),
        },
        "prepared_passes": len(prepared),
        "of_which_cite_an_r35_answer_in_a_commit_body": sum(
            1
            for row in prepared.values()
            if row["cites_an_r35_answer_in_a_commit_body"]
        ),
        "groups": prepared,
    }


def check(committed: Mapping[str, Any] | None = None) -> list[str]:
    """Every way the committed backlog can stop being true of the tree.

    ``committed`` is R-05's seam: a caller hands in a mutated artifact and the
    check reports on that instead of the file, so the gate has a red it can
    reproduce on demand rather than one demonstrated once in development.
    """
    if committed is None:
        if not BACKLOG_PATH.exists():
            return [f"{BACKLOG_PATH.name} is not committed; run --write"]
        committed = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    fresh = backlog()
    failures: list[str] = []
    if set(committed.get("groups", {})) != set(fresh["groups"]):
        failures.append(
            "the committed backlog covers a different set of slice groups than "
            "the ledger's residue; a prepared row that outlives its residue "
            "entry, or a residue entry with no prepared row, is the gap "
            "reopening under a file that says it is closed"
        )
    for tag, row in fresh["groups"].items():
        recorded = committed.get("groups", {}).get(tag)
        if recorded != row:
            failures.append(f"slice group {tag!r}: committed row differs from derived")
    if committed.get("brief_source", {}).get("text") != fresh["brief_source"]["text"]:
        failures.append(
            "the committed brief differs from R-35's text in the runbook; a "
            "backlog may not hand a verifier a brief the ruling does not state"
        )
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """``--write`` regenerates the receipt; ``--check`` gates it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the receipt")
    parser.add_argument("--check", action="store_true", help="fail on any drift")
    parser.add_argument(
        "--pending",
        action="append",
        default=[],
        metavar="SUBJECT",
        help="the subject of a commit about to be made, so the row for the "
        "slice group that lands this file can be written before it exists",
    )
    args = parser.parse_args(argv)
    if args.write:
        BACKLOG_PATH.write_text(
            json.dumps(backlog(args.pending), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {BACKLOG_PATH.relative_to(REPO_ROOT).as_posix()}")
        return 0
    failures = check()
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
