#!/usr/bin/env python3
"""Build static/data.json, the patch snapshot app.js loads before any API call.

It holds exactly the champion fields the page reads from ``DATA``: identity for
the picker and the reviewed ability slots. Identity is derived from the cached
champion table; the per-ability ``name``/``icon``/``maxHits``/``variants`` cells
are the one hand-maintained section, because they name the reviewed client
formula graph's forms and Data Dragon's spell icons, neither of which ``data/``
carries -- this builder carries that section forward from the committed
snapshot and prunes it to the keys app.js reads.

Everything numeric the page shows comes from the API (``/api/loadout-stats``,
``/api/items``, ``/api/boots``), so no stat, price or damage ratio belongs here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculator.cast_dependency import BASE_CAST_SLOTS

MAX_RANK = {"P": 1, "R": 3}
DEFAULT_MAX_RANK = 5


def _pretty(token: str) -> str:
    """Cache enums as the picker prints them: ``BLOOD_WELL`` -> ``Blood Well``."""
    return token.replace("_", " ").title()


def _required(record: Mapping[str, Any], key: str, owner: str = "") -> Any:
    """One field the snapshot cannot be written without, failing closed on the key."""
    value = record.get(key)
    if not value:
        name = owner or record.get("name") or record.get("key") or "unknown champion"
        raise ValueError(f"{name}: record has no {key}")
    return value


def reviewed_abilities(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    """The hand-maintained ability block, by champion name, pruned to what app.js reads.

    ``maxRank`` is dropped here and re-derived, so the slot's rank count has one
    home. ``maxHits`` survives only where the reviewed form actually caps hits.
    """
    committed = json.loads(snapshot.read_text(encoding="utf-8"))
    block: dict[str, list[dict[str, Any]]] = {}
    for champion in committed.get("champions", []):
        name = champion.get("name", "")
        abilities = []
        for ability in champion.get("abilities", []):
            slot = ability.get("slot")
            if slot not in BASE_CAST_SLOTS:
                raise ValueError(f"{name}: reviewed ability has no known slot ({slot})")
            variants = [
                {"name": variant["name"]} for variant in ability.get("variants", [])
            ]
            if not variants:
                raise ValueError(f"{name} {slot}: reviewed ability has no variant")
            entry = {
                "slot": slot,
                "name": _required(ability, "name", f"{name} {slot}"),
                "icon": _required(ability, "icon", f"{name} {slot}"),
                "maxRank": MAX_RANK.get(slot, DEFAULT_MAX_RANK),
            }
            if ability.get("maxHits"):
                entry["maxHits"] = ability["maxHits"]
            entry["variants"] = variants
            abilities.append(entry)
        block[name] = abilities
    return block


def build_snapshot(source: Path, snapshot: Path) -> dict[str, Any]:
    cache = json.loads(source.read_text(encoding="utf-8"))
    by_name = {str(record.get("name", "")): record for record in cache.values()}
    abilities = reviewed_abilities(snapshot)

    absent = sorted(set(abilities) - set(by_name))
    if absent:
        raise ValueError(
            "reviewed abilities for champions with no cached row: " + ", ".join(absent)
        )

    return {
        "champions": [
            {
                "name": name,
                "key": _required(by_name[name], "key"),
                "title": _required(by_name[name], "title"),
                "tags": [_pretty(role) for role in _required(by_name[name], "roles")],
                "resource": _pretty(_required(by_name[name], "resource")),
                "abilities": abilities.get(name, []),
            }
            for name in sorted(by_name)
        ]
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument("--output", type=Path, default=root / "static" / "data.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when the committed snapshot has drifted",
    )
    args = parser.parse_args()

    snapshot = build_snapshot(args.source.resolve(), args.output.resolve())
    if args.check:
        committed = json.loads(args.output.read_text(encoding="utf-8"))
        if committed != snapshot:
            raise SystemExit(
                f"{args.output} has drifted from the cache — rebuild with: "
                "python scripts/build_static_data.py"
            )
        print(f"{args.output} is current ({len(snapshot['champions'])} champions)")
        return

    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    reviewed = sum(len(champion["abilities"]) for champion in snapshot["champions"])
    print(
        f"wrote {args.output} ({len(snapshot['champions'])} champions, "
        f"{reviewed} reviewed abilities)"
    )


if __name__ == "__main__":
    main()
