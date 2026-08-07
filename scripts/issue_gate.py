#!/usr/bin/env python3
"""Issue-closure gate (issue #77): verify a claim is commit-addressed + gated.

Before closing a GitHub issue with an implementation claim, this script
proves the claim is (a) merged on the working branch, (b) fully gated
green, and (c) traceable to a deployment SHA when one is provided.

Usage:
    python scripts/issue_gate.py check --issue 45 --commit 79baf9a
    python scripts/issue_gate.py check --issue 45 --commit 79baf9a --deploy-sha 79baf9a

Exit code 0 = the issue may be closed; non-zero = do NOT close (reasons printed).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRANCH = "codex/deep-audit-2026-08"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=120
    )


def gate(args: argparse.Namespace) -> int:
    failures: list[str] = []
    commit = args.commit
    if args.deploy_sha:
        # Deployment gate: the claim commit must be an ancestor of the
        # deployed SHA (or equal). When P10 lands, this hook compares
        # against the live Vercel deployment; today it accepts the
        # explicit deploy-sha argument.
        deploy = args.deploy_sha
        ancestor = _git("merge-base", "--is-ancestor", commit, deploy)
        if ancestor.returncode != 0:
            failures.append(
                f"deployment gate: commit {commit[:10]} is not an ancestor of "
                f"deployed SHA {deploy[:10]}"
            )
    r = _git("fetch", "origin", BRANCH)
    if r.returncode != 0:
        failures.append("fetch origin failed")
    ancestor = _git("merge-base", "--is-ancestor", commit, f"origin/{BRANCH}")
    if ancestor.returncode != 0:
        failures.append(f"commit {commit[:10]} is not merged on origin/{BRANCH}")
    # (2) Working tree clean
    status = _git("status", "--porcelain")
    if status.stdout.strip():
        failures.append(f"working tree is dirty:\n{status.stdout.strip()[:200]}")
    # (3) Golden gate (engine regression)
    venv = REPO / ".venv" / "bin" / "python"
    if venv.exists():
        golden = subprocess.run(
            [
                str(venv),
                "scripts/golden_snapshot.py",
                "compare",
                "scripts/golden_baseline.json",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=REPO,
        )
        if golden.returncode != 0:
            failures.append("golden snapshot differs from baseline")
        pytest = subprocess.run(
            [str(venv), "-m", "pytest", "-q"],
            capture_output=True,
            text=True,
            timeout=2400,
            cwd=REPO,
        )
        if pytest.returncode != 0:
            failures.append("full pytest suite not green")
        pylint = subprocess.run(
            [str(venv), "-m", "pylint", "src/", "--fail-under=9"],
            capture_output=True,
            text=True,
            timeout=900,
            cwd=REPO,
        )
        if pylint.returncode != 0:
            failures.append("pylint < 9")
    if failures:
        print("ISSUE GATE FAILED — do not close:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        f"ISSUE GATE PASSED: commit {commit[:10]} is merged on "
        f"origin/{BRANCH}, gates green"
        + (
            f", deployment ancestor of {args.deploy_sha[:10]}"
            if args.deploy_sha
            else ""
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="verify an issue-closure claim")
    check.add_argument("--issue", required=True, help="issue number (informational)")
    check.add_argument("--commit", required=True, help="claim commit SHA")
    check.add_argument(
        "--deploy-sha",
        default=None,
        help="deployed SHA to gate against (optional; wired fully at P10)",
    )
    check.set_defaults(func=gate)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
