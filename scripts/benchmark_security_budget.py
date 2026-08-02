"""Reproduce the max-valid optimizer workload used for abuse-budget tuning."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.app import _RATE_LIMIT_POLICIES, app  # noqa: E402
from src.calculator.champions import get_champion_options_meta  # noqa: E402


def _maximum_options(champion_name: str) -> dict[str, bool | int | float]:
    """Choose each declared option's most expensive public-side value."""
    options = {}
    for option in get_champion_options_meta(champion_name)["options"]:
        options[option["key"]] = True if option["type"] == "bool" else option["max"]
    return options


def main() -> None:
    """Time one exact Ezreal request at every public maximum and report CPU share."""
    payload = {
        "champion": "Ezreal",
        "level": 20,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1,
        "target_health": 10_000,
        "target_bonus_health": 10_000,
        "target_armor": 500,
        "target_mr": 500,
        "role": "bottom",
        "role_quest_complete": True,
        "max_legendary_slots": 6,
        "champion_options": _maximum_options("Ezreal"),
    }
    app.config["RATE_LIMIT_ENABLED"] = False
    started_cpu = time.process_time()
    started_wall = time.perf_counter()
    response = app.test_client().post("/api/optimize", json=payload)
    if response.status_code != 200:
        raise RuntimeError(
            f"Optimizer returned {response.status_code}: {response.text}"
        )
    cpu_seconds = time.process_time() - started_cpu
    wall_seconds = time.perf_counter() - started_wall
    _, refill_per_second = _RATE_LIMIT_POLICIES["optimize"]

    print(f"CPU seconds: {cpu_seconds:.3f}")
    print(f"Wall seconds: {wall_seconds:.3f}")
    print(f"Evaluations: {response.get_json()['evaluations']}")
    print(f"Steady-state one-core share: {cpu_seconds * refill_per_second:.1%}")


if __name__ == "__main__":
    main()
