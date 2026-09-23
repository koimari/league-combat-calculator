"""Capture what the engine's INTERNAL row shapes carry, for every champion.

``tests/test_row_stream_census.py`` measures the rows the engine PUBLISHES,
because ``golden_coupled_baseline.json`` is a committed corpus of them. The
modules that build that payload read the internal shape instead, so nothing
in that census licenses a single read in ``public_response`` and its
siblings: they run at publication, not after it.

This is the missing corpus. It walks one timed fight per registered
champion and records, per internal stream, how many rows it saw, how many
carried each key, and which keys were on every one of them. ``check``
re-derives and compares, so the receipt cannot drift from the engine the
way a hand-written note would, and a producer that stops stamping a key on
some of its rows moves a count here even where it moves no universal set.

A key here is safe to index only under the same clauses the published
census carries, and the corpus answers the first of them for the internal
shapes. It is deliberately ONE scenario shape per champion: broad across
kits, not across fight configurations, so a key it calls universal is
universal over the kits and not over every request a user can build. That
is stated rather than implied, because a corpus whose reach is misread is
how the published census produced a wrong figure the first time.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import (
    registered_champion_names,
)
from src.calculator.pipeline import run_fight
from src.calculator.scenario import (
    parse_scenario_request,
    resolve_scenario,
)

RECEIPT = REPO_ROOT / "docs" / "receipts" / "internal-row-census.json"

#: The internal row streams a fight result publishes under its own keys.
#: ``breakdown`` is a table keyed by damage source rather than a list, and
#: ``breakdown_damage_events`` is the packets its rows author, a third
#: population that is neither the table nor the top-level stream.
STREAMS = (
    "damage_events",
    "self_healing_events",
    "control_events",
    "breakdown",
    "breakdown_damage_events",
)

#: The one probe shape, stated so a reader knows what the corpus covers.
PROBE = {
    "level": 13,
    "role": "mid",
    "fight_duration_seconds": 10.0,
    "enemy": "Aatrox",
}


def _fight(champion: str) -> dict[str, Any]:
    """One timed fight for *champion*, at the probe's stated shape."""
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": PROBE["level"],
            "role": PROBE["role"],
            "items": [],
            "enemies": [
                {"champion": PROBE["enemy"], "level": PROBE["level"], "role": "top"}
            ],
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    params = replace(
        resolved.fight_params,
        fight_duration_seconds=PROBE["fight_duration_seconds"],
        one_rotation=False,
        auto_attack_uptime=1.0,
    )
    return run_fight(
        resolved.champion_data, request.level, list(resolved.items), params
    )


def _stream_rows(result: dict[str, Any], stream: str) -> list[dict]:
    """One stream's dict rows: a list the fight publishes, a table keyed by
    source, or the packets those table rows author."""
    if stream == "breakdown_damage_events":
        return [
            packet
            for row in _stream_rows(result, "breakdown")
            for packet in (row.get("damage_events") or ())
            if isinstance(packet, dict)
        ]
    published = result.get(stream) or ()
    values = published.values() if isinstance(published, dict) else published
    return [row for row in values if isinstance(row, dict)]


def measure() -> dict[str, Any]:
    """Walk every registered champion and census each internal stream."""
    rows: dict[str, list[dict]] = {stream: [] for stream in STREAMS}
    champions = registered_champion_names()
    for champion in champions:
        result = _fight(champion)
        for stream in STREAMS:
            rows[stream].extend(_stream_rows(result, stream))
    census: dict[str, Any] = {
        "champions": len(champions),
        "probe": dict(PROBE),
        "streams": {},
    }
    for stream, seen in rows.items():
        counts = Counter(key for row in seen for key in row)
        census["streams"][stream] = {
            "keys": dict(sorted(counts.items())),
            "rows": len(seen),
            "universal": (
                sorted(key for key, count in counts.items() if count == len(seen))
                if seen
                else []
            ),
        }
    return census


def main() -> int:
    """``capture`` writes the receipt; ``check`` re-derives and compares."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "check"))
    action = parser.parse_args().action
    measured = measure()
    if action == "capture":
        RECEIPT.write_text(
            json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Captured internal row census -> {RECEIPT}")
        for stream, block in sorted(measured["streams"].items()):
            print(
                f"  {stream}: {block['rows']} rows, {len(block['universal'])} universal"
            )
        return 0
    if not RECEIPT.exists():
        print(f"FAIL: {RECEIPT} is not committed; run capture", file=sys.stderr)
        return 1
    committed = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if committed != measured:
        print("FAIL: the internal row census has drifted from the engine")
        for stream in sorted(set(committed["streams"]) | set(measured["streams"])):
            was = committed["streams"].get(stream)
            now = measured["streams"].get(stream)
            if was != now:
                print(f"  {stream}: {was} -> {now}")
        return 1
    print("OK: the internal row census matches the engine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
