"""Benchmark the coupled optimizer latency target from issue #32.

Reproduces the live Brave Origin shape — a main champion optimized against a
selected enemy roster through the real ``/api/optimize`` path — and reports
wall time, evaluation count, and the certified result so a performance change
can prove it kept the same answer.

Usage:
    python scripts/bench_coupled_optimizer.py            # time both scenarios
    python scripts/bench_coupled_optimizer.py --profile  # cProfile the slow one
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.app import app  # noqa: E402

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

SCENARIOS = {
    "cassiopeia_3champ": CASSIOPEIA_SCENARIO,
    "cassiopeia_5champ": FIVE_CHAMPION_SCENARIO,
    "mundo_3champ": MUNDO_SCENARIO,
}


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="store_true", help="cProfile one run")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default=None,
        help="run only one scenario",
    )
    parser.add_argument(
        "--json", action="store_true", help="dump the full response body"
    )
    args = parser.parse_args()
    app.config["RATE_LIMIT_ENABLED"] = False

    selected = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS

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
