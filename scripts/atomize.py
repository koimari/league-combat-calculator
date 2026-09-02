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
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.atomizer import Atom, write_atoms, write_manifest
from src.calculator.atomizer_domains import (
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


def atomize_champions(champions: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Delegate to the specialist classifier and normalize its atoms."""
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
    bin_dir = REPO_ROOT / "data" / "bin" / "characters"
    bin_paths = {
        module.champion_key(path.name[: -len(".bin.json")]): path
        for path in bin_dir.glob("*.bin.json")
    }
    missing = [
        name for name in sorted(champions) if module.champion_key(name) not in bin_paths
    ]
    if missing:
        raise RuntimeError(
            "champion atomization needs CommunityDragon character bins; "
            f"missing {len(missing)} files under {bin_dir}: {', '.join(missing[:5])}"
        )

    selected_paths = [bin_paths[module.champion_key(name)] for name in champions]
    vocab = module.load_vocab()
    generic_tokens = module.compute_generic_tokens(selected_paths)
    keyword_index = module.build_keyword_index(
        vocab, generic_tokens, module.champion_name_tokens()
    )
    passive_map = module.load_passive_map()
    tag_map = module.load_tag_map()
    wiki_types = module.load_wiki_damage_types()
    atom_relations = module.load_atom_relations()

    def normalize(champion_name: str, atom: Mapping) -> dict:
        provenance = atom.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError(f"{champion_name} atom has no provenance")
        evidence: list[str] = []
        receipt = provenance.get("evidence")
        if isinstance(receipt, str) and receipt and receipt != "unknown":
            evidence.append(receipt)
        evidence.extend(
            f"wiki:{wiki_page}"
            for wiki_page in provenance.get("wiki", [])
            if str(wiki_page).strip()
        )
        evidence.extend(
            f"binary:{binary_name}"
            for binary_name in provenance.get("binary", [])
            if str(binary_name).strip()
        )
        if provenance.get("source"):
            evidence.append(f"source:{provenance['source']}")
        if provenance.get("inherited_from"):
            evidence.append(f"inherited:{provenance['inherited_from']}")
        if not evidence:
            raise ValueError(f"{champion_name} atom has no evidence receipt")

        parameters = atom.get("parameters")
        values: list[float] = []
        units: list[str] = []

        def collect(value: object, key: str) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                values.append(float(value))
                if "cooldown" in key:
                    units.append("s")
                elif key == "range":
                    units.append("units")
                elif "flags" in key:
                    units.append("bitmask")
                else:
                    units.append("flat")
                return
            if isinstance(value, list):
                for index, item in enumerate(value):
                    collect(item, f"{key}[{index}]")
            elif isinstance(value, dict):
                for child_key, child_value in value.items():
                    collect(child_value, f"{key}.{child_key}")

        collect(parameters, "parameters")
        for key, value in (parameters or {}).items():
            if isinstance(value, str):
                evidence.append(f"parameter:{key}={value}")
        behavior = str(atom.get("behavior") or atom.get("atom_id") or "unknown")
        source = str(
            (provenance.get("binary") or [None])[0]
            or provenance.get("source")
            or f"{champion_name}.wiki-map"
        )
        return Atom(
            atom_id=str(atom.get("atom_id", "")),
            behavior=behavior,
            source=source,
            name=behavior,
            values=values,
            units=units,
            evidence=evidence,
        ).to_dict()

    results = {}
    for name in sorted(champions):
        path = bin_paths[module.champion_key(name)]
        result = module.extract_champion(
            name,
            path,
            keyword_index,
            vocab,
            passive_map,
            tag_map,
            wiki_types,
            atom_relations,
        )
        results[name] = [normalize(name, atom) for atom in result["atoms"]]
    return results


def _source_ref(path: Path) -> str:
    """Return a stable source path plus its current content digest."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"{path.relative_to(REPO_ROOT)}@sha256:{digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "domains", nargs="*", help="one of {} or 'all'".format("|".join(DOMAINS))
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

    data_paths = _load_data()
    data = {
        key: json.loads(path.read_text(encoding="utf-8"))
        for key, path in data_paths.items()
    }
    out_root = Path(args.out)
    manifest = {}

    if "items" in wanted:
        objects = atomize_item_catalogue(data["items.json"])
        manifest["items"] = write_atoms(
            out_root / "items.json",
            domain="items",
            objects=objects,
            source_ref=_source_ref(data_paths["items.json"]),
        )
    if "abilities" in wanted:
        objects = {
            name: [
                atom
                for slot_atoms in atomize_abilities(name, champion).values()
                for atom in slot_atoms
            ]
            for name, champion in sorted(data["champions.json"].items())
        }
        manifest["abilities"] = write_atoms(
            out_root / "abilities.json",
            domain="abilities",
            objects=objects,
            source_ref=_source_ref(data_paths["champions.json"]),
        )
    if "runes" in wanted:
        objects = atomize_rune_catalogue(data["runes.json"])
        manifest["runes"] = write_atoms(
            out_root / "runes.json",
            domain="runes",
            objects=objects,
            source_ref=_source_ref(data_paths["runes.json"]),
        )
    if "economics" in wanted:
        objects = atomize_economics(data["economics-sourced.json"])
        manifest["economics"] = write_atoms(
            out_root / "economics.json",
            domain="economics",
            objects=objects,
            source_ref=_source_ref(data_paths["economics-sourced.json"]),
        )
    if "stats" in wanted:
        objects = {
            name: atomize_stats(champion)
            for name, champion in sorted(data["champions.json"].items())
        }
        manifest["stats"] = write_atoms(
            out_root / "stats.json",
            domain="stats",
            objects=objects,
            source_ref=_source_ref(data_paths["champions.json"]),
        )
    if "champions" in wanted:
        objects = atomize_champions(data["champions.json"])
        manifest["champions"] = write_atoms(
            out_root / "champions.json",
            domain="champions",
            objects=objects,
            source_ref=_source_ref(data_paths["champions.json"])
            + ";data/bin/characters",
        )

    write_manifest(
        out_root / "manifest.json",
        {"schema_version": 1, "domains": manifest},
    )
    print(f"atomized {sorted(wanted)} -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
