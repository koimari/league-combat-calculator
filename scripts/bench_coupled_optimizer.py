"""Benchmark the coupled optimizer: latency, and the work behind it.

Two instruments live here.

The original one reproduces the live Brave Origin shape — a main champion
optimized against a selected enemy roster through the real ``/api/optimize``
path — and reports wall time, evaluation count, and the certified result so a
performance change can prove it kept the same answer.

``--fixed-work`` is the campaign instrument (runbook R-01 row 8).  Wall time
is a property of the machine; the *work* a search does is a property of the
code, and the four counter families below plus the residual
(``pair fights - evaluations x enemies``, R-25) move the instant a cache stops
hitting or a candidate stops compiling, long before wall time leaves the
noise.  The counters ride the search itself through
``app.config["OPTIMIZER_INSTRUMENTATION"]`` and the optimizer's own
``work_counters`` parameter — never a monkey-patched module attribute (R-24),
because a patched harness measures something CI does not ship.

Usage:
    python scripts/bench_coupled_optimizer.py               # time every scenario
    python scripts/bench_coupled_optimizer.py --profile     # cProfile the slow one
    python scripts/bench_coupled_optimizer.py --fixed-work --isolate --json
    python scripts/bench_coupled_optimizer.py --fixed-work --isolate --no-compiled --json
    python scripts/bench_coupled_optimizer.py --alloc --json      # the probe alone

``--no-compiled`` is R-01 row 11 and runs *both* routings: the row is defined
against row 8's default run, so the command pairs them itself, reports
``routing_divergences`` per scenario and exits non-zero on any.

The fixed-work reading carries ``allocation_peak_bytes`` per scenario, from
the same ``allocation_probe`` ``--alloc`` runs alone, so the one command
Phase 0's criterion 4 names emits everything that criterion lists.  Emitting
the peak is not gating it — R-28 gates allocation once, at Phase 4 S4.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import subprocess
import sys
import time
import tracemalloc
from collections import Counter
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.app import app  # noqa: E402

# ``/api/optimize`` clamps ``time_budget_ms`` into [100, 60_000] and defaults
# to 12_000.  A budget the machine can exhaust makes every counter below a
# property of the machine, so the harness always asks for the ceiling and
# voids any run that still reports ``truncated`` (R-09).
TIME_BUDGET_CLAMP_MS = 60_000

# The issue's headline scenario: Cassiopeia optimized into an Alistar +
# Dr. Mundo front line over a timed window with auto attacks — the shape
# that measured 3.6-7.0 seconds live.
CASSIOPEIA_SCENARIO = {
    "champion": "Cassiopeia",
    "level": 13,
    "fight_mode": "one_rotation",
    "role": "mid",
    "enemies": [
        {
            "champion": "Alistar",
            "level": 13,
            "role": "support",
            "boots": "Plated Steelcaps",
            "items": ["Randuin's Omen", "Bramble Vest"],
        },
        {
            "champion": "Dr. Mundo",
            "level": 13,
            "role": "top",
            "boots": "Mercury's Treads",
            "items": ["Kaenic Rookern", "Warmog's Armor", "Spirit Visage"],
        },
    ],
}

# The five-champion stress shape from the issue's "three-to-five champion"
# goal: the same front line plus an ally and a third enemy.
FIVE_CHAMPION_SCENARIO = {
    **CASSIOPEIA_SCENARIO,
    "allies": [
        {
            "champion": "Alistar",
            "level": 13,
            "role": "support",
            "boots": "Mercury's Treads",
            "items": ["Dead Man's Plate"],
        },
    ],
    "enemies": CASSIOPEIA_SCENARIO["enemies"]
    + [
        {
            "champion": "Vayne",
            "level": 13,
            "role": "bottom",
            "boots": "Berserker's Greaves",
            "items": ["Kraken Slayer", "Phantom Dancer"],
        },
    ],
}

# The issue's second live shape: a tank (enemy Dr. Mundo in the report,
# run here as the optimized champion) built into a mixed enemy pair.
MUNDO_SCENARIO = {
    "champion": "Dr. Mundo",
    "level": 13,
    "fight_mode": "one_rotation",
    "role": "top",
    "enemies": [
        {
            "champion": "Cassiopeia",
            "level": 13,
            "role": "mid",
            "boots": "Sorcerer's Shoes",
            "items": ["Rabadon's Deathcap", "Void Staff"],
        },
        {
            "champion": "Vayne",
            "level": 13,
            "role": "bottom",
            "boots": "Berserker's Greaves",
            "items": ["Kraken Slayer", "Phantom Dancer"],
        },
    ],
}

# The campaign's fourth scenario (runbook R-27).  The three above author no
# ``cc_kind`` at all, so the immobilize-triggered half of the model — the
# Imperial Mandate Command amp this whole campaign exists because of — is
# invisible to the harness that is supposed to police it.  Syndra's E is
# authored as a stun (``champions/syndra.py``) and Imperial Mandate is locked
# into every candidate, so the amp is priced on every evaluation.
SYNDRA_MANDATE_SCENARIO = {
    "champion": "Syndra",
    "level": 13,
    "fight_mode": "one_rotation",
    "role": "mid",
    "locked_items": ["Imperial Mandate"],
    "enemies": CASSIOPEIA_SCENARIO["enemies"],
}

SCENARIOS = {
    "cassiopeia_3champ": CASSIOPEIA_SCENARIO,
    "cassiopeia_5champ": FIVE_CHAMPION_SCENARIO,
    "mundo_3champ": MUNDO_SCENARIO,
    "syndra_mandate_3champ": SYNDRA_MANDATE_SCENARIO,
}

# One fully locked build per scenario, so ``allocation_probe`` scores exactly
# one candidate: with every legendary slot and the boots locked the search
# has a single legal option and skips greedy fill, hill climbing and the
# runner-up sweep entirely.  Each is the build that scenario's unlocked
# search elects today — pinned rather than re-derived, because an allocation
# figure is only comparable across commits when the build is the same one.
PROBE_BUILDS = {
    "cassiopeia_3champ": {
        "items": [
            "Actualizer",
            "Void Staff",
            "Rabadon's Deathcap",
            "Malignance",
            "Stormsurge",
        ],
        "boots": "Sorcerer's Shoes",
    },
    "cassiopeia_5champ": {
        "items": [
            "Malignance",
            "Void Staff",
            "Rabadon's Deathcap",
            "Actualizer",
            "Stormsurge",
        ],
        "boots": "Sorcerer's Shoes",
    },
    "mundo_3champ": {
        "items": [
            "Serylda's Grudge",
            "Stridebreaker",
            "Voltaic Cyclosword",
            "Bastionbreaker",
            "Trinity Force",
        ],
        "boots": "Sorcerer's Shoes",
    },
    "syndra_mandate_3champ": {
        "items": [
            "Imperial Mandate",
            "Void Staff",
            "Rabadon's Deathcap",
            "Actualizer",
            "Stormsurge",
        ],
        "boots": "Sorcerer's Shoes",
    },
}


def _measure_the_optimizer_not_the_cache() -> None:
    """Put the app in the one configuration a benchmark may measure.

    The shared token bucket would 429 a long run, and on a deployment with
    ``DATABASE_URL`` or ``REDIS_URL`` set the result cache would answer every
    repeat after the first — so the same command would report the optimizer
    on one machine and a cache lookup on another.
    """
    app.config["RATE_LIMIT_ENABLED"] = False
    app.config["TESTING"] = True


@dataclass(slots=True)
class WorkCounters:
    """One search's work, threaded onto the search itself (R-24).

    ``public_evaluations`` is read back from the optimizer's own response
    rather than counted here: it is a published figure, and a second counting
    site for it could only ever disagree with the number the API returns.
    The other four are incremented inside ``src/`` — ``_evaluate_build`` for
    the two proposal counters, ``participant_timeline._pair_run_fight`` for
    the pair fights, and the compiled/receipt gate for the rungs.
    """

    public_evaluations: int = 0
    measured_proposals: int = 0
    score_memo_misses: int = 0
    pair_run_fight_calls: int = 0
    rungs: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready counters, rungs included."""
        return {
            "public_evaluations": self.public_evaluations,
            "measured_proposals": self.measured_proposals,
            "score_memo_misses": self.score_memo_misses,
            "pair_run_fight_calls": self.pair_run_fight_calls,
            "rungs": dict(sorted(self.rungs.items())),
        }


def residual(counters: WorkCounters, n_enemies: int) -> int:
    """Pair fights minus evaluations x enemies — the cache/fallback tripwire.

    A perfectly cached search runs exactly one pair fight per (evaluation,
    enemy).  Everything above that is roster-to-roster setup, cache misses
    and fallbacks, so the difference is a small number whose *movement* is
    the signal (R-25).
    """
    return counters.pair_run_fight_calls - counters.public_evaluations * n_enemies


def _enemy_count(scenario: str) -> int:
    """How many enemies the scenario's main champion fights."""
    return len(SCENARIOS[scenario].get("enemies", ()))


def _fixed_work_payload(scenario: str) -> dict[str, Any]:
    """The scenario's request at the app's time-budget ceiling (R-09)."""
    return {**SCENARIOS[scenario], "time_budget_ms": TIME_BUDGET_CLAMP_MS}


def report_from_response(
    scenario: str, body: Mapping[str, Any], counters: WorkCounters, wall_ms: float
) -> dict[str, Any]:
    """One repeat's counters, residual, rungs, winner, score and wall.

    Void when the optimizer reports ``truncated``: a search the wall clock
    cut short measured the machine, not the code.  Kept separate from the
    request so the void path has a seam its own test can drive.
    """
    truncated = bool(body.get("truncated", False))
    return {
        "scenario": scenario,
        "void": truncated,
        "truncated": truncated,
        "counters": counters.as_dict(),
        "residual": residual(counters, _enemy_count(scenario)),
        "rungs": dict(sorted(counters.rungs.items())),
        "timeline_complete": bool(
            body.get("search_timeline_coverage", {}).get("complete", False)
        ),
        "winner": {"items": body.get("items"), "boots": body.get("boots")},
        "score": body.get("total_damage"),
        "wall_ms": round(wall_ms, 1),
    }


def _single_run(scenario: str, *, compiled: bool) -> dict[str, Any]:
    """Post one scenario with the counters installed and report the run."""
    counters = WorkCounters()
    _measure_the_optimizer_not_the_cache()
    app.config["OPTIMIZER_INSTRUMENTATION"] = {
        "work_counters": counters,
        "use_compiled_walk": compiled,
    }
    try:
        client = app.test_client()
        started = time.perf_counter()
        response = client.post("/api/optimize", json=_fixed_work_payload(scenario))
        wall_ms = (time.perf_counter() - started) * 1000
    finally:
        app.config["OPTIMIZER_INSTRUMENTATION"] = {}
    if response.status_code != 200:
        raise RuntimeError(
            f"{scenario}: optimizer returned {response.status_code}: {response.text}"
        )
    body = response.get_json()
    counters.public_evaluations = int(body["evaluations"])
    return report_from_response(scenario, body, counters, wall_ms)


def _isolated_run(scenario: str, *, compiled: bool) -> dict[str, Any]:
    """One repeat in a fresh interpreter (R-26).

    ``_RESOLVED_DAMAGE_EFFECTS``, ``_DERIVED_RULE_CACHE``, ``_MATRIX_DPS_CACHE``,
    ``_ITEM_STATS_MEMO`` and ``data_fetcher``'s ``lru_cache`` all survive a
    repeat and a scenario switch, so an in-process repeat measures a warmer
    process than the one before it.
    """
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--fixed-work",
        "--scenario",
        scenario,
        "--repeats",
        "1",
        "--json",
        # The child measures exactly the routing it was asked for.  Without
        # this, ``--no-compiled`` would make the child run both routings the
        # way the top-level row 11 command does, and the parent would be
        # measuring a comparison inside its own comparison.
        "--single-routing",
    ]
    if not compiled:
        command.append("--no-compiled")
    finished = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if finished.returncode != 0:
        raise RuntimeError(
            f"{scenario}: isolated repeat failed ({finished.returncode}): "
            f"{(finished.stderr or finished.stdout).strip()[:400]}"
        )
    return json.loads(finished.stdout)[scenario]["repeats"][0]


def fixed_work_report(
    scenario: str, *, isolate: bool, repeats: int, compiled: bool = True
) -> dict[str, Any]:
    """One scenario's fixed-work reading, aggregated over its repeats.

    The reported counters come from the first non-void repeat and the wall
    time is the best of them; every repeat is kept so
    :func:`determinism_probe` can decide which counters may be equality
    gated.  A scenario whose every repeat voids is reported void — never as
    an absent-but-assumed-green counter (R-09).
    """
    runs = [
        (
            _isolated_run(scenario, compiled=compiled)
            if isolate
            else _single_run(scenario, compiled=compiled)
        )
        for _ in range(repeats)
    ]
    live = [run for run in runs if not run["void"]]
    if not live:
        return {
            "scenario": scenario,
            "void": True,
            "reason": "every repeat reported truncated",
            "repeats": runs,
        }
    report = dict(live[0])
    report["wall_ms"] = min(run["wall_ms"] for run in live)
    report["repeats"] = runs
    report["isolated"] = isolate
    report["compiled_walk"] = compiled
    return report


_PROBED_COUNTERS = (
    "public_evaluations",
    "measured_proposals",
    "score_memo_misses",
    "pair_run_fight_calls",
)


def determinism_probe(
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, Literal["exact", "tolerant"]]:
    """Which counters repeated exactly, and may therefore be equality gated.

    R-08: a counter that does not reproduce across five isolated repeats is
    demoted to a ratchet with its spread recorded, because an unexplainable
    drift of two destroys a gate's authority faster than having no gate.
    """
    verdict: dict[str, Literal["exact", "tolerant"]] = {}
    for name in (*_PROBED_COUNTERS, "residual"):
        if name == "residual":
            values = [report["residual"] for report in reports]
        else:
            values = [report["counters"][name] for report in reports]
        verdict[name] = "exact" if len(set(values)) == 1 else "tolerant"
    rung_shapes = {json.dumps(report["rungs"], sort_keys=True) for report in reports}
    verdict["rungs"] = "exact" if len(rung_shapes) == 1 else "tolerant"
    return verdict


def determinism_spread(reports: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Max minus min per counter — the tolerance a demoted counter carries."""
    spread: dict[str, int] = {}
    for name in (*_PROBED_COUNTERS, "residual"):
        if name == "residual":
            values = [report["residual"] for report in reports]
        else:
            values = [report["counters"][name] for report in reports]
        spread[name] = max(values) - min(values)
    return spread


def routing_divergences(
    compiled_report: Mapping[str, Any], receipt_report: Mapping[str, Any]
) -> tuple[str, ...]:
    """Where the two routings answered differently — R-01 row 11's verdict.

    Row 11 runs one scenario through the compiled score path and again
    forced onto the receipt walk, and demands the same winner and the same
    score.  The rung histogram is *expected* to differ and is deliberately
    not compared here; a different **answer** is a routing change wearing a
    performance change's clothes, which is the only thing this row catches.
    The empty tuple is the pass condition, so the gate has a verdict a
    caller reads rather than two JSON blobs a human eyeballs.
    """
    scenario = compiled_report.get("scenario") or receipt_report.get("scenario") or "?"
    voided = [
        f"{scenario}: the {label} routing voided "
        f"({report.get('reason', 'a repeat reported truncated')})"
        for label, report in (
            ("compiled", compiled_report),
            ("receipt-walk", receipt_report),
        )
        if report.get("void")
    ]
    if voided:
        return tuple(voided)
    failures = []
    if compiled_report["winner"] != receipt_report["winner"]:
        failures.append(
            f"{scenario}: winner {compiled_report['winner']} "
            f"-> {receipt_report['winner']}"
        )
    if compiled_report["score"] != receipt_report["score"]:
        failures.append(
            f"{scenario}: score {compiled_report['score']} "
            f"-> {receipt_report['score']}"
        )
    return tuple(failures)


def routing_comparison(
    scenarios: Sequence[str],
    *,
    isolate: bool,
    repeats: int,
    determinism: bool = False,
    report: Any = None,
) -> dict[str, dict[str, Any]]:
    """Every named scenario run both ways, each carrying its own verdict.

    This is the body of R-01 row 11's command: the row is defined against
    row 8's default run, so the command runs that routing itself instead of
    trusting a reader to pair two invocations.  Each entry is the
    receipt-walk report plus the compiled run under ``compiled_run`` and
    :func:`routing_divergences`'s verdict under ``routing_divergences``.
    ``report`` is the seam a test drives to make the verdict red on demand
    (R-05); it defaults to :func:`fixed_work_report`.
    """
    measure = report or fixed_work_report
    comparison: dict[str, dict[str, Any]] = {}
    for name in scenarios:
        compiled_report = measure(name, isolate=isolate, repeats=repeats, compiled=True)
        receipt_report = measure(name, isolate=isolate, repeats=repeats, compiled=False)
        entry = dict(receipt_report)
        entry["compiled_run"] = compiled_report
        entry["routing_divergences"] = list(
            routing_divergences(compiled_report, receipt_report)
        )
        if determinism and not entry["void"]:
            entry["determinism"] = determinism_probe(entry["repeats"])
            entry["spread"] = determinism_spread(entry["repeats"])
        comparison[name] = entry
    return comparison


def allocation_probe(scenario: str) -> int:
    """``tracemalloc`` peak bytes for one isolated candidate evaluation.

    The scenario's probe build is locked into every slot, so the optimizer's
    exact regime scores exactly one candidate and the peak is that single
    coupled evaluation's — Phase 4 S4 trades per-fight dict churn for cached
    frozen records and this is the number that has to hold (R-28).
    """
    build = PROBE_BUILDS[scenario]
    payload = {
        **SCENARIOS[scenario],
        "locked_items": build["items"],
        "locked_boots": build["boots"],
        "max_legendary_slots": len(build["items"]),
        "time_budget_ms": TIME_BUDGET_CLAMP_MS,
    }
    _measure_the_optimizer_not_the_cache()
    client = app.test_client()
    # Warm every module-level cache first: a probe that measures the first
    # item-data parse of the process is measuring the parse, not the walk.
    warmup = client.post("/api/optimize", json=payload)
    if warmup.status_code != 200:
        raise RuntimeError(f"{scenario}: allocation probe: {warmup.text}")
    tracemalloc.start()
    response = client.post("/api/optimize", json=payload)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    if response.status_code != 200:
        raise RuntimeError(f"{scenario}: allocation probe: {response.text}")
    if int(response.get_json()["evaluations"]) != 1:
        raise RuntimeError(
            f"{scenario}: allocation probe scored "
            f"{response.get_json()['evaluations']} candidates, not one — the "
            "probe build no longer fills every slot"
        )
    return int(peak)


def attach_allocation_peaks(reports: MutableMapping[str, Any]) -> None:
    """Give every fixed-work report its ``allocation_peak_bytes`` (R-28).

    The peak rides the fixed-work reading so one invocation carries everything
    Phase 0's criterion 4 names — counters, residual, rungs, wall and the
    allocation probe — rather than leaving the last of them to a second
    command a reader has to know about.  Emitting it is not gating it: R-28
    gates allocation once, at Phase 4 S4, against the margin in the receipt.

    Probed here, in this process and in scenario order, which is exactly how
    ``--alloc`` captures the figures the receipt holds — and why ``--isolate``
    does not reach it.  A peak is only comparable to the one beside it when
    both were read on the same basis, so a probe-per-subprocess variant would
    silently re-define the committed number rather than reproduce it.  What
    isolation buys the counters, ``allocation_probe``'s own warm-up request
    buys the peak.
    """
    for name, report in reports.items():
        report["allocation_peak_bytes"] = allocation_probe(name)


def run_scenario(name: str, payload: dict, repeats: int = 3) -> dict:
    """POST one scenario through the real optimize endpoint and time it."""
    client = app.test_client()
    timings = []
    body = None
    for _ in range(repeats):
        started = time.perf_counter()
        response = client.post("/api/optimize", json=payload)
        elapsed = time.perf_counter() - started
        if response.status_code != 200:
            raise RuntimeError(
                f"{name}: optimizer returned {response.status_code}: {response.text}"
            )
        body = response.get_json()
        timings.append(elapsed)
    best = min(timings)
    print(f"{name}:")
    print(f"  wall time (best of {repeats}): {best * 1000:.1f} ms")
    print(f"  all runs: {', '.join(f'{t * 1000:.0f}' for t in timings)} ms")
    print(f"  evaluations: {body['evaluations']}")
    print(f"  build: {body['items']} + {body['boots']}")
    print(f"  score: {body['total_damage']}")
    print(f"  certified: {body['is_certified_best']}")
    print(f"  search timeline complete: {body['search_timeline_coverage']['complete']}")
    return body


def _print_fixed_work(reports: Mapping[str, Mapping[str, Any]]) -> None:
    """Human-readable form of the fixed-work reports."""
    for name, report in reports.items():
        print(f"{name}:")
        if report["void"]:
            print(f"  VOID — {report['reason']}")
            continue
        counters = report["counters"]
        for counter in _PROBED_COUNTERS:
            print(f"  {counter}: {counters[counter]}")
        print(f"  residual: {report['residual']}")
        print(f"  rungs: {report['rungs']}")
        print(f"  timeline complete: {report['timeline_complete']}")
        print(f"  winner: {report['winner']['items']} + {report['winner']['boots']}")
        print(f"  score: {report['score']}")
        print(f"  wall (best of {len(report['repeats'])}): {report['wall_ms']} ms")


def _run_row_eleven(args: argparse.Namespace, selected: Mapping[str, Any]) -> None:
    """R-01 row 11: both routings, the verdict, and a non-zero exit on any.

    The row is defined against row 8's default run, so the command runs that
    routing itself rather than trusting a reader to pair two invocations —
    and it reports its verdict as an exit code, because a gate whose failure
    is a paragraph a human must notice is the shape this campaign exists to
    remove.
    """
    reports = routing_comparison(
        sorted(selected),
        isolate=args.isolate,
        repeats=args.repeats,
        determinism=args.determinism,
    )
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_fixed_work(reports)
    diverged = [
        failure
        for report in reports.values()
        for failure in report["routing_divergences"]
    ]
    for failure in diverged:
        print(f"ROUTING DIVERGENCE — {failure}", file=sys.stderr)
    if diverged:
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    """The CLI: the latency bench, the fixed-work instrument, the probes."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", action="store_true", help="cProfile one run")
    parser.add_argument(
        "--scenario", choices=sorted(SCENARIOS), default=None, help="run only one"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--fixed-work",
        action="store_true",
        help="counters, residual and rungs at the time-budget ceiling",
    )
    parser.add_argument(
        "--isolate",
        action="store_true",
        help="one subprocess per repeat, so no cache survives into the next",
    )
    parser.add_argument(
        "--no-compiled",
        action="store_true",
        help=(
            "R-01 row 11: run each scenario on the receipt walk and again on "
            "the compiled path, and exit non-zero if they disagree"
        ),
    )
    parser.add_argument(
        "--single-routing",
        action="store_true",
        help=(
            "measure only the routing asked for, skipping row 11's comparison "
            "— what an isolated repeat's child process runs"
        ),
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help="repeats per fixed-work scenario"
    )
    parser.add_argument(
        "--determinism",
        action="store_true",
        help="classify each counter exact or tolerant over the repeats (R-08)",
    )
    parser.add_argument(
        "--alloc", action="store_true", help="tracemalloc peak for one evaluation"
    )
    return parser


def _run_fixed_work(args: argparse.Namespace, selected: Mapping[str, Any]) -> None:
    """R-01 row 8's command body: one routing, counters, peaks, and the print.

    The peak rides the reading unless this process is an isolated repeat's
    child, which is measuring one routing for its parent rather than answering
    criterion 4.
    """
    reports = {
        name: fixed_work_report(
            name,
            isolate=args.isolate,
            repeats=args.repeats,
            compiled=not args.no_compiled,
        )
        for name in selected
    }
    if not args.single_routing:
        attach_allocation_peaks(reports)
    if args.determinism:
        for report in reports.values():
            if report["void"]:
                continue
            report["determinism"] = determinism_probe(report["repeats"])
            report["spread"] = determinism_spread(report["repeats"])
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        _print_fixed_work(reports)


def main() -> None:
    """CLI entry point."""
    args = _build_parser().parse_args()
    _measure_the_optimizer_not_the_cache()

    selected = (
        {args.scenario: SCENARIOS[args.scenario]} if args.scenario else dict(SCENARIOS)
    )

    if args.alloc:
        peaks = {name: allocation_probe(name) for name in selected}
        print(json.dumps(peaks, indent=2) if args.json else peaks)
        return

    if args.fixed_work:
        if args.no_compiled and not args.single_routing:
            _run_row_eleven(args, selected)
        else:
            _run_fixed_work(args, selected)
        return

    if args.profile:
        name, payload = next(iter(selected.items()))
        client = app.test_client()
        profiler = cProfile.Profile()
        profiler.enable()
        response = client.post("/api/optimize", json=payload)
        profiler.disable()
        if response.status_code != 200:
            raise RuntimeError(f"{name}: {response.status_code}: {response.text}")
        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative").print_stats(40)
        stats.sort_stats("tottime").print_stats(30)
        return

    for name, payload in selected.items():
        body = run_scenario(name, payload)
        if args.json:
            print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
