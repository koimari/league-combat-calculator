"""CI checks out the tree, not the repository.

Every gate the workflow runs answers from the files in the checkout.  Four
places used to answer from commits instead — the corpus anchor's merge base,
the campaign's slice tags, the migration counters' receipt-to-receipt diff and
the P2a breach's ``git archive`` — and each of them held ``fetch-depth: 0`` on
every job for a record that was already closed.  The records are pinned now,
so the two halves of that are asserted together: the workflow pins no depth,
and no gate walks history to find out what it is gating.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: Git subcommands that read commits the checkout may not have.  ``rev-parse``
#: and ``show`` are absent deliberately: both are used against ``HEAD``, which
#: a depth-1 checkout has.
HISTORY_WALKING = ("log", "archive", "merge-base", "rev-list", "for-each-ref")

_WALK = re.compile(r"\bgit[ _-]?(?:%s)\b" % "|".join(HISTORY_WALKING))


def test_the_workflow_pins_no_fetch_depth():
    """The default checkout is depth 1; asking for more needs a reason to."""
    assert "fetch-depth" not in WORKFLOW.read_text(encoding="utf-8")


def test_no_gate_walks_history():
    """Named, so a re-introduced walk is a finding rather than a slow CI job."""
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{number}"
        for folder in ("tests", "scripts")
        for path in sorted((ROOT / folder).rglob("*.py"))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _WALK.search(line) and path.name != Path(__file__).name
    ]
    assert offenders == [], offenders
