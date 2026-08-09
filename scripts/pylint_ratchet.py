"""Per-file, non-decreasing pylint score gate (runbook R-03, D-99).

CI's real lint gate is ``pylint src/ --fail-under=9``, an *average*.  An
average is the wrong instrument for a campaign that adds ~25 small clean
modules while rewriting a handful of large ones: the new files lift the mean
by more than a hotspot's rot pushes it down, so the largest module can
degrade for months under a green gate.  This is the other half of that gate —
a score per file, and no file may score lower than the value recorded for it
in ``docs/receipts/campaign-fingerprints.json``.

The score is pylint's own, from a single-file ``--output-format=json2`` run,
so nothing here re-implements pylint's arithmetic.  Baselines are seeded from
``--scores`` and live only in the fingerprints receipt; this script never
writes them, because a gate that can move its own baseline is not a gate.

Usage:
    python scripts/pylint_ratchet.py --check           # the gate
    python scripts/pylint_ratchet.py --scores <path>…  # seed values, to stdout
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

# Floating-point noise in pylint's own score arithmetic must not read as rot.
SCORE_EPSILON = 1e-6


def file_score(path: str) -> float:
    """One file's pylint score, from pylint's own scorer.

    ``json2`` is the only output format that carries ``statistics.score``,
    which is why the ratchet reads it rather than counting messages and
    reproducing the formula.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pylint", "--output-format=json2", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"pylint produced no JSON report for {path}: "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        ) from exc
    return float(report["statistics"]["score"])


def load_baseline() -> dict[str, float]:
    """The ``pylint`` block of the fingerprints receipt, or an empty mapping."""
    if not FINGERPRINTS_PATH.exists():
        return {}
    receipt = json.loads(FINGERPRINTS_PATH.read_text(encoding="utf-8"))
    block = receipt.get("pylint") or {}
    return {str(path): float(score) for path, score in block.items()}


def check_ratchet(
    baseline: Mapping[str, float], *, score=file_score
) -> tuple[str, ...]:
    """Files whose pylint score fell — an empty tuple is the pass condition.

    ``score`` is the seam the gate's own negative test drives: a ratchet that
    cannot be made to fail on demand is indistinguishable from one that
    passes (R-05).
    """
    failures: list[str] = []
    for path in sorted(baseline):
        if not (REPO_ROOT / path).exists():
            failures.append(
                f"{path} is in the pylint baseline but no longer exists -- "
                "drop its row deliberately rather than by deletion"
            )
            continue
        current = score(path)
        recorded = baseline[path]
        if current < recorded - SCORE_EPSILON:
            failures.append(
                f"{path} scores {current:.4f}, below its recorded {recorded:.4f} "
                "-- the per-file ratchet is non-decreasing (D-99)"
            )
    return tuple(failures)


def run_check() -> int:
    """The gate: every recorded file still scores at least what it scored."""
    baseline = load_baseline()
    if not baseline:
        print(
            f"note: {FINGERPRINTS_PATH.name} carries no pylint block yet; the "
            "per-file ratchet has nothing to hold and passes vacuously.",
            file=sys.stderr,
        )
        return 0
    failures = check_ratchet(baseline)
    for failure in failures:
        print(f"pylint ratchet: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"pylint ratchet: {len(baseline)} file(s) at or above their recorded score")
    return 0


def print_scores(paths: Sequence[str]) -> int:
    """Print ``{path: score}`` for the given files, for seeding the receipt."""
    print(json.dumps({path: file_score(path) for path in paths}, indent=2))
    return 0


def main() -> None:
    """CLI entry point: --check (the gate) or --scores (seed values)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="run the gate")
    parser.add_argument("--scores", nargs="+", default=None, help="score these files")
    args = parser.parse_args()
    if args.scores:
        sys.exit(print_scores(args.scores))
    if args.check:
        sys.exit(run_check())
    parser.error("one of --check or --scores is required")


if __name__ == "__main__":
    main()
