#!/usr/bin/env python3
"""Concurrent load sanity test for /api/calculate and /api/bis.

Simulates N concurrent users each firing M requests against a local
Scryglass server, then asserts two operational budgets:

- p95 latency: calculate < 2.0s, bis < 5.0s (measured across both passes)
- result-cache hit ratio on the warm pass >= 0.9

Procedure
---------
1. Warm up the server (one calculate + one bis request).
2. Cold pass: every request misses and computes.
3. Checkpoint the server's cache counters (/api/cache-status).
4. Warm pass: the exact same request list is replayed at low concurrency so
   cache_set lands between gets; nearly every response must come from cache.
5. Re-read the counters; hit ratio = (hits_delta / (hits+misses)_delta) over
   the warm pass only.

Server
------
Without ``--url`` the script spawns its own local Flask server with
``DATABASE_URL`` pointed at a throwaway SQLite file (so the result cache is
enabled) and rate limiting disabled (this test measures the engine and cache,
not the abuse-control budget). To run against an external server, pass
``--url`` — it must have the result cache enabled and rate limiting relaxed,
otherwise the budgets/ratio cannot hold.

    python scripts/load_sanity.py [--url http://127.0.0.1:8000]
                                  [--users 10] [--requests 20] [--port 8123]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

CALCULATE_BUDGET_SECONDS = 2.0
BIS_BUDGET_SECONDS = 5.0
MIN_CACHE_HIT_RATIO = 0.9

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

CALCULATE_PAYLOADS = [
    {
        "champion": "Ahri",
        "level": 18,
        "items": ["Liandry's Torment", "Rabadon's Deathcap", "Void Staff"],
        "boots": "Sorcerer's Shoes",
        "role": "mid",
        "fight_mode": "one_rotation",
        "fight_duration": 5,
        "include_auto_attacks": False,
        "auto_attack_uptime": 0,
        "rotations": 1,
        "ability_ranks": _RANKS,
        "champion_options": {},
        "target_health": 2000.0,
        "target_armor": 50.0,
        "target_mr": 40.0,
        "enemies": [],
        "allies": [],
    },
    {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "ability_ranks": _RANKS,
        "champion_options": {},
        "target_health": 2200.0,
        "target_armor": 70.0,
        "target_mr": 45.0,
        "enemies": [],
        "allies": [],
    },
    {
        "champion": "Ashe",
        "level": 18,
        "items": ["Infinity Edge", "Runaan's Hurricane"],
        "boots": "Berserker's Greaves",
        "role": "bottom",
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.7,
        "ability_ranks": _RANKS,
        "champion_options": {},
        "target_health": 1800.0,
        "target_armor": 60.0,
        "target_mr": 40.0,
        "enemies": [],
        "allies": [],
    },
]

BIS_PAYLOADS = [
    {
        "champion": "Aatrox",
        "level": 18,
        "items": ["Infinity Edge", "Bloodthirster"],
        "boots": "Plated Steelcaps",
        "role": "top",
        "ability_ranks": _RANKS,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0.3,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "objective": "overall",
        "enemies": [
            {
                "champion": "Ambessa",
                "level": 18,
                "items": [],
                "role": "top",
                "ability_ranks": _RANKS,
            }
        ],
        "allies": [
            {
                "champion": "Lulu",
                "level": 18,
                "items": [],
                "role": "support",
                "ally_effects_enabled": True,
                "ability_ranks": _RANKS,
            }
        ],
    },
    {
        "champion": "Ahri",
        "level": 18,
        "items": ["Liandry's Torment"],
        "boots": "Sorcerer's Shoes",
        "role": "mid",
        "ability_ranks": _RANKS,
        "fight_mode": "one_rotation",
        "fight_duration": 5,
        "include_auto_attacks": False,
        "auto_attack_uptime": 0.0,
        "subject_team": "main",
        "subject_index": 0,
        "slot_index": 0,
        "slot_kind": "item",
        "objective": "overall",
        "enemies": [],
        "allies": [],
    },
]


def _free_port() -> int:
    """Return an ephemeral port that is currently free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _spawn_server(port: int, database: str) -> subprocess.Popen:
    """Start a local Flask server with the result cache enabled."""
    spawn_code = (
        "import sys; from src.app import app;"
        " app.config['RATE_LIMIT_ENABLED'] = False;"
        " app.run(host='127.0.0.1', port=int(sys.argv[1]),"
        " threaded=True, use_reloader=False, debug=False)"
    )
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database}"
    env.pop("REDIS_URL", None)
    env.pop("SENTRY_DSN", None)
    proc = subprocess.Popen(
        [sys.executable, "-c", spawn_code, str(port)],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


async def _wait_until_healthy(
    client: httpx.AsyncClient, base_url: str, timeout: float = 60.0
) -> None:
    """Poll /healthz until the server responds."""
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = await client.get(f"{base_url}/healthz")
            if response.status_code == 200:
                return
            last_error = f"healthz returned {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        await asyncio.sleep(0.25)
    raise RuntimeError(f"server at {base_url} did not become healthy: {last_error}")


async def _fire(
    client: httpx.AsyncClient,
    base_url: str,
    endpoint: str,
    payload: dict,
) -> tuple[str, float, int]:
    """POST one request; returns (endpoint, latency_seconds, status)."""
    started = time.perf_counter()
    try:
        response = await client.post(f"{base_url}{endpoint}", json=payload)
    except httpx.HTTPError:
        return endpoint, time.perf_counter() - started, -1
    return endpoint, time.perf_counter() - started, response.status_code


def _build_user_plan(users: int, requests: int) -> list[tuple[str, dict]]:
    """Interleave calculate and bis requests across users (50/50 mix)."""
    plan: list[tuple[str, dict]] = []
    for user in range(users):
        for index in range(requests):
            if (user + index) % 2 == 0:
                payload = CALCULATE_PAYLOADS[(user + index) % len(CALCULATE_PAYLOADS)]
                plan.append(("/api/calculate", payload))
            else:
                payload = BIS_PAYLOADS[(user + index) % len(BIS_PAYLOADS)]
                plan.append(("/api/bis", payload))
    return plan


async def _run_pass(
    client: httpx.AsyncClient,
    base_url: str,
    plan: list[tuple[str, dict]],
    concurrency: int,
) -> tuple[list[tuple[str, float, int]], list[str]]:
    """Execute the plan with a fixed worker pool.

    Returns ``(results, failures_detail)`` where each detail is a short
    ``endpoint -> status`` string for every non-200 response.
    """
    results: list[tuple[str, float, int]] = []
    failures_detail: list[str] = []
    queue: asyncio.Queue = asyncio.Queue()
    for item in plan:
        queue.put_nowait(item)

    async def worker() -> None:
        while not queue.empty():
            try:
                endpoint, payload = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            endpoint, latency, status = await _fire(client, base_url, endpoint, payload)
            results.append((endpoint, latency, status))
            if status != 200:
                failures_detail.append(f"{endpoint} -> {status}")
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    await asyncio.gather(*workers)
    return results, failures_detail


async def _cache_counters(client: httpx.AsyncClient, base_url: str) -> dict:
    response = await client.get(f"{base_url}/api/cache-status")
    response.raise_for_status()
    body = response.json()
    if not body.get("cache_enabled"):
        raise RuntimeError(
            "/api/cache-status reports cache_enabled=false — the result cache "
            "is off. Start the server with DATABASE_URL (or REDIS_URL) set."
        )
    return body


async def _run(
    base_url: str,
    users: int,
    requests: int,
    warm_concurrency: int,
) -> dict:
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await _wait_until_healthy(client, base_url)
        plan = _build_user_plan(users, requests)

        # Warm up so the first timed request is not paying one-time startup
        # (champion data + item effects loading).
        await _fire(client, base_url, "/api/calculate", CALCULATE_PAYLOADS[0])
        await _fire(client, base_url, "/api/bis", BIS_PAYLOADS[0])

        cold, _cold_failures = await _run_pass(
            client, base_url, plan, concurrency=users
        )
        before = await _cache_counters(client, base_url)
        warm, warm_failures = await _run_pass(
            client, base_url, plan, concurrency=warm_concurrency
        )
        after = await _cache_counters(client, base_url)

    hits_delta = int(after["hits"]) - int(before["hits"])
    misses_delta = int(after["misses"]) - int(before["misses"])
    counted = hits_delta + misses_delta
    hit_ratio = hits_delta / counted if counted else 0.0

    latencies: dict[str, list[float]] = {"calculate": [], "bis": []}
    failures = 0
    failures_detail = list(warm_failures)
    for endpoint, latency, status in cold + warm:
        latencies["calculate" if endpoint == "/api/calculate" else "bis"].append(
            latency
        )
        if status != 200:
            failures += 1
            failures_detail.append(f"{endpoint} -> {status}")

    summary = {
        "users": users,
        "requests_per_user": requests,
        "total_requests": len(cold) + len(warm),
        "failures": failures,
        "failures_detail": failures_detail,
        "warm_pass_requests": len(warm),
        "cache_counted": counted,
        "cache_hit_ratio": hit_ratio,
        "latencies": {
            name: {
                "p50": statistics.median(values),
                "p95": _percentile(values, 0.95),
                "max": max(values),
            }
            for name, values in latencies.items()
            if values
        },
    }
    return summary


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[index]


def _check_budgets(summary: dict) -> bool:
    """Assert p95 budgets and the warm-pass cache hit ratio; returns pass."""
    ok = True
    calculate_p95 = summary["latencies"]["calculate"]["p95"]
    bis_p95 = summary["latencies"]["bis"]["p95"]
    hit_ratio = summary["cache_hit_ratio"]
    if calculate_p95 >= CALCULATE_BUDGET_SECONDS:
        print(
            f"FAIL: /api/calculate p95 {calculate_p95:.2f}s >= "
            f"{CALCULATE_BUDGET_SECONDS:.1f}s budget"
        )
        ok = False
    if bis_p95 >= BIS_BUDGET_SECONDS:
        print(f"FAIL: /api/bis p95 {bis_p95:.2f}s >= {BIS_BUDGET_SECONDS:.1f}s budget")
        ok = False
    if hit_ratio < MIN_CACHE_HIT_RATIO:
        print(
            f"FAIL: warm-pass cache hit ratio {hit_ratio:.3f} < "
            f"{MIN_CACHE_HIT_RATIO}"
        )
        ok = False
    if summary["failures"]:
        print(f"FAIL: {summary['failures']} non-200 responses")
        ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="base URL of a running server")
    parser.add_argument(
        "--users", type=int, default=10, help="concurrent users (cold pass)"
    )
    parser.add_argument("--requests", type=int, default=20, help="requests per user")
    parser.add_argument(
        "--warm-concurrency", type=int, default=4, help="workers for the warm pass"
    )
    parser.add_argument(
        "--port", type=int, default=0, help="port for the spawned server"
    )
    args = parser.parse_args(argv)

    spawned = None
    database = ""
    if args.url:
        base_url = args.url.rstrip("/")
    else:
        port = args.port or _free_port()
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as handle:
            database = handle.name
        spawned = _spawn_server(port, database)
        base_url = f"http://127.0.0.1:{port}"
        print(f"[load_sanity] spawned server at {base_url} (db {database})")

    try:
        summary = asyncio.run(
            _run(base_url, args.users, args.requests, args.warm_concurrency)
        )
    finally:
        if spawned is not None:
            spawned.terminate()
            try:
                spawned.wait(timeout=10)
            except subprocess.TimeoutExpired:
                spawned.kill()
            try:
                Path(database).unlink(missing_ok=True)
            except OSError:
                pass

    print(
        f"[load_sanity] users={summary['users']} requests/user={summary['requests_per_user']}"
    )
    print(
        f"[load_sanity] total requests={summary['total_requests']} failures={summary['failures']}"
    )
    for name in ("calculate", "bis"):
        stats = summary["latencies"][name]
        print(
            f"[load_sanity] {name:<10} p50={stats['p50']:.3f}s "
            f"p95={stats['p95']:.3f}s max={stats['max']:.3f}s"
        )
    print(
        f"[load_sanity] warm-pass cache: {summary['cache_counted']} counted, "
        f"hit ratio={summary['cache_hit_ratio']:.3f}"
    )
    if summary["failures_detail"]:
        print("[load_sanity] failures:", summary["failures_detail"][:20])

    ok = _check_budgets(summary)
    print(f"[load_sanity] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
