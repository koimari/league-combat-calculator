#!/usr/bin/env python3
"""Extract fundamental behavior atoms from decomposed champion binaries (WS3).

Each champion's SpellObject entries are classified into behavior atoms
(heal/shield/crowd_control/damage/buff/resource) with binary provenance
(cooldowns, ranges, alternate-name hooks). This is the seed of the atomic
catalog: every champion mechanic as a composition of atoms.

Usage:
    ~/.local/mcp/wad-env/bin/python scripts/extract_atoms.py
    # or any python3 with json (reads data/bin/characters/*.bin.json)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BIN_DIR = Path("data/bin/characters")
ATOMS_DIR = Path("data/atoms")
AGGREGATE = ATOMS_DIR / "atom-summary.json"


def extract_atoms(ser: dict, champion: str) -> list[dict]:
    atoms = []
    seen = set()
    for key, val in ser.items():
        if not (isinstance(val, dict) and val.get("__type") == "SpellObject"):
            continue
        name = val.get("mScriptName", key)
        m = val.get("mSpell", {})
        cd = m.get("cooldownTime") or []
        rng = m.get("castRange") or []
        low = name.lower()
        alt = (m.get("mAlternateName") or "").lower()
        if "heal" in low or "heal" in alt or "transfusion" in low:
            fam = "heal"
        elif "shield" in low or "shield" in alt:
            fam = "shield"
        elif "slow" in low or "slow" in alt or "stun" in low or "root" in low or "knock" in low:
            fam = "crowd_control"
        elif "cost" in low:
            fam = "resource"
        elif "buff" in low or "frenzy" in low or "build" in low or "gorged" in low or "passive" in low:
            fam = "buff"
        elif "nuke" in low or "damage" in low or "missile" in low or "debuff" in low:
            fam = "damage"
        else:
            continue
        aid = f"{fam}.{champion.lower()}.{name}"
        if aid in seen:
            continue
        seen.add(aid)
        atoms.append({
            "atom_id": aid,
            "family": fam,
            "behavior": name,
            "trigger": "on_cast" if fam == "damage" else "on_effect",
            "target_policy": "self" if fam in ("heal", "buff") else "enemy",
            "parameters": {
                "cooldown_rank1": cd[0] if cd else None,
                "cooldown_rank_max": cd[-1] if cd else None,
                "range": rng[0] if rng else None,
            },
            "provenance": {"wiki": [champion], "binary": [key]},
        })
    return atoms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ATOMS_DIR))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    total = 0
    for f in sorted(BIN_DIR.glob("*.bin.json")):
        champ = f.stem.replace(".bin.json", "")
        ser = json.loads(f.read_text())
        atoms = extract_atoms(ser, champ)
        (out / f"{champ}.atoms.json").write_text(json.dumps(atoms, indent=1))
        total += len(atoms)
        for a in atoms:
            summary.setdefault(a["family"], set()).add(champ)
    agg = {fam: sorted(champs) for fam, champs in sorted(summary.items())}
    (out / "atom-summary.json").write_text(json.dumps(agg, indent=1))
    print(f"atoms extracted: {total} across {len(summary)} families")
    for fam, champs in agg.items():
        print(f"  {fam}: {len(champs)} champions")


if __name__ == "__main__":
    main()
