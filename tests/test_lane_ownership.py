"""Runbook criterion 12, made checkable outside the plan documents.

The criterion says the two-lanes-live rule and the (file, symbol) ownership
rule are "checkable from the map plus the active worktree list".  The map
lived only in a section of the runbook, and an R-35 verifier -- whose brief
forbids reading the plan -- reported the criterion **unverifiable** rather
than met.  Unverifiable is not a verdict a campaign gets to bank.

So the map is committed at ``docs/receipts/lane-ownership.json``, and this
file is what stops it from being a second copy that drifts: the lane set and
the three symbol-shared files are read out of the runbook table and asserted
equal to the artifact's, the ranges are resolved against git, and the actual
writers of those three files are derived from the tree and asserted equal to
the declared owners **plus** the divergences the artifact records.  A writer
nobody declared is a failure here rather than a silence.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "docs" / "receipts" / "lane-ownership.json"
RUNBOOK = ROOT / "docs" / "plans" / "silent-failure-runbook.md"
CAMPAIGN_BASE = "584071e"


def _artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout


def _shas(rev_range: str) -> list[str]:
    return _git("log", "--format=%h", rev_range).split()


def _runbook_lane_rows() -> dict[str, str]:
    """The ownership table's lane ids and agents, read from the runbook.

    Declaration and derivation side by side (D-98's shape): the artifact is
    the machine-readable copy, and this is the assertion that it is a copy of
    *that* table and not of somebody's memory of it.
    """
    rows: dict[str, str] = {}
    for line in RUNBOOK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*(L\d|X)\s*\|\s*`([^`]+)`\s*\|", line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def test_the_artifact_holds_every_lane_the_runbook_table_declares() -> None:
    declared = _runbook_lane_rows()
    recorded = {row["lane"]: row["agent"] for row in _artifact()["lanes"]}
    assert recorded == declared


def test_every_declared_range_resolves_and_the_chain_is_contiguous() -> None:
    """The ranges are the campaign, once, with no gap and no overlap."""
    lanes = _artifact()["lanes"]
    for row in lanes:
        base, _, tip = row["range"].partition("..")
        assert _git("rev-parse", "--verify", base).strip(), row["lane"]
        assert _git("rev-parse", "--verify", tip).strip(), row["lane"]
    for earlier, later in zip(lanes, lanes[1:]):
        assert earlier["range"].split("..")[1] == later["range"].split("..")[0]
    assert lanes[0]["range"].startswith(CAMPAIGN_BASE)
    assert lanes[-1]["range"].endswith("HEAD")

    covered = [sha for row in lanes for sha in _shas(row["range"])]
    assert sorted(covered) == sorted(_shas(f"{CAMPAIGN_BASE}..HEAD"))
    assert len(covered) == len(set(covered)), "a commit is claimed by two lanes"


def test_no_commit_is_claimed_by_more_lanes_than_the_map_allows() -> None:
    """The two-lanes-live bound, as far as a linear history can carry it.

    R-34 rules integration as rebase-then-cherry-pick and never merge, so
    concurrency is not in the graph; what is in the graph is which lane owns
    each commit, and the artifact says a commit belongs to exactly one.
    """
    artifact = _artifact()
    owners: dict[str, set[str]] = {}
    for row in artifact["lanes"]:
        for sha in _shas(row["range"]):
            owners.setdefault(sha, set()).add(row["lane"])
    assert max(len(lanes) for lanes in owners.values()) <= artifact["max_lanes_live"]


def _lane_of_commit() -> dict[str, str]:
    return {
        sha: row["lane"] for row in _artifact()["lanes"] for sha in _shas(row["range"])
    }


@pytest.mark.parametrize(
    "shared",
    _artifact()["shared_by_symbol"],
    ids=[row["file"] for row in _artifact()["shared_by_symbol"]],
)
def test_every_writer_of_a_symbol_shared_file_is_declared(shared) -> None:
    """The check the criterion always wanted and no artifact could run.

    Derived: which lanes actually wrote each of the three files, read from
    the tree.  Declared: the map's owners plus the divergences the artifact
    records by name.  Every real writer must be one of those, so a lane that
    starts writing one of these files without a row is a red rather than a
    fact nobody noticed.  The containment is one-way on purpose: ownership is
    permission, not obligation, and L1 declares consumers in
    ``ability_spec.py`` it never needed to write.
    """
    artifact = _artifact()
    lane_of = _lane_of_commit()
    touched = _git("log", "--format=%h", f"{CAMPAIGN_BASE}..HEAD", "--", shared["file"])
    wrote = {lane_of[sha] for sha in touched.split()}
    assert wrote, shared["file"]

    undeclared = {
        row["lane"]
        for row in artifact["writers_the_map_does_not_list"]
        if row["file"] == shared["file"]
    }
    assert wrote <= set(shared["declared_owners"]) | undeclared
    assert undeclared <= wrote, "a divergence row names a lane that never wrote"


def test_each_recorded_divergence_names_real_commits_that_touched_the_file() -> None:
    """A divergence row is evidence, not an apology."""
    lane_of = _lane_of_commit()
    for row in _artifact()["writers_the_map_does_not_list"]:
        touched = set(
            _git(
                "log", "--format=%h", f"{CAMPAIGN_BASE}..HEAD", "--", row["file"]
            ).split()
        )
        assert set(row["commits"]) <= touched, row["file"]
        for sha in row["commits"]:
            assert lane_of[sha] == row["lane"], sha
        assert row["why_it_is_not_a_criterion_12_violation"].strip()


def test_the_three_symbol_shared_files_are_the_ones_the_runbook_names() -> None:
    """Criterion 12 names them; the artifact may not quietly hold a fourth."""
    recorded = {
        row["file"].rsplit("/", 1)[-1] for row in _artifact()["shared_by_symbol"]
    }
    assert recorded == {"pipeline.py", "ability_spec.py", "syndra.py"}
    text = RUNBOOK.read_text(encoding="utf-8")
    for name in ("`pipeline.py`", "`ability_spec.py`", "`champions/syndra.py`"):
        assert name in text
