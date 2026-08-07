#!/usr/bin/env python3
"""Beta success scorecard CLI (thin wrapper around the runtime module).

The scorecard definition lives in ``src/metrics.py`` so ``GET /api/metrics``
and this CLI share one gate (see docs/beta-metrics.md).  This script only
adds the operator surface: human/JSON output and the exit-code contract.

Usage
-----
    python scripts/beta_metrics.py                 # human scorecard
    python scripts/beta_metrics.py --json          # dashboard payload
    python scripts/beta_metrics.py --beta-start 2026-07-23 --weeks 2 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from metrics import compute_scorecard  # noqa: E402


def _parse_cli_datetime(value: str) -> datetime:
    """Parse an ISO date or datetime (CLI) into naive UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _format_human(scorecard: dict) -> str:
    """Render the scorecard as a compact terminal table."""
    lines = [
        "Scryglass Beta Scorecard",
        f"generated_at: {scorecard['generated_at']}",
        "beta: {start} -> {end} ({window_days} days, {weeks} weeks, {complete})".format(
            start=scorecard["beta"]["start"],
            end=scorecard["beta"]["end"],
            window_days=scorecard["beta"]["window_days"],
            weeks=scorecard["beta"]["weeks"],
            complete="complete" if scorecard["beta"]["complete"] else "in progress",
        ),
        "",
        "data_sources: sessions_observed={sessions_observed}, "
        "sessions_without_id={sessions_without_id}, builds={builds}, "
        "shares={shares}, feedback={feedback}, metrics_events={metrics_events}, "
        "receipts={receipts}".format(**scorecard["data_sources"]),
        "",
    ]
    for name in ("activation", "retention", "receipts", "bias", "staleness"):
        entry = scorecard["criteria"][name]
        status = entry["status"].upper()
        value = entry.get("value", entry.get("value_hours"))
        threshold = entry.get("threshold", entry.get("threshold_hours"))
        lines.append(f"{name:<10} {status:<16} value={value} threshold={threshold}")
        lines.append(f"            {entry['detail']}")
        for week in entry.get("weeks", []):
            lines.append(
                f"            week {week['week']}: {week['status']}"
                f" (complete={week.get('complete')})"
            )
    gate = scorecard["gate"]
    lines.append("")
    lines.append(f"gate: {gate['verdict']} ({gate['status']})")
    lines.append(f"rule: {gate['rule']}")
    lines.append(f"missed_weeks: {gate['missed_weeks']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: print the scorecard; exit 1 when the gate fails."""
    parser = argparse.ArgumentParser(
        description="Scryglass beta metrics scorecard + PASS/FAIL gate",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the raw scorecard JSON for the dashboard",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="evaluation time as ISO datetime (default: now)",
    )
    parser.add_argument(
        "--beta-start",
        default=None,
        help="beta start as ISO date/datetime (default: 14 days before now)",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=2,
        help="beta length in weeks (default: 2)",
    )
    parser.add_argument(
        "--staleness-report",
        default=None,
        help="path to the patch-regression report (default: data/staleness.json)",
    )
    args = parser.parse_args(argv)

    now = _parse_cli_datetime(args.now) if args.now else None
    beta_start = _parse_cli_datetime(args.beta_start) if args.beta_start else None
    scorecard = compute_scorecard(
        now=now,
        beta_start=beta_start,
        weeks=args.weeks,
        staleness_path=args.staleness_report,
    )
    if args.json:
        print(json.dumps(scorecard, indent=2, sort_keys=False))
    else:
        print(_format_human(scorecard))
    return 1 if scorecard["gate"]["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
