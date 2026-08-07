#!/usr/bin/env python3
"""E9 — per-champion and per-item receipts consolidating atoms + module coverage
+ audit verdict + heal rules into one verifiable receipt per entity.

Output: docs/receipts/champions/<name>.json, docs/receipts/items/<id>.json,
docs/receipts/summary.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAMPS_JSON = ROOT / "data/champions.json"
ITEMS_JSON = ROOT / "data/items.json"
ATOMS_DIR = ROOT / "data/atoms"
ITEM_ATOMS_DIR = ROOT / "data/item-atoms"
AUDIT_DIR = ROOT / "data/champion-audit"
OUT = ROOT / "docs/receipts"


def champion_receipt(name: str, champ: dict, audits: dict) -> dict:
    atoms = []
    atoms_file = ATOMS_DIR / f"{name.lower()}.atoms.json"
    if atoms_file.exists():
        atoms = json.loads(atoms_file.read_text())
    module_path = ROOT / "src/calculator/champions" / f"{name.lower()}.py"
    module_coverage = {}
    if module_path.exists():
        m = re.search(r"MODULE_COVERAGE\s*=\s*(\{.*?\})", module_path.read_text(), re.S)
        if m:
            try:
                module_coverage = json.loads(m.group(1).replace("'", '"'))
            except Exception:
                pass
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
                (
                    abs_[0].get("damageType")
                    if abs_ and isinstance(abs_[0], dict)
                    else None
                )
            )
            for slot, abs_ in (champ.get("abilities") or {}).items()
        },
    }


def item_receipt(item_id: str, item: dict) -> dict:
    """Read atoms from the unified Atomizer item domain (data/atoms/items.json)."""
    atoms = []
    atoms_file = ITEM_ATOMS_DIR / "items.json"
    if atoms_file.exists():
        dec = json.loads(atoms_file.read_text())
        objects = dec.get("objects", {}) if isinstance(dec, dict) else {}
        atoms = objects.get(str(item_id), []) if isinstance(objects, dict) else []
    return _item_receipt_body(item_id, item, atoms)


def _item_receipt_body(item_id: str, item: dict, atoms: list) -> dict:
    return {
        "name": item.get("name"),
        "id": item_id,
        "atoms": {
            "count": len(atoms),
            "ids": [atom.get("atom_id") for atom in atoms if isinstance(atom, dict)][
                :100
            ],
        },
    }
    return {
        "name": item.get("name"),
        "id": item_id,
        "atoms": {
            "count": len(atoms),
            "families": sorted({a["family"] for a in atoms}),
            "effects": [a["atom_id"] for a in atoms if a["family"] != "stats"],
        },
        "passives": [p.get("name") for p in item.get("passives") or []],
        "active": [a.get("name") for a in item.get("active") or []],
    }


def main():
    champs = json.loads(CHAMPS_JSON.read_text())
    items = json.loads(ITEMS_JSON.read_text())
    audits = {}
    # Sorted so the newest (batch-e9-*) audits win over the CP-era batches
    # (dict.update keeps the last writer per key).
    for f in sorted(AUDIT_DIR.glob("batch-*.json")):
        audits.update(json.loads(f.read_text()))

    (OUT / "champions").mkdir(parents=True, exist_ok=True)
    (OUT / "items").mkdir(parents=True, exist_ok=True)
    summary = {"champions": {}, "items": {}}
    for name, champ in champs.items():
        rec = champion_receipt(name, champ, audits)
        (OUT / "champions" / f"{name.lower()}.json").write_text(
            json.dumps(rec, indent=1)
        )
        summary["champions"][name] = {
            "atoms": rec["atoms"]["count"],
            "verdict": rec["audit_verdict"],
        }
    for item_id, item in items.items():
        rec = item_receipt(item_id, item)
        (OUT / "items" / f"{item_id}.json").write_text(json.dumps(rec, indent=1))
        summary["items"][item.get("name")] = {
            "id": item_id,
            "atoms": rec["atoms"]["count"],
            "effects": len(rec["atoms"]["effects"]),
        }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"champions: {len(summary['champions'])} | items: {len(summary['items'])}")
    from collections import Counter

    verdicts = Counter(v["verdict"] for v in summary["champions"].values())
    print("audit verdicts:", dict(verdicts))


if __name__ == "__main__":
    main()
