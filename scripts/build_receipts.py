#!/usr/bin/env python3
"""Per-champion and per-item receipts: atoms, module coverage, audit verdict
and heal rules folded into one verifiable receipt per entity.

Output: docs/receipts/champions/<name>.json and docs/receipts/items/<id>.json,
both gitignored and rebuilt from the local corpus.  The run's counts are
printed and returned; nothing tracked is written, so a partial local atom
corpus cannot commit itself.

Item atoms come from ``data/atoms/items.json``, the only authoritative
item-atom source.  The receipt tree is built in a temporary directory and
published only after every entity succeeds, so a failure can never leave a
partially refreshed tree.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CHAMPS_JSON = ROOT / "data/champions.json"
ITEMS_JSON = ROOT / "data/items.json"
ATOMS_DIR = ROOT / "data/atoms"
ITEM_ATOMS_FILE = ATOMS_DIR / "items.json"
MANIFEST_FILE = ATOMS_DIR / "manifest.json"
AUDIT_DIR = ROOT / "data/champion-audit"
OUT = ROOT / "docs/receipts"


class ItemAtomError(RuntimeError):
    """The unified item-atom source is missing or violates its contract."""


def load_item_atoms(path: Path | None = None) -> dict[str, list[dict]]:
    """Load and validate the unified Atomizer item domain (fail closed).

    Contract (``scripts/atomize.py items`` -> ``atomizer.write_atoms``):
    top-level ``domain == "items"`` with an ``objects`` mapping of item id ->
    list of atom rows, each row a dict carrying a string ``atom_id``.  Any
    violation raises :class:`ItemAtomError` before a receipt is written.
    """
    atoms_file = Path(path) if path is not None else ITEM_ATOMS_FILE
    if not atoms_file.is_file():
        raise ItemAtomError(
            f"item atom file not found: {atoms_file}\n"
            "Run the unified Atomizer first: python scripts/atomize.py items"
        )
    try:
        payload = json.loads(atoms_file.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ItemAtomError(f"item atom file is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ItemAtomError(
            f"item atom payload must be an object, got {type(payload).__name__}"
        )
    if payload.get("domain") != "items":
        raise ItemAtomError(
            f"item atom payload domain is {payload.get('domain')!r}, expected 'items'"
        )
    objects = payload.get("objects")
    if not isinstance(objects, dict):
        raise ItemAtomError(
            f"item atoms 'objects' must be a mapping, got {type(objects).__name__}"
        )
    for item_id, rows in objects.items():
        if not isinstance(item_id, str):
            raise ItemAtomError(
                f"item atom object key must be a string id, got {item_id!r}"
            )
        if not isinstance(rows, list):
            raise ItemAtomError(
                f"item {item_id}: atoms must be a list, got {type(rows).__name__}"
            )
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("atom_id"), str):
                raise ItemAtomError(
                    f"item {item_id}: atom row {index} must be a dict with a string atom_id"
                )
    return objects


def _family_of(atom: Mapping) -> str:
    """Family of an item atom: the ``atom_id`` prefix, no ``family`` field."""
    return atom["atom_id"].split(".", 1)[0]


def champion_receipt(name: str, champ: Mapping, audits: Mapping) -> dict:
    atoms = []
    atoms_file = ATOMS_DIR / f"{name.lower()}.atoms.json"
    if atoms_file.exists():
        atoms = json.loads(atoms_file.read_text())
    from src.calculator.champions import get_champion_module_contract

    module_coverage = get_champion_module_contract(name).coverage
    audit = audits.get(name, {})
    return {
        "champion": name,
        "atoms": {
            "count": len(atoms),
            "families": sorted({a["family"] for a in atoms}),
        },
        "module_coverage": module_coverage,
        "audit_verdict": audit.get("verdict"),
        "audit_gap": audit.get("gap_summary", "")[:200],
        "ability_damage_types": {
            slot: (
                abs_[0].get("damageType")
                if abs_ and isinstance(abs_[0], dict)
                else None
            )
            for slot, abs_ in (champ.get("abilities") or {}).items()
        },
    }


def item_receipt(item_id: str, item: Mapping, atoms: list[dict] | None = None) -> dict:
    """One item receipt from the Atomizer item domain.

    ``atoms`` may be injected for tests; the default loads and validates the
    authoritative ``data/atoms/items.json``.  An id absent from the mapping
    yields a truthful zero-atom receipt.
    """
    if atoms is None:
        atoms = load_item_atoms().get(str(item_id), [])
    return {
        "name": item.get("name"),
        "id": item_id,
        "atoms": {
            "count": len(atoms),
            "ids": [atom["atom_id"] for atom in atoms],
            "families": sorted({_family_of(atom) for atom in atoms}),
            "effects": sorted(
                atom["atom_id"] for atom in atoms if _family_of(atom) != "stat"
            ),
        },
    }


def _manifest_items() -> dict | None:
    """Authoritative item atom inventory from the unified Atomizer manifest."""
    try:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    domains = manifest.get("domains") if isinstance(manifest, dict) else None
    items = domains.get("items") if isinstance(domains, dict) else None
    if isinstance(items, dict) and isinstance(items.get("object_count"), int):
        return items
    return None


def build() -> dict:
    """Compute every receipt and the summary; publish atomically."""
    champs = json.loads(CHAMPS_JSON.read_text())
    items = json.loads(ITEMS_JSON.read_text())
    audits = {}
    # Sorted so the newest (batch-e9-*) audits win over the CP-era batches
    # (dict.update keeps the last writer per key).
    for f in sorted(AUDIT_DIR.glob("batch-*.json")):
        audits.update(json.loads(f.read_text()))

    item_atoms = load_item_atoms()
    # Champion atoms live in gitignored data/atoms/*.atoms.json (E-series
    # corpus); a fresh checkout carries only the tracked subset.  Report the
    # incompleteness loudly instead of silently emitting zero-atom receipts.
    champion_atom_files = {
        p.stem.removesuffix(".atoms") for p in ATOMS_DIR.glob("*.atoms.json")
    }
    if len(champion_atom_files) < len(champs):
        missing = len(champs) - len(champion_atom_files)
        print(
            f"WARNING: {missing}/{len(champs)} champions have no local atom file; "
            "their receipts report atoms: 0. Regenerate the corpus with "
            "python scripts/atomize.py champions, or re-capture from the "
            "full-atom working tree.",
            file=sys.stderr,
        )
    summary = {"champions": {}, "items": {}}

    # Compute and validate every entity BEFORE any output is published.
    champion_records: dict[str, dict] = {}
    for cache_key, champ in champs.items():
        display_name = str(champ.get("name") or cache_key)
        champion_records[cache_key] = champion_receipt(display_name, champ, audits)
    item_records: dict[str, dict] = {}
    for item_id, item in items.items():
        item_records[item_id] = item_receipt(
            item_id, item, item_atoms.get(str(item_id), [])
        )

    for name, rec in champion_records.items():
        summary["champions"][name] = {
            "atoms": rec["atoms"]["count"],
            "verdict": rec["audit_verdict"],
        }
    total_item_atoms = 0
    for item_id, rec in item_records.items():
        total_item_atoms += rec["atoms"]["count"]
        summary["items"][rec["name"]] = {
            "id": item_id,
            "atoms": rec["atoms"]["count"],
            "effects": len(rec["atoms"]["effects"]),
        }

    # Cross-check the summary against the authoritative Atomizer inventory.
    manifest = _manifest_items()
    if manifest is not None:
        expected_objects = manifest["object_count"]
        expected_atoms = manifest.get("atom_count")
        if len(item_records) != expected_objects:
            raise ItemAtomError(
                f"item receipt count {len(item_records)} != Atomizer manifest "
                f"object_count {expected_objects}"
            )
        if expected_atoms is not None and total_item_atoms != expected_atoms:
            raise ItemAtomError(
                f"item atom total {total_item_atoms} != Atomizer manifest "
                f"atom_count {expected_atoms}"
            )

    # Publish only after every entity succeeded: build the tree in a temp dir
    # on the same filesystem, then swap it into place.
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".receipts-tmp-", dir=OUT) as tmp_raw:
        tmp = Path(tmp_raw)
        (tmp / "champions").mkdir()
        (tmp / "items").mkdir()
        for name, rec in champion_records.items():
            (tmp / "champions" / f"{name.lower()}.json").write_text(
                json.dumps(rec, indent=1)
            )
        for item_id, rec in item_records.items():
            (tmp / "items" / f"{item_id}.json").write_text(json.dumps(rec, indent=1))

        for child in ("champions", "items"):
            dest = OUT / child
            if dest.exists():
                shutil.rmtree(dest)
            (tmp / child).replace(dest)

    print(f"champions: {len(summary['champions'])} | items: {len(summary['items'])}")
    verdicts = Counter(v["verdict"] for v in summary["champions"].values())
    print("audit verdicts:", dict(verdicts))
    if manifest is not None:
        print(
            f"item atoms: {total_item_atoms} (manifest {manifest.get('atom_count')}) | "
            f"objects: {len(item_records)} (manifest {manifest['object_count']})"
        )
    return summary


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
