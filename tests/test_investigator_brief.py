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


def startable() -> list[str]:
    """Docketed clusters a whole-series re-adjudication can be posed for."""
    return sorted(
        entry["id"]
        for entry in json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
        if "brief_for_the_re_adjudication" in entry
    )


def test_every_docketed_cluster_is_either_startable_or_routed_to_a_ruling() -> None:
    """The docket's own partition, reproduced by the tool that acts on it."""
    entries = json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
    for entry in entries:
        has_brief = "brief_for_the_re_adjudication" in entry
        assert has_brief != ("owed_ruling_id" in entry), entry["id"]
    assert set(investigator_brief.clusters()) == {entry["id"] for entry in entries}


@pytest.mark.parametrize("cluster_id", startable())
def test_a_startable_cluster_gets_a_brief_that_poses_the_series(cluster_id) -> None:
    """Every field clause 1 and clause 3 need, present and non-empty."""
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


@pytest.mark.parametrize("cluster_id", startable())
def test_the_brief_carries_the_committed_pre_change_side_and_not_the_tree(
    cluster_id,
) -> None:
    """The amendment's one line, checked as a fact rather than as an intention.

    The emitted series is asserted equal to the capture the docket cites, and
    asserted to differ from the baseline the working tree holds now -- so a
    builder that quietly read the wrong side would fail on the second half
    even if the first still passed.
    """
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
    """Clause 3, enforced rather than described."""
    routed = [
        entry["id"]
        for entry in json.loads(DOCKET.read_text(encoding="utf-8"))["clusters"]
        if "owed_ruling_id" in entry
    ]
    assert routed
    for cluster_id in routed:
        with pytest.raises(investigator_brief.BriefError) as raised:
            investigator_brief.build(cluster_id)
        assert "oracle shopping" in str(raised.value)
        assert "rulings-owed.json" in str(raised.value)


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
