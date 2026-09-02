#!/usr/bin/env python3
"""Build the UI-safe, patch-pinned ability catalogue from the Wiki cache.

The catalogue is deliberately descriptive. It proves that a champion's five
ability slots were ingested, but it does not turn an unreviewed description
into a damage formula. Exact combat output remains owned by the reviewed
champion registry.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.source_receipt import cache_patch, source_receipt
from src.calculator.cast_dependency import BASE_CAST_SLOTS
from src.calculator.champions import registered_champion_names


def _first_nonempty(values: Iterable[Any]) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def rank_count(ability: Mapping[str, Any], slot: str) -> int:
    """The catalogue's rank cardinality for one ability, clamped to the UI's five.

    Distinct from ``scenario._ability_max_rank``, which reads the same cache to
    bound a *manual* rank and so deliberately admits the level tables some
    modifiers carry (18 and 40 entries).  A rank picker has five steps.
    """
    if slot == "P":
        return 1
    counts: list[int] = []
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                if isinstance(values, list) and values:
                    counts.append(len([v for v in values if _is_number(v)]))
    counts = [count for count in counts if count]
    return 3 if slot == "R" else 5 if not counts else max(1, min(max(counts), 5))


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


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
        "max_rank": rank_count(primary, slot),
        "ingestion_status": "metadata_ingested",
    }


def catalogue_champions(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The cached champion rows a catalogue publishes, by display name.

    Every cached champion is here: an unregistered one is still a legal ally or
    target.  A registered module with no cache row fails the build.
    """
    by_name = {str(champion.get("name", "")): champion for champion in raw.values()}
    absent = sorted(name for name in registered_champion_names() if name not in by_name)
    if absent:
        raise ValueError("registered modules with no cached row: " + ", ".join(absent))
    return [by_name[name] for name in sorted(by_name)]


def build_catalog(source: Path, patch: str) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected champion mapping in {source}")

    champions = []
    for champion in catalogue_champions(raw):
        abilities = champion.get("abilities", {})
        entries = [
            _ability_entry(slot, abilities.get(slot, [])) for slot in BASE_CAST_SLOTS
        ]
        champions.append(
            {
                "name": champion.get("name", ""),
                "key": champion.get("key", ""),
                "id": champion.get("id"),
                "abilities": entries,
                "complete": all(
                    entry["ingestion_status"] == "metadata_ingested"
                    for entry in entries
                ),
            }
        )

    return {
        "schema_version": 1,
        "patch": patch,
        "champion_count": len(champions),
        "ability_slots": list(BASE_CAST_SLOTS),
        "source": source_receipt(source),
        "champions": champions,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument(
        "--output", type=Path, default=root / "static" / "ability-catalog.json"
    )
    # Default derived from the cache, so a rebuild cannot stamp a stale patch.
    parser.add_argument("--patch", default=None)
    args = parser.parse_args()

    catalog = build_catalog(args.source.resolve(), args.patch or cache_patch())
    if not catalog["champions"]:
        raise SystemExit(
            "No champions in the cached source — refusing to write an empty "
            "ability catalog"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.output} ({catalog['champion_count']} champions, "
        f"{len(catalog['champions']) * len(BASE_CAST_SLOTS)} ability slots)"
    )


if __name__ == "__main__":
    main()
