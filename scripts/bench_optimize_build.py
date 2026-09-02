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

``--budget`` answers where one evaluation goes.  cProfile charges about a
microsecond to every call and this engine spreads its cost over millions of
one-line ones, so its shares over-weight small helpers roughly two to one.  The
mode takes call *counts* from a profiled search, which cProfile reports exactly,
and *shares* from a ``timeit`` best-of-7 of each term against a best-of-7 of the
whole ``run_fight``.  A term called once per evaluation is timed on the
arguments a real evaluation passed it; a term called per owner or per item is
timed as the fold it runs in, less a no-op fold of the same length, so it reads
its body rather than the harness loop around it.

``--by-build-size`` answers whether a saving that scales with held items pays.
A fold memoized per build looks free when it is timed in a loop over one build,
so each sample is a fresh subprocess and the timed evaluation is the first that
process runs on that build.  ``--against`` alternates a second checkout's copy
of this script round by round, so machine drift lands on both trees.

The script imports nothing from ``scripts/``, so it can be copied into an
archived checkout of an older commit to re-measure that tree with this harness.

Usage:
    python scripts/bench_optimize_build.py            # table
    python scripts/bench_optimize_build.py --json
    python scripts/bench_optimize_build.py --repeats 9
    python scripts/bench_optimize_build.py --profile  # cProfile one warm search
    python scripts/bench_optimize_build.py --budget   # per-term share of one evaluation
    python scripts/bench_optimize_build.py --by-build-size --against ../other-tree
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import statistics
import subprocess
import sys
import time
import timeit
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calculator import (
    damage,
    item_behavior_catalog,
    item_effects,
    pipeline,
)
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.optimizer import (
    get_selectable_items,
    optimize_build,
)
from src.calculator.pipeline import FightParams, run_fight

REPEATS = 7

CHAMPION = "Ahri"
LEVEL = 18
MAX_LEGENDARY_SLOTS = 5
TARGET = {"target_health": 2000, "target_armor": 50, "target_mr": 40}

BUILD_SIZES = (1, 2, 3, 4, 6)
ROUNDS = 5


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


def _elected_build(result: dict) -> list[dict]:
    """The item rows the search elected, boots last."""
    names = list(result["items"])
    if result.get("boots"):
        names.append(result["boots"])
    return [get_item_by_name(name) for name in names]


def _noop(_value: Any) -> None:
    """A fold's floor: one call that does nothing."""


def _fold(call: Callable[[Any], Any], values: list) -> None:
    """Call *call* once per value, the shape a per-owner fold runs in."""
    for value in values:
        call(value)


def _replay(calls: list) -> None:
    """Make each recorded call again, in the order the evaluation made them."""
    for call in calls:
        call()


def _best_us(call: Callable[[], Any], repeats: int) -> float:
    """Best-of-*repeats* microseconds for one call of *call*."""
    timer = timeit.Timer(call)
    number, _ = timer.autorange()
    return min(timer.repeat(repeats, number)) / number * 1e6


class Term(NamedTuple):
    """One priced term: what to time, how many calls that is, where it profiles."""

    label: str
    call: Callable[[], Any]
    calls: int
    floor: Callable[[], Any] | None
    key: tuple[str, str]


CAPTURED = ((pipeline, "parse_champion_abilities"), (damage, "_damage_event_row"))


def _capture_calls(champion: dict, items: list[dict], params: FightParams) -> dict:
    """Every call one evaluation makes to a term the build alone cannot rebuild.

    Both are reached by module-global lookup from the function that calls them,
    so a recorder bound to the global sees the evaluation's own calls.  Whole
    sequences, not one sample: ``_damage_event_row`` prices four row shapes and
    only the evaluation's own mix of them weights them the way the search does.
    """
    captured: dict[str, list] = {attr: [] for _module, attr in CAPTURED}
    restore = []
    for module, attr in CAPTURED:
        original = getattr(module, attr)
        restore.append((module, attr, original))

        def record(*args, _attr=attr, _original=original, **kwargs):
            captured[_attr].append(partial(_original, *args, **kwargs))
            return _original(*args, **kwargs)

        setattr(module, attr, record)
    try:
        run_fight(champion, LEVEL, items, params)
    finally:
        for module, attr, original in restore:
            setattr(module, attr, original)
    empty = [attr for attr, calls in captured.items() if not calls]
    if empty:
        raise RuntimeError(f"one evaluation called none of {empty}")
    return captured


def _captured_term(label: str, calls: list, key: tuple[str, str]) -> Term:
    """One term timed by replaying its captured calls, against an empty replay."""
    floor = [partial(_noop, None)] * len(calls)
    return Term(
        label, partial(_replay, calls), len(calls), partial(_replay, floor), key
    )


def _profile_totals() -> tuple[dict, float]:
    """Exact call counts and cumulative time per (file, function) over one search."""
    profiler = cProfile.Profile()
    profiler.enable()
    one_search()
    profiler.disable()
    stats = pstats.Stats(profiler)
    totals: dict[tuple[str, str], list[float]] = {}
    for (filename, _line, func), row in stats.stats.items():
        entry = totals.setdefault((Path(filename).name, func), [0, 0.0])
        entry[0] += row[1]
        entry[1] += row[3]
    return totals, stats.total_tt


def _budget_terms(
    champion: dict, params: FightParams, items: list[dict], captured: dict
) -> list[Term]:
    """The terms `benchmarks.md` prices, called the way an evaluation calls them."""
    owners = [item_effects.resolved_item_name(item) for item in items]
    return [
        _captured_term(
            "champions.engine.parse_abilities",
            captured["parse_champion_abilities"],
            ("engine.py", "parse_abilities"),
        ),
        Term(
            "FightParams.pre_combat_stats",
            partial(params.pre_combat_stats, champion, LEVEL, items),
            1,
            None,
            ("pipeline.py", "pre_combat_stats"),
        ),
        _captured_term(
            "damage._damage_event_row",
            captured["_damage_event_row"],
            ("damage.py", "_damage_event_row"),
        ),
        Term(
            "item_behavior_catalog.behavior_rules",
            partial(_fold, item_behavior_catalog.behavior_rules, owners),
            len(owners),
            partial(_fold, _noop, owners),
            ("item_behavior_catalog.py", "behavior_rules"),
        ),
        Term(
            "item_effects.resolved_item_name",
            partial(_fold, item_effects.resolved_item_name, items),
            len(items),
            partial(_fold, _noop, items),
            ("item_effects.py", "resolved_item_name"),
        ),
        Term(
            "item_effects._item_names",
            partial(item_effects._item_names, items),  # noqa: SLF001 - the fold
            1,
            None,
            ("item_effects.py", "_item_names"),
        ),
    ]


def budget(repeats: int = REPEATS) -> dict:
    """Each term's real share of one evaluation, beside what the profiler says."""
    warmup = one_search()
    champion = get_champion(CHAMPION)
    params = FightParams.from_request(TARGET, deterministic=True)
    items = _elected_build(warmup)
    evaluations = int(warmup["evaluations"])
    evaluation_us = _best_us(
        partial(run_fight, champion, LEVEL, items, params), repeats
    )
    captured = _capture_calls(champion, items, params)
    totals, profile_tt = _profile_totals()
    rows = []
    for term in _budget_terms(champion, params, items, captured):
        floor = _best_us(term.floor, repeats) if term.floor is not None else 0.0
        per_call = (_best_us(term.call, repeats) - floor) / term.calls
        counted, cumulative = totals.get(term.key, (0, 0.0))
        per_evaluation = per_call * counted / evaluations
        rows.append(
            {
                "term": term.label,
                "calls_per_search": int(counted),
                "per_call_us": round(per_call, 3),
                "per_evaluation_us": round(per_evaluation, 1),
                "share": round(per_evaluation / evaluation_us, 3),
                "profile_share": round(cumulative / profile_tt, 3),
            }
        )
    return {
        "repeats": repeats,
        "build": [item_effects.resolved_item_name(item) for item in items],
        "evaluations": evaluations,
        "evaluation_us": round(evaluation_us, 1),
        "terms": rows,
    }


def _print_budget(report: dict) -> None:
    """The per-term table, in the shape ``benchmarks.md`` holds."""
    print(f"one evaluation: {report['evaluation_us']} us")
    print(f"  build: {', '.join(report['build'])}")
    print(f"  evaluations per search: {report['evaluations']}")
    print(f"  {'term':38} {'calls':>9} {'per call':>9} {'us/eval':>8}", end="")
    print(f" {'share':>6} {'profile':>7}")
    for row in report["terms"]:
        print(f"  {row['term']:38} {row['calls_per_search']:9d}", end="")
        print(f" {row['per_call_us']:9.3f} {row['per_evaluation_us']:8.1f}", end="")
        print(f" {row['share']:6.1%} {row['profile_share']:7.1%}")


def _warmup_names(names: list[str]) -> list[str]:
    """One item outside the measured build, so the timed evaluation is the first."""
    held = set(names)
    for item in get_selectable_items():
        candidate = item_effects.resolved_item_name(item)
        if candidate not in held:
            return [candidate]
    raise RuntimeError("every selectable item is in the measured build")


def build_size_sample(size: int, names: list[str]) -> float:
    """Microseconds for a cold process's first evaluation of a *size*-item build."""
    champion = get_champion(CHAMPION)
    params = FightParams.from_request(TARGET, deterministic=True)
    warm = [get_item_by_name(name) for name in _warmup_names(names)]
    build = [get_item_by_name(name) for name in names[:size]]
    run_fight(champion, LEVEL, warm, params)
    started = time.perf_counter()
    run_fight(champion, LEVEL, build, params)
    return (time.perf_counter() - started) * 1e6


def _run_sample(tree: Path, size: int, names: list[str]) -> float:
    """One cold subprocess, running *tree*'s own copy of this script."""
    completed = subprocess.run(
        [
            sys.executable,
            str(tree / "scripts" / "bench_optimize_build.py"),
            "--build-size-sample",
            str(size),
            "--build",
            json.dumps(names),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(tree),
    )
    return float(json.loads(completed.stdout)["per_evaluation_us"])


def by_build_size(rounds: int = ROUNDS, against: str | None = None) -> dict:
    """Per-evaluation microseconds by items held, trees alternated round by round."""
    names = [item_effects.resolved_item_name(i) for i in _elected_build(one_search())]
    trees = [ROOT] + ([Path(against).resolve()] if against else [])
    samples = {str(tree): {size: [] for size in BUILD_SIZES} for tree in trees}
    for index in range(rounds):
        order = trees if index % 2 == 0 else list(reversed(trees))
        for size in BUILD_SIZES:
            for tree in order:
                samples[str(tree)][size].append(_run_sample(tree, size, names))
    return {
        "rounds": rounds,
        "build": names,
        "trees": {
            tree: {
                str(size): round(statistics.median(readings), 1)
                for size, readings in sizes.items()
            }
            for tree, sizes in samples.items()
        },
    }


def _print_by_build_size(report: dict) -> None:
    """One row per tree, one column per build size."""
    print(f"per-evaluation us, cold build, median over {report['rounds']} rounds")
    print(f"  build: {', '.join(report['build'])}")
    header = "".join(f"{size:>9}" for size in BUILD_SIZES)
    print(f"  {'items held':38}{header}")
    for tree, sizes in report["trees"].items():
        row = "".join(f"{sizes[str(size)]:9.1f}" for size in BUILD_SIZES)
        print(f"  {Path(tree).name[:38]:38}{row}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--profile", action="store_true", help="cProfile one search")
    parser.add_argument("--budget", action="store_true", help="per-term budget table")
    parser.add_argument(
        "--by-build-size", action="store_true", help="per-evaluation us by items held"
    )
    parser.add_argument("--rounds", type=int, default=ROUNDS, help="--by-build-size")
    parser.add_argument("--against", help="a second checkout to alternate with")
    parser.add_argument("--build-size-sample", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--build", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.build_size_sample:
        sample = build_size_sample(args.build_size_sample, json.loads(args.build))
        print(json.dumps({"per_evaluation_us": round(sample, 1)}))
        return
    if args.profile:
        profile()
        return
    if args.budget:
        report = budget(repeats=args.repeats)
        print(json.dumps(report, indent=2)) if args.json else _print_budget(report)
        return
    if args.by_build_size:
        report = by_build_size(rounds=args.rounds, against=args.against)
        (
            print(json.dumps(report, indent=2))
            if args.json
            else _print_by_build_size(report)
        )
        return

    report = measure(repeats=args.repeats)
    print(json.dumps(report, indent=2)) if args.json else _print_table(report)


if __name__ == "__main__":
    main()
