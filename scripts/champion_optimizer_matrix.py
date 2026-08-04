"""Run a bounded 173-champion optimizer smoke matrix for issue #38.

Each registered champion is sent through the real local Flask
``/api/optimize`` path with one locked item so the sweep stays bounded.  The
report records elapsed time, status/error text, event-order coverage, and the
item-candidate scope.  Issue #38 certifies champion event packages; incomplete
item coverage is owned by issue #40 and is recorded as a separate scope gap.
A partial event timeline or an unexpected HTTP result still fails the matrix;
an in-scope champion result is never promoted to a global BIS claim.

Usage::

    .venv/bin/python scripts/champion_optimizer_matrix.py
    .venv/bin/python scripts/champion_optimizer_matrix.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXPECTED_WITHHOLDING_PREFIXES = (
    "No complete legal event-ordered build fits",
    "Manual ability ranks unavailable",
    "Time-based ",
)


def _payload(champion: str) -> dict[str, Any]:
    """Build the bounded, deterministic payload used for every champion."""
    return {
        "champion": champion,
        "level": 18,
        "fight_mode": "one_rotation",
        "include_boots": False,
        "max_legendary_slots": 1,
        "locked_items": ["Shadowflame"],
    }


def _classify(status: int, body: Mapping[str, Any]) -> str:
    """Classify a result by champion timeline, then disclose item scope.

    ``is_certified_best`` is deliberately not the champion-matrix predicate:
    the optimizer can withhold a global BIS claim because the item umbrella
    still has known out-of-scope candidates while the champion's own event
    package is complete.  Those are separate work streams.  Keep that fact in
    the outcome instead of mislabeling every generic champion as a partial
    champion.
    """
    if status == 200:
        coverage = body.get("search_timeline_coverage")
        if isinstance(coverage, Mapping) and coverage.get("complete"):
            if bool(body.get("is_certified_best")):
                return "certified"
            candidate_coverage = body.get("candidate_coverage")
            if isinstance(candidate_coverage, Mapping) and not bool(
                candidate_coverage.get("complete")
            ):
                return "certified_with_item_scope_gap"
        return "partial_or_unexhaustive"
    error = body.get("error")
    if (
        status == 400
        and isinstance(error, str)
        and error.startswith(EXPECTED_WITHHOLDING_PREFIXES)
    ):
        return "expected_withholding"
    return "unexpected_failure"


def run_matrix(
    post: Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]],
    names: list[str],
) -> dict[str, Any]:
    """Exercise every supplied champion and return an auditable report."""
    results: list[dict[str, Any]] = []
    for champion in names:
        payload = _payload(champion)
        started = time.perf_counter()
        status, raw_body = post("/api/optimize", payload)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        body = raw_body if isinstance(raw_body, dict) else {}
        coverage = body.get("search_timeline_coverage", {})
        if not isinstance(coverage, dict):
            coverage = {}
        results.append(
            {
                "champion": champion,
                "status": int(status),
                "error": body.get("error"),
                "elapsed_ms": elapsed_ms,
                "search_timeline_coverage": coverage,
                "candidate_coverage": (
                    body.get("candidate_coverage", {})
                    if isinstance(body.get("candidate_coverage", {}), dict)
                    else {}
                ),
                "selection_certification": body.get("selection_certification"),
                "outcome": _classify(int(status), body),
                "build": (
                    {"items": body.get("items"), "boots": body.get("boots")}
                    if int(status) == 200
                    else None
                ),
            }
        )

    expected_names = list(names)
    observed_names = [row["champion"] for row in results]
    counts = Counter(row["outcome"] for row in results)
    integrity_ok = (
        len(expected_names) == len(set(expected_names))
        and observed_names == expected_names
        and all(
            isinstance(row["elapsed_ms"], float) and row["elapsed_ms"] >= 0
            for row in results
        )
    )
    return {
        "matrix": "issue_38_champion_optimizer",
        "registered_count": len(expected_names),
        "exercised_count": len(observed_names),
        "all_registered_exercised": integrity_ok,
        "outcome_counts": dict(sorted(counts.items())),
        # A matrix that contains a partial event timeline has not certified
        # that champion.  Item-scope gaps are reported separately because
        # they are the issue #40 track, not evidence that the champion module
        # itself is partial.
        "passed": (
            integrity_ok
            and counts.get("unexpected_failure", 0) == 0
            and counts.get("partial_or_unexhaustive", 0) == 0
        ),
        "results": results,
    }


def main() -> int:
    """Run the local 173-champion smoke matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args()

    from src.app import app  # pylint: disable=import-outside-toplevel
    from src.calculator.champions import (  # pylint: disable=import-outside-toplevel
        registered_champion_names,
    )

    app.config["RATE_LIMIT_ENABLED"] = False
    names = registered_champion_names()
    with app.test_client() as client:
        report = run_matrix(
            lambda path, payload: (
                (
                    response.status_code,
                    response.get_json(silent=True) or {},
                )
                if (response := client.post(path, json=payload))
                else (0, {"error": "no response"})
            ),
            names,
        )
    report["registry_size_expected"] = 173
    report["registry_size_ok"] = len(names) == report["registry_size_expected"]
    report["passed"] = bool(report["passed"] and report["registry_size_ok"])

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for row in report["results"]:
            print(
                f"{row['outcome'].upper()} {row['champion']}: "
                f"status={row['status']} elapsed_ms={row['elapsed_ms']} "
                f"error={row['error'] or '-'}"
            )
        print(
            f"summary exercised={report['exercised_count']}/"
            f"{report['registered_count']} passed={report['passed']}"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
