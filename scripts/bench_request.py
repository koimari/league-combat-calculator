"""Request latency for ``calculate_payload`` — the number ``benchmarks.md`` holds.

Three pinned scenarios, read from ``golden_snapshot.COUPLED_SCENARIOS`` by name
rather than retyped, so a request shape lives in one place: a cheap auto-only
fight, a crit carry, and the fullest roster (two equipped defenders, an ally,
autos at full uptime).  Crit rolls are random unless ``deterministic=True``, so
every call here passes it.

Usage:
    python scripts/bench_request.py                       # table
    python scripts/bench_request.py --json
    python scripts/bench_request.py --compare benchmarks.md   # non-zero on a regression
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.golden_snapshot import COUPLED_SCENARIOS  # noqa: E402
from src.calculator.calculate import calculate_payload  # noqa: E402

REPEATS = 50
LOOP_CALLS = 20

#: ``(bench name, golden scenario, request overrides)``.  The one override is
#: ``auto_only``: no committed golden scenario is auto-only, and the auto path
#: is the cheapest request the endpoint serves — the floor the regression moved.
SCENARIOS = (
    ("simple_auto_only", "score_plain_tuple", {"fight_mode": "auto_only"}),
    ("crit_carry", "crit_onhit_carry_roster", {}),
    ("full_roster", "swing_term_armed_carry_roster", {}),
)

_GOLDEN = {scenario.name: scenario.request for scenario in COUPLED_SCENARIOS}

_IMPORT_PROBE = (
    "import sys, time; sys.path.insert(0, {root!r}); "
    "started = time.perf_counter(); "
    "import src.calculator.calculate; "
    "print((time.perf_counter() - started) * 1000)"
)


def request_for(golden: str, overrides: dict) -> dict:
    """The golden scenario's request with this bench row's overrides applied."""
    return {**_GOLDEN[golden], **overrides}


def import_ms(repeats: int = 3) -> float:
    """Median cost of importing the calculator in a fresh interpreter.

    A warm process cannot see this: the module is already in ``sys.modules``
    by the time the bench runs, so the import has to be paid in a child.
    """
    command = [sys.executable, "-c", _IMPORT_PROBE.format(root=str(ROOT))]
    readings = []
    for _ in range(repeats):
        finished = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=True
        )
        readings.append(float(finished.stdout.strip()))
    return round(statistics.median(readings), 1)


def measure(request: dict, *, repeats: int = REPEATS) -> dict:
    """Warm once, then median/p90 over ``repeats`` calls plus a 20-call loop."""
    calculate_payload(request, deterministic=True)
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        calculate_payload(request, deterministic=True)
        samples.append((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    for _ in range(LOOP_CALLS):
        calculate_payload(request, deterministic=True)
    loop_seconds = time.perf_counter() - started
    return {
        "median_ms": round(statistics.median(samples), 2),
        "p90_ms": round(statistics.quantiles(samples, n=10, method="inclusive")[8], 2),
        "loop_20_s": round(loop_seconds, 3),
    }


def bench(selected: tuple, *, repeats: int = REPEATS) -> dict:
    """Every selected scenario, in declaration order, plus the import cost."""
    return {
        "import_calculator_ms": import_ms(),
        "repeats": repeats,
        "scenarios": {
            name: measure(request_for(golden, overrides), repeats=repeats)
            for name, golden, overrides in selected
        },
    }


def committed_medians(path: str) -> dict:
    """``{scenario: median ms}`` from ``benchmarks.md``'s request table."""
    known = {name for name, _, _ in SCENARIOS}
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] in known:
            rows[cells[0]] = float(cells[1])
    return rows


def regressions(measured: dict, committed: dict, tolerance: float = 1.25) -> list:
    """Scenarios whose median exceeds the committed one by more than 25%."""
    return [
        f"{name}: {committed[name]} -> {reading['median_ms']} ms median"
        for name, reading in measured["scenarios"].items()
        if name in committed and reading["median_ms"] > committed[name] * tolerance
    ]


def _print_table(report: dict) -> None:
    """The committed table's own shape, so a reader can diff by eye."""
    print(f"import calculator: {report['import_calculator_ms']} ms (fresh interpreter)")
    print(f"{'scenario':<20}{'median ms':>12}{'p90 ms':>10}{'20-call s':>12}")
    for name, reading in report["scenarios"].items():
        print(
            f"{name:<20}{reading['median_ms']:>12}"
            f"{reading['p90_ms']:>10}{reading['loop_20_s']:>12}"
        )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scenario", choices=[name for name, _, _ in SCENARIOS], default=None
    )
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--compare", default=None, help="fail if a median regressed vs benchmarks.md"
    )
    args = parser.parse_args()

    selected = tuple(row for row in SCENARIOS if args.scenario in (None, row[0]))
    report = bench(selected, repeats=args.repeats)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(report)

    if args.compare:
        slower = regressions(report, committed_medians(args.compare))
        for failure in slower:
            print(f"LATENCY REGRESSION — {failure}", file=sys.stderr)
        if slower:
            sys.exit(1)


if __name__ == "__main__":
    main()
