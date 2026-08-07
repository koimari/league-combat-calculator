#!/usr/bin/env python3
"""Unified Atomizer CLI — atomize champions, items, abilities, runes,
economics, and stats into one Atom contract.

Usage:
    python scripts/atomize.py --list
    python scripts/atomize.py items --out data/atoms
    python scripts/atomize.py champions abilities runes economics stats --out data/atoms
    python scripts/atomize.py all --out data/atoms

Every domain emits data/atoms/<domain>.json plus a manifest in
data/atoms/manifest.json (object count, atom count, sha256, source refs).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.atomizer import write_atoms  # noqa: E402
from src.calculator.atomizer_domains import (  # noqa: E402
    atomize_abilities,
    atomize_economics,
    atomize_item_catalogue,
    atomize_rune_catalogue,
    atomize_stats,
)

DOMAINS = ("champions", "items", "abilities", "runes", "economics", "stats")


def _load_data() -> dict[str, Path]:
    return {
        "champions.json": REPO_ROOT / "data" / "champions.json",
        "items.json": REPO_ROOT / "data" / "items.json",
        "runes.json": REPO_ROOT / "data" / "runes.json",
        "economics-sourced.json": REPO_ROOT / "data" / "economics-sourced.json",
    }


def atomize_champions(champions: dict) -> dict[str, list]:
    """Delegate to the specialist champion atomizer when its assets exist."""
    import importlib.util

    extract_atoms = REPO_ROOT / "scripts" / "extract_atoms.py"
    spec = importlib.util.spec_from_file_location("extract_atoms", extract_atoms)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - asset-dependent
        return {
            "_error": [
                {
                    "atom_id": "champion_atomizer_unavailable",
                    "behavior": "error",
                    "source": str(exc),
                    "name": "champion atomizer",
                    "values": [],
                    "units": [],
                    "evidence": [str(exc)],
                    "hash": "unavailable",
                }
            ]
        }
    results = {}
    for name, champion in champions.items():
        atoms = module.extract_champion(name, None, None, None)
        results[name] = atoms if isinstance(atoms, list) else []
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "domains", nargs="*", help="one of %s or 'all'" % "|".join(DOMAINS)
    )
    parser.add_argument("--list", action="store_true", help="list domains and exit")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "atoms"))
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(DOMAINS))
        return 0

    wanted = set(args.domains)
    if "all" in wanted:
        wanted = set(DOMAINS)
    unknown = wanted - set(DOMAINS)
    if unknown:
        print(
            f"unknown domain(s): {sorted(unknown)}; use one of {DOMAINS} or 'all'",
            file=sys.stderr,
        )
        return 2
    if not wanted:
        parser.print_help()
        return 2

    data = {
        key: json.loads(path.read_text(encoding="utf-8"))
        for key, path in _load_data().items()
    }
    out_root = Path(args.out)
    manifest = {}

    if "items" in wanted:
        objects = atomize_item_catalogue(data["items.json"])
        manifest["items"] = write_atoms(
            out_root / "items.json", domain="items", objects=objects
        )
    if "abilities" in wanted:
        objects = {
            name: atomize_abilities(name, champion)
            for name, champion in sorted(data["champions.json"].items())
        }
        manifest["abilities"] = write_atoms(
            out_root / "abilities.json", domain="abilities", objects=objects
        )
    if "runes" in wanted:
        objects = atomize_rune_catalogue(data["runes.json"])
        manifest["runes"] = write_atoms(
            out_root / "runes.json", domain="runes", objects=objects
        )
    if "economics" in wanted:
        objects = atomize_economics(data["economics-sourced.json"])
        manifest["economics"] = write_atoms(
            out_root / "economics.json", domain="economics", objects=objects
        )
    if "stats" in wanted:
        objects = {
            name: atomize_stats(champion)
            for name, champion in sorted(data["champions.json"].items())
        }
        manifest["stats"] = write_atoms(
            out_root / "stats.json", domain="stats", objects=objects
        )
    if "champions" in wanted:
        objects = atomize_champions(data["champions.json"])
        manifest["champions"] = write_atoms(
            out_root / "champions.json", domain="champions", objects=objects
        )

    (out_root / "manifest.json").write_text(
        json.dumps(
            {"schema_version": 1, "domains": manifest}, indent=1, ensure_ascii=False
        )
    )
    print(f"atomized {sorted(wanted)} -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
