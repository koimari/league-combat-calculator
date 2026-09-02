"""CI checks out the tree, not the repository.

Every gate the workflow runs answers from the files in the checkout.  Four
records — the corpus anchor's merge base, the campaign's slice tags, the
migration counters' receipt-to-receipt diff and the P2a breach's tree
extraction — are closed and pinned, so none of them needs a commit and none
justifies ``fetch-depth: 0`` on the test job.  The two halves of that are
asserted together: the workflow pins no depth, and no gate reads a commit the
depth-1 checkout does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: Git subcommands that read commits a depth-1 checkout may not have.
#: ``rev-parse`` and ``show`` are absent deliberately: both are used against
#: ``HEAD``, which every checkout has.
HISTORY_WALKING = ("log", "archive", "merge-base", "rev-list", "for-each-ref")

#: ``git`` and the subcommand, however the call spells the gap between them:
#: ``git log`` in prose, ``["git", "log", ...]``, ``_git("merge-base", ...)``,
#: and the same wrapped across lines.
_WALK = re.compile(
    r"""git['"]?[\s,(_-]+['"]?(?:{})\b""".format("|".join(HISTORY_WALKING))
)


def test_the_workflow_pins_no_fetch_depth():
    """The default checkout is depth 1; asking for more needs a reason to."""
    assert "fetch-depth" not in WORKFLOW.read_text(encoding="utf-8")


def test_no_gate_walks_history():
    """Named, so a re-introduced walk is a finding rather than a slow CI job."""
    offenders = []
    for folder in ("tests", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if path == Path(__file__):
                continue
            source = path.read_text(encoding="utf-8")
            for match in _WALK.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    assert offenders == [], offenders
