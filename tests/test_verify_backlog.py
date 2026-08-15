"""The prepared-work gate over criterion 11's residue.

``verify-ledger.json`` grades the residue; ``verify-backlog.json`` prepares
it.  Preparation is the half that can go wrong quietly, in three ways this
file exists to make loud.

The row set can drift from the residue it prepares -- a prepared row that
outlives its residue entry reads as work still owed when it is not, and a
residue entry with no row reads as prepared when nobody can start it.  The
brief can weaken: the one sentence a hurried backlog would drop is *do not
read the implementation plan*, and a brief without it produces an answer that
is not an R-35 answer at all.  And a backlog can be misread as coverage,
which is the unverifiable claim about the past the campaign outlaws -- so the
artifact says in its own words that every row is a pass that has not run, and
this file pins that it says so.

R-05: the last test is the red this gate can reproduce on demand, through the
seam ``check()`` takes rather than through a commit somebody has to remember.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_backlog  # noqa: E402  pylint: disable=wrong-import-position

LEDGER = ROOT / "docs" / "receipts" / "verify-ledger.json"
BACKLOG = ROOT / "docs" / "receipts" / "verify-backlog.json"


def backlog() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(BACKLOG.read_text(encoding="utf-8"))


def residue() -> list[str]:
    """The ledger's own list of slice groups with no recorded answer."""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    return list(ledger["coverage"]["slice_groups_without_one"])


def test_the_backlog_declares_what_it_is_and_what_gates_it() -> None:
    block = backlog()
    assert block["artifact"] == "verify_backlog"
    assert block["gate"] == "tests/test_verify_backlog.py"


def test_the_committed_backlog_matches_the_tree() -> None:
    """The whole instrument, run as the gate a reader would run."""
    assert verify_backlog.check() == []


def test_the_row_set_is_the_ledger_s_residue_and_not_a_second_list() -> None:
    """Preparing the work may not become a way of redefining it."""
    assert set(backlog()["groups"]) == set(residue())
    assert backlog()["prepared_passes"] == len(residue())


def test_every_row_names_commits_the_tree_holds_under_its_own_tag() -> None:
    """A range a reader cannot open is a range nobody can verify against."""
    in_tree = verify_backlog.commits_by_tag()
    for tag, row in backlog()["groups"].items():
        assert row["commit_count"] == len(row["subjects"]), tag
        assert row["subjects"] == [commit.subject for commit in in_tree[tag]], tag
        for subject in row["subjects"]:
            assert verify_backlog.tag_of(subject) == tag


def test_the_backlog_says_how_a_range_is_enumerated() -> None:
    """Subjects are the address; the instruction that turns them into a range."""
    instruction = backlog()["how_to_enumerate_a_range"]
    assert "git log" in instruction
    assert verify_backlog.CAMPAIGN_BASE in instruction


def test_every_criteria_document_exists_and_names_the_tag() -> None:
    """The locator half: a document worth opening, checked to be one."""
    for tag, row in backlog()["groups"].items():
        for relative in row["criteria_documents"]:
            path = ROOT / relative
            assert path.exists(), (tag, relative)
            pattern = verify_backlog.tag_pattern(tag)
            assert pattern.search(path.read_text(encoding="utf-8")), (tag, relative)


def test_the_brief_is_r35s_own_text_and_keeps_its_load_bearing_sentence() -> None:
    """The clause a weakened brief drops first, pinned by name."""
    brief = backlog()["brief_source"]
    assert brief["ruling"] == "R-35"
    assert brief["text"] == verify_backlog.r35_brief()
    assert "Do not read the implementation plan" in brief["text"]
    assert "commit range" in brief["text"]


def test_the_citation_flag_agrees_with_the_ledger() -> None:
    """A row may not claim a citation state the ledger's derivation denies."""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    cited = set(ledger["coverage"]["slice_groups_citing_a_verdict_in_a_commit_body"])
    for tag, row in backlog()["groups"].items():
        assert row["cites_an_r35_answer_in_a_commit_body"] == (tag in cited), tag
    assert backlog()["of_which_cite_an_r35_answer_in_a_commit_body"] == len(
        cited & set(backlog()["groups"])
    )


def test_the_backlog_refuses_to_be_read_as_coverage() -> None:
    """Every row is a pass that has not run, said where a reader is."""
    block = backlog()
    assert "not a recorded R-35 answer" in block["what_this_is_not"]
    assert "has NOT run" in block["what_this_is_not"]
    assert block["how_a_row_is_discharged"]
    # No row carries a verdict *field*.  Quoted commit subjects may of course
    # contain the word -- the check is on the row's schema, because a backlog
    # that grew a verdict column is a backlog somebody has started filling in.
    for row in block["groups"].values():
        assert "verdict" not in row
        assert not any(key.startswith("verdict") for key in row)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("drop_a_group", "different set of slice groups"),
        ("weaken_the_brief", "brief the ruling does not state"),
        ("move_a_row", "committed row differs from derived"),
    ],
)
def test_the_gate_has_a_red_it_can_reproduce(mutation: str, expected: str) -> None:
    """R-05: the check fails on command, through its own seam."""
    mutated = copy.deepcopy(backlog())
    if mutation == "drop_a_group":
        mutated["groups"].pop(sorted(mutated["groups"])[0])
    elif mutation == "weaken_the_brief":
        mutated["brief_source"]["text"] = mutated["brief_source"]["text"].replace(
            "Do not read the implementation plan. ", ""
        )
    else:
        first = sorted(mutated["groups"])[0]
        mutated["groups"][first]["commit_count"] += 1
    failures = verify_backlog.check(mutated)
    assert any(expected in failure for failure in failures), failures
