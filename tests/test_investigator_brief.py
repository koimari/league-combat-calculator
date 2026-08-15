"""The gate over the re-adjudication brief builder.

One line in the R-15/R-18 amendment does all the work: the pre-change side and
the committed scenario definitions may be quoted, and the post-change side may
not, because the post-change side is the answer.  A hand-assembled brief obeys
that line by care.  These tests are what make the builder obey it by
construction -- the source may not reach the working tree's baseline at all,
and the series it emits is asserted to be the committed pre-change one and
asserted to differ from what the tree holds now.

The other two properties are the ones a convenience script quietly loses.  The
export must stay R-18's, read from the ruling rather than re-spelled, because
a wider export is an oracle that has read the fix.  And a cluster routed to a
ruling must be refused rather than briefed: clause 3 makes a re-run whose
receipt names no defect in the prior brief unwritable, and briefing a cluster
that has no defect to name is oracle shopping with a script in front of it.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import investigator_brief  # noqa: E402  pylint: disable=wrong-import-position

SCRIPT = ROOT / "scripts" / "investigator_brief.py"
DOCKET = ROOT / "docs" / "receipts" / "standing-dissent-docket.json"


def briefable() -> dict[str, dict]:
    """Every docket row carrying a brief -- live in ``clusters`` or ``cleared``.

    Live rows alone were the subject until the 2026-08-15 re-adjudication
    answered the last of them, and a population that empties takes the two
    load-bearing properties below with it: an empty parametrisation is a
    *skip*, and a builder whose pre-change-only guarantee is asserted over
    nothing is a gate that stopped running without saying so.

    A cleared row keeps the brief it was answered under -- the docket closes a
    row by moving it, never by deleting it -- so those rows are committed
    fixtures with real captures behind them, and the guarantee stays exercised
    on real data after the last live row is gone.  The set only grows.
    """
    body = json.loads(DOCKET.read_text(encoding="utf-8"))
    return {
        entry["id"]: entry
        for entry in list(body["clusters"]) + list(body.get("cleared", ()))
        if "brief_for_the_re_adjudication" in entry
    }


def test_every_docketed_cluster_is_startable_ruled_or_already_re_adjudicated() -> None:
    """The docket's own partition, reproduced by the tool that acts on it.

    Three states, not two, since 2026-08-15: a row whose clause-1
    investigation has run and did not clear it owes clause 2's ruled ``src/``
    slice.  The assertion is that each row is in exactly one -- a row in two
    would be a brief offered for a question that has been answered, which is
    the oracle shopping the builder exists to refuse.
    """
    entries = json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
    for entry in entries:
        states = [
            key in entry
            for key in (
                "brief_for_the_re_adjudication",
                "owed_ruling_id",
                "re_adjudication_filed",
            )
        ]
        assert sum(states) == 1, entry["id"]
    assert set(investigator_brief.clusters()) == {entry["id"] for entry in entries}


@pytest.mark.parametrize("cluster_id", sorted(briefable()))
def test_a_briefable_cluster_gets_a_brief_that_poses_the_series(
    cluster_id, monkeypatch
) -> None:
    """Every field clause 1 and clause 3 need, present and non-empty."""
    monkeypatch.setattr(investigator_brief, "clusters", briefable)
    brief = investigator_brief.build(cluster_id)
    for key in (
        "unit",
        "question",
        "scenario_parameters",
        "defect_in_the_prior_brief",
        "export_command",
        "pre_change_capture",
    ):
        assert str(brief[key]).strip(), key
    assert brief["receipts_this_supersedes"]
    assert brief["pre_change_series"]


@pytest.mark.parametrize("cluster_id", sorted(briefable()))
def test_the_brief_carries_the_committed_pre_change_side_and_not_the_tree(
    cluster_id, monkeypatch
) -> None:
    """The amendment's one line, checked as a fact rather than as an intention.

    The emitted series is asserted equal to the capture the docket cites, and
    asserted to differ from the baseline the working tree holds now -- so a
    builder that quietly read the wrong side would fail on the second half
    even if the first still passed.

    The row set is :func:`briefable`, which includes the cleared rows, so this
    keeps checking the builder against a real capture after the live rows are
    answered.  The patch reaches only which rows ``build`` can see; every
    value it reads still comes off the committed docket and the committed
    capture.
    """
    monkeypatch.setattr(investigator_brief, "clusters", briefable)
    brief = investigator_brief.build(cluster_id)
    committed = investigator_brief.pre_change_baseline(brief["pre_change_capture"])
    current = json.loads(
        (ROOT / investigator_brief.BASELINE_IN_TREE).read_text(encoding="utf-8")
    )["coupled_scenarios"]
    differs = False
    for address, emitted in brief["pre_change_series"].items():
        scenario, _, container = address.partition("/")
        assert emitted == investigator_brief._at(  # pylint: disable=protected-access
            committed, scenario, container
        )
        if emitted != investigator_brief._at(  # pylint: disable=protected-access
            current, scenario, container
        ):
            differs = True
    assert differs, (
        f"{cluster_id}: every series in this brief is identical to the working "
        "tree's baseline, so the test cannot tell the pre-change side from the "
        "post-change one and proves nothing"
    )


def test_the_export_is_r18s_own_command_and_no_wider() -> None:
    """A wider export is an oracle that has read the fix."""
    command = investigator_brief.export_command()
    assert command.startswith("git archive")
    assert "data docs/math-foundations.md" in command
    for forbidden in ("src", "scripts", "tests", "docs/plans", "docs/receipts"):
        assert f" {forbidden} " not in command


def test_a_cluster_routed_to_a_ruling_is_refused_by_name() -> None:
    """Clause 3, enforced rather than described.

    Not asserted non-empty: a cluster leaves this arm when its ruling lands,
    and that is the gap closing rather than a gate to protect.
    """
    routed = [
        entry["id"]
        for entry in json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
        if "owed_ruling_id" in entry
    ]
    for cluster_id in routed:
        with pytest.raises(investigator_brief.BriefError) as raised:
            investigator_brief.build(cluster_id)
        assert "oracle shopping" in str(raised.value)
        assert "rulings-owed.json" in str(raised.value)


def test_a_cluster_already_re_adjudicated_is_refused_and_told_what_it_owes() -> None:
    """Clause 3 from the other end, and clause 2 named in the refusal.

    The refusal a reader gets has to say which of the two no-brief states this
    is.  "Not startable" would read as a gap somebody should fill; this one is
    a row whose investigation ran, so the next act is a ruled ``src/`` slice
    and briefing it again is the oracle shopping clause 3 forbids.
    """
    entries = json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
    for entry in entries:
        if "re_adjudication_filed" not in entry:
            continue
        with pytest.raises(investigator_brief.BriefError) as raised:
            investigator_brief.build(entry["id"])
        assert "oracle shopping" in str(raised.value)
        assert "clause 2" in str(raised.value)
        assert "rulings-owed.json" not in str(raised.value)


def test_the_refusal_is_a_pure_function_of_the_row() -> None:
    """R-05's seam: three fabricated rows, three answers, no docket needed."""
    assert (
        investigator_brief.refusal("x", {"brief_for_the_re_adjudication": {}}) is None
    )
    ruled = investigator_brief.refusal("x", {"owed_ruling_id": "some_ruling"})
    filed = investigator_brief.refusal("x", {"re_adjudication_filed": {}})
    assert ruled is not None and "some_ruling" in ruled
    assert filed is not None and "clause 2" in filed
    assert ruled != filed


def test_an_unknown_cluster_is_refused_rather_than_invented() -> None:
    with pytest.raises(investigator_brief.BriefError):
        investigator_brief.build("no_such_cluster")


def test_the_builder_structurally_cannot_read_the_post_change_baseline() -> None:
    """The line held by construction: no path into the working tree's copy.

    Two assertions, and the second is the one that matters.  The baseline is
    named exactly once in the source, in the constant; and every subprocess
    the module runs is a ``git show``, so the only way it can reach a baseline
    at all is inside a commit object somebody named.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("golden_coupled_baseline") == 1
    assert "REPO_ROOT / BASELINE_IN_TREE" not in source
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    ]
    assert calls
    for call in calls:
        command = call.args[0]
        assert isinstance(command, ast.List)
        assert [element.value for element in command.elts[:2]] == ["git", "show"]
