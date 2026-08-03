#!/usr/bin/env python3
"""Build the UI-safe, patch-pinned ability catalogue from the Wiki cache.

The catalogue is deliberately descriptive. It proves that a champion's five
ability slots were ingested, but it does not turn an unreviewed description
into a damage formula. Exact combat output remains owned by the reviewed
champion registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ABILITY_SLOTS = ("P", "Q", "W", "E", "R")


def _first_nonempty(values: list[Any]) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _rank_count(ability: dict[str, Any], slot: str) -> int:
    if slot == "P":
        return 1
    counts: list[int] = []
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                if isinstance(values, list) and values:
                    counts.append(len(values))
    return 3 if slot == "R" else 5 if not counts else max(1, min(max(counts), 5))


def _ability_entry(slot: str, raw_entries: Any) -> dict[str, Any]:
    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    if not entries:
        return {
            "slot": slot,
            "name": slot,
            "icon": "",
            "forms": [],
            "description": "",
            "blurb": "",
            "damage_type": None,
            "targeting": None,
            "affects": None,
            "resource": None,
            "max_rank": 1 if slot == "P" else 3 if slot == "R" else 5,
            "ingestion_status": "missing",
        }

    descriptions: list[str] = []
    forms: list[dict[str, Any]] = []
    for entry in entries:
        for effect in entry.get("effects", []):
            description = str(effect.get("description", "")).strip()
            if description and description not in descriptions:
                descriptions.append(description)
        forms.append(
            {
                "name": entry.get("name") or slot,
                "icon": entry.get("icon") or "",
                "blurb": entry.get("blurb") or "",
                "damage_type": entry.get("damageType"),
            }
        )

    primary = entries[0]
    return {
        "slot": slot,
        "name": primary.get("name") or slot,
        "icon": primary.get("icon") or "",
        "forms": forms,
        "description": " ".join(descriptions),
        "blurb": _first_nonempty([entry.get("blurb") for entry in entries]) or "",
        "damage_type": _first_nonempty([entry.get("damageType") for entry in entries]),
        "targeting": _first_nonempty([entry.get("targeting") for entry in entries]),
        "affects": _first_nonempty([entry.get("affects") for entry in entries]),
        "resource": _first_nonempty([entry.get("resource") for entry in entries]),
        "max_rank": _rank_count(primary, slot),
        "ingestion_status": "metadata_ingested",
    }


def build_catalog(source: Path, patch: str) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected champion mapping in {source}")

    champions = []
    for champion in sorted(raw.values(), key=lambda item: str(item.get("name", ""))):
        abilities = champion.get("abilities", {})
        champions.append(
            {
                "name": champion.get("name", ""),
                "key": champion.get("key", ""),
                "id": champion.get("id"),
                "abilities": [
                    _ability_entry(slot, abilities.get(slot, []))
                    for slot in ABILITY_SLOTS
                ],
                "complete": all(
                    _ability_entry(slot, abilities.get(slot, [])).get(
                        "ingestion_status"
                    )
                    == "metadata_ingested"
                    for slot in ABILITY_SLOTS
                ),
            }
        )

    return {
        "schema_version": 1,
        "patch": patch,
        "champion_count": len(champions),
        "ability_slots": list(ABILITY_SLOTS),
        "source": {
            "kind": "local Wiki cache",
            # as_posix() so a Windows rebuild matches a macOS/Linux one.
            "path": source.relative_to(source.parents[1]).as_posix(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "champions": champions,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument(
        "--output", type=Path, default=root / "static" / "ability-catalog.json"
    )
    parser.add_argument("--patch", default="26.15")
    args = parser.parse_args()

    catalog = build_catalog(args.source.resolve(), args.patch)
    if catalog["champion_count"] != 173:
        raise SystemExit(
            f"Expected 173 champions in the cached source, got {catalog['champion_count']}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.output} ({catalog['champion_count']} champions, "
        f"{len(catalog['champions']) * len(ABILITY_SLOTS)} ability slots)"
    )


if __name__ == "__main__":
    main()
