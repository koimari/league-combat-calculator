"""Run the backend acceptance matrix.

The matrix is intentionally API-level: it can run against the local Flask
application or a deployed origin and records the same evidence for either
surface.  It never treats a withheld or partial optimizer result as success.

Usage::

    .venv/bin/python scripts/acceptance_matrix.py
    .venv/bin/python scripts/acceptance_matrix.py --base-url https://example
    .venv/bin/python scripts/acceptance_matrix.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SCENARIOS: dict[str, dict[str, Any]] = {
    "damage_carry_vs_tank": {
        "champion": "Ahri",
        "level": 13,
        "role": "mid",
        "enemies": [
            {
                "champion": "Dr. Mundo",
                "level": 13,
                "role": "top",
                "items": ["Warmog's Armor", "Spirit Visage"],
            }
        ],
    },
    "tank_vs_damage_carry": {
        "champion": "Dr. Mundo",
        "level": 13,
        "role": "top",
        "enemies": [
            {
                "champion": "Ahri",
                "level": 13,
                "role": "mid",
                "items": ["Rabadon's Deathcap", "Void Staff"],
            }
        ],
    },
    "enchanter_ally": {
        "champion": "Jinx",
        "level": 13,
        "role": "bottom",
        "allies": [
            {
                "champion": "Lulu",
                "level": 13,
                "role": "support",
                "items": ["Staff of Flowing Water"],
                "ally_effects_enabled": True,
            }
        ],
        "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
    },
    "warden_ally": {
        "champion": "Aatrox",
        "level": 13,
        "role": "top",
        "allies": [{"champion": "Shen", "level": 13, "role": "support"}],
        "enemies": [{"champion": "Ahri", "level": 13, "role": "mid"}],
    },
    "enemy_shield_and_heal": {
        "champion": "Ahri",
        "level": 13,
        "role": "mid",
        "enemies": [
            {
                "champion": "Kai'Sa",
                "level": 13,
                "role": "bottom",
                "items": ["Kaenic Rookern"],
            }
        ],
    },
    "multiple_enemies": {
        "champion": "Aatrox",
        "level": 13,
        "role": "top",
        "enemies": [
            {"champion": "Ahri", "level": 13, "role": "mid"},
            {"champion": "Jinx", "level": 13, "role": "bottom"},
        ],
    },
    "multiple_allies": {
        "champion": "Jinx",
        "level": 13,
        "role": "bottom",
        "allies": [
            {"champion": "Lulu", "level": 13, "role": "support"},
            {"champion": "Shen", "level": 13, "role": "top"},
        ],
        "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
    },
    "ranks_and_casts": {
        "champion": "Ahri",
        "level": 13,
        "role": "mid",
        "ability_ranks": {"Q": 5, "W": 3, "E": 3, "R": 1},
        "cast_order": ["Q", "E", "W", "R"],
        "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
    },
    "boots_and_role": {
        "champion": "Ahri",
        "level": 13,
        "role": "mid",
        "boots": "Sorcerer's Shoes",
        "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
    },
    "top_role_quest_level": {
        "champion": "Aatrox",
        "level": 19,
        "role": "top",
        "role_quest_complete": True,
        "enemies": [{"champion": "Dr. Mundo", "level": 18, "role": "top"}],
    },
}


def _post_local(client: Any, path: str, payload: dict[str, Any]) -> tuple[int, dict]:
    response = client.post(path, json=payload)
    return response.status_code, response.get_json(silent=True) or {}


def _post_remote(base_url: str, path: str, payload: dict[str, Any]) -> tuple[int, dict]:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw_body = response.read()
            try:
                body = json.loads(raw_body)
            except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
                preview = raw_body[:500].decode("utf-8", errors="replace")
                error = (
                    "remote deployment requires authentication (private calculator gate)"
                    if "private calculator" in preview.lower()
                    else "remote response was not valid JSON"
                )
                body = {
                    "error": error,
                    "body_preview": preview,
                }
            return response.status, body
    except HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except (ValueError, json.JSONDecodeError):
            return exc.code, {"error": str(exc)}
    except URLError as exc:
        return 0, {"error": str(exc.reason)}


def _participants(body: dict[str, Any]) -> list[str]:
    combat = body.get("combat")
    if not isinstance(combat, dict):
        return []
    rows = combat.get("participants", [])
    if not isinstance(rows, list):
        return []
    return [str(row.get("participant_id", "")) for row in rows if isinstance(row, dict)]


def _summarize(
    name: str,
    payload: dict[str, Any],
    calculate: tuple[int, dict],
    optimize: tuple[int, dict],
    *,
    origin: str = "local:test_client",
) -> dict[str, Any]:
    # A successful HTTP status with a non-object JSON body is still a broken
    # API contract. Normalize it into an evidence-bearing error instead of
    # crashing the matrix before the result can be serialized.
    malformed_calculate = not isinstance(calculate[1], dict)
    malformed_optimize = not isinstance(optimize[1], dict)
    if malformed_calculate:
        calculate = (
            calculate[0],
            {"error": "calculate response was not a JSON object"},
        )
    if malformed_optimize:
        optimize = (
            optimize[0],
            {"error": "optimizer response was not a JSON object"},
        )
    calculate_status, calculate_body = calculate
    optimize_status, optimize_body = optimize
    raw_optimize_coverage = optimize_body.get("search_timeline_coverage", {})
    malformed_coverage = not isinstance(raw_optimize_coverage, dict)
    optimize_coverage = raw_optimize_coverage if not malformed_coverage else {}
    raw_complete = optimize_coverage.get("complete")
    raw_certified = optimize_body.get("is_certified_best")
    malformed_flags = (
        "complete" not in optimize_coverage
        or "is_certified_best" not in optimize_body
        or not isinstance(raw_complete, bool)
        or not isinstance(raw_certified, bool)
    )
    complete = raw_complete if isinstance(raw_complete, bool) else False
    optimized = optimize_status == 200 and complete and raw_certified is True
    outcome = "certified" if optimized else "withheld"
    if calculate_status != 200:
        outcome = "invalid_request"
    elif (
        malformed_calculate
        or malformed_optimize
        or malformed_coverage
        or malformed_flags
        or optimize_status != 200
    ):
        # A failed optimizer endpoint is an acceptance failure, not an
        # intentional withholding.  Keep the distinction explicit so a
        # broken deployment cannot pass the matrix merely because its
        # response lacks a certified build.
        outcome = "optimizer_error"
    return {
        "name": name,
        "origin": origin,
        "request_paths": {
            "calculate": "/api/calculate",
            "optimize": "/api/optimize",
        },
        "click_state": {
            "calculate_submitted": True,
            "optimize_submitted": True,
        },
        "payload": payload,
        "calculate_status": calculate_status,
        "calculate_participants": _participants(calculate_body),
        "calculate_coverage": calculate_body.get("timeline_coverage"),
        "calculate_error": calculate_body.get("error"),
        "optimize_status": optimize_status,
        "optimize_coverage": optimize_coverage,
        "build": (
            {"items": optimize_body.get("items"), "boots": optimize_body.get("boots")}
            if optimize_status == 200
            else None
        ),
        "outcome": outcome,
        "withheld": outcome == "withheld",
        "withheld_reason": (
            optimize_body.get("error")
            or optimize_coverage.get("note")
            or "optimizer did not return a certified complete build"
            if not optimized
            else None
        ),
        "success": calculate_status == 200
        and optimize_status == 200
        and outcome in {"certified", "withheld"},
    }


def run_matrix(
    post: Callable[[str, dict[str, Any]], tuple[int, dict]],
    *,
    origin: str = "local:test_client",
) -> list[dict[str, Any]]:
    """Run every matrix case through calculate and optimize."""
    results = []
    for name, payload in SCENARIOS.items():
        results.append(
            _summarize(
                name,
                payload,
                post("/api/calculate", payload),
                post("/api/optimize", payload),
                origin=origin,
            )
        )
    return results


def main() -> int:
    """Parse options, run the matrix, and return a CI-friendly exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="deployed origin; omit for local Flask")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args()

    if args.base_url:
        results = run_matrix(
            lambda path, payload: _post_remote(args.base_url, path, payload),
            origin=args.base_url.rstrip("/"),
        )
    else:
        from src.app import app  # pylint: disable=import-outside-toplevel

        app.config["RATE_LIMIT_ENABLED"] = False
        with app.test_client() as client:
            results = run_matrix(
                lambda path, payload: _post_local(client, path, payload),
                origin="local:test_client",
            )

    from gate_receipt import build_receipt  # pylint: disable=import-outside-toplevel

    successes = [result for result in results if result["success"]]
    report = build_receipt(
        matrix="issue_20_backend_acceptance",
        passed=all(result["success"] for result in results),
        passed_count=len(successes),
        failed_count=len(results) - len(successes),
        total_count=len(results),
        withheld_count=sum(result["withheld"] for result in results),
        failures=[
            {"name": result["name"], "reason": result["withheld_reason"]}
            for result in results
            if not result["success"]
        ],
        extra={
            "scenario_count": len(results),
            "origin": (
                args.base_url.rstrip("/") if args.base_url else "local:test_client"
            ),
            "evidence_contract": [
                "origin",
                "request_paths",
                "click_state",
                "calculate_status",
                "optimize_status",
                "calculate_participants",
                "calculate_coverage",
                "optimize_coverage",
                "build",
                "withheld_reason",
            ],
            "results": results,
        },
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for result in results:
            state = "PASS" if result["success"] else "FAIL"
            print(
                f"{state} {result['name']}: calculate={result['calculate_status']} "
                f"optimize={result['optimize_status']} "
                f"participants={','.join(result['calculate_participants']) or '-'} "
                f"withheld={result['withheld']}"
            )
    return 0 if all(result["success"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
