"""Search latency for the direct ``optimize_build`` call — the Ahri/18/5 shape.

The coupled bench next door times ``/api/optimize`` against an enemy roster.
This one times the uncoupled call that ``tests/test_optimizer.py``'s smoke cap
drives, which is the scenario every optimizer figure in ``benchmarks.md`` and in
that cap's docstring was measured on.  The parameters below are that test's,
and ``FightParams.from_request(..., deterministic=True)`` is its seam — Ahri
reaches crit-capable builds during the search, and an undetermined crit roll
would make two identical searches score differently.

``optimization_time_ms`` is the engine's own reading and the figure the smoke
cap asserts on; wall time is reported beside it so a gap between them shows up
as harness cost rather than hiding in the median.

The script imports nothing from ``scripts/``, so it can be copied into an
archived checkout of an older commit to re-measure that tree with this harness.

Usage:
    python scripts/bench_optimize_build.py            # table
    python scripts/bench_optimize_build.py --json
    python scripts/bench_optimize_build.py --repeats 9
    python scripts/bench_optimize_build.py --profile  # cProfile one warm search
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calculator.data_fetcher import get_champion  # noqa: E402
from src.calculator.optimizer import optimize_build  # noqa: E402
from src.calculator.pipeline import FightParams  # noqa: E402

REPEATS = 7

CHAMPION = "Ahri"
LEVEL = 18
MAX_LEGENDARY_SLOTS = 5
TARGET = {"target_health": 2000, "target_armor": 50, "target_mr": 40}


def one_search() -> dict:
    """One full search, returning the optimizer's own response."""
    return optimize_build(
        get_champion(CHAMPION),
        LEVEL,
        fight_params=FightParams.from_request(TARGET, deterministic=True),
        max_legendary_slots=MAX_LEGENDARY_SLOTS,
    )


def measure(repeats: int = REPEATS) -> dict:
    """Warm once, then engine and wall readings over ``repeats`` searches.

    The warmup is not optional: the first search of a process pays the item
    catalogue parse and every module-level memo, which is several hundred ms of
    work no later search repeats.
    """
    warmup = one_search()
    engine, wall = [], []
    for _ in range(repeats):
        started = time.perf_counter()
        result = one_search()
        wall.append((time.perf_counter() - started) * 1000)
        engine.append(float(result["optimization_time_ms"]))
    return {
        "repeats": repeats,
        "engine_median_ms": round(statistics.median(engine), 1),
        "engine_best_ms": round(min(engine), 1),
        "engine_worst_ms": round(max(engine), 1),
        "wall_median_ms": round(statistics.median(wall), 1),
        "evaluations": warmup.get("evaluations"),
        "items": warmup.get("items"),
        "boots": warmup.get("boots"),
        "total_damage": warmup.get("total_damage"),
    }


def _print_table(report: dict) -> None:
    """One row per reading, in the shape ``benchmarks.md`` holds."""
    spread = report["engine_worst_ms"] - report["engine_best_ms"]
    print(f"{CHAMPION} level {LEVEL}, {MAX_LEGENDARY_SLOTS} legendary slots")
    print(f"  engine median (of {report['repeats']}): {report['engine_median_ms']} ms")
    print(f"  engine best / worst: {report['engine_best_ms']} / ", end="")
    print(f"{report['engine_worst_ms']} ms (spread {round(spread, 1)} ms)")
    print(f"  wall median: {report['wall_median_ms']} ms")
    print(f"  evaluations: {report['evaluations']}")
    print(f"  build: {report['items']} + {report['boots']}")
    print(f"  score: {report['total_damage']}")


def profile(rows: int = 30) -> None:
    """cProfile one search, warmed first so the catalogue parse is not the top row."""
    one_search()
    profiler = cProfile.Profile()
    profiler.enable()
    one_search()
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats("tottime").print_stats(rows)
    stats.sort_stats("cumulative").print_stats(rows)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--profile", action="store_true", help="cProfile one search")
    args = parser.parse_args()

    if args.profile:
        profile()
        return

    report = measure(repeats=args.repeats)
    print(json.dumps(report, indent=2)) if args.json else _print_table(report)


if __name__ == "__main__":
    main()
