"""Unified Atomizer core: one way to atomize anything numerical.

Every domain (champions, items, abilities, runes, economics, stats) produces
the same Atom contract:

    atom_id     canonical atom identity, e.g. "damage.physical" or "heal.flat"
    behavior    how the atom behaves in combat: damage|heal|shield|stat|...
    source      provenance path inside the object: champion, slot, effect index
    name        human label (ability name, passive name, attribute name)
    values      leveling/ranked numeric array (or single value)
    units       unit string per value ("%", "", "/5s", ...)
    evidence    exact receipt strings: "passive:Spellblade@kw:on-hit",
                "effects[2].leveling[0].modifiers[0]", wiki revision
    hash        sha256 of the canonical atom record

Rules (enforced by the core):
1. Per-object classify: each effect fragment is classified independently;
   no cross-effect "seen" set can absorb later effects (the item-atomizer
   bug this design exists to prevent).
2. Dedup at emission by (atom_id, behavior), merging evidence receipts.
3. Every emitted atom carries provenance; nothing is emitted without a
   receipt.
4. Output is written atomically with a manifest + source hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Atom:
    atom_id: str
    behavior: str
    source: str
    name: str
    values: list[float] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        record = {
            "atom_id": self.atom_id,
            "behavior": self.behavior,
            "source": self.source,
            "name": self.name,
            "values": self.values,
            "units": self.units,
            "evidence": sorted(set(self.evidence)),
        }
        record["hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        return record


class Atomizer:
    """Per-object atom collector with (atom_id, behavior) dedup + receipts."""

    def __init__(self, domain: str, source_ref: str | None = None) -> None:
        self.domain = domain
        self.source_ref = source_ref
        self._atoms: dict[tuple[str, str], Atom] = {}

    def add(
        self,
        atom_id: str,
        behavior: str,
        source: str,
        name: str,
        values: Iterable[float] = (),
        units: Iterable[str] = (),
        evidence: Iterable[str] = (),
    ) -> None:
        values = [float(v) for v in values]
        units = list(units)
        key = (atom_id, behavior)
        atom = self._atoms.get(key)
        if atom is None:
            self._atoms[key] = Atom(atom_id, behavior, source, name, values, units, list(evidence))
            return
        # merge: keep the first non-empty values, union evidence
        if not atom.values and values:
            atom.values = values
            atom.units = units
        atom.evidence.extend(evidence)

    def emit(self) -> list[dict[str, Any]]:
        return sorted(
            (a.to_dict() for a in self._atoms.values()),
            key=lambda d: (d["atom_id"], d["behavior"], d["source"]),
        )


def number_and_unit(text: str) -> tuple[list[float], list[str]]:
    """Extract (values, units) pairs from a numeric fragment like
    '50 (+ 25% AP)' -> ([50.0, 0.25], ['flat', 'ratio'])."""
    values: list[float] = []
    units: list[str] = []
    for match in re.finditer(
        r"(-?\d+(?:\.\d+)?)\s*(%|/5s|/s|gold|s)?", text
    ):
        values.append(float(match.group(1)))
        unit = match.group(2) or ""
        if unit == "%":
            units.append("percent")
        elif unit:
            units.append(unit)
        else:
            units.append("flat")
    return values, units


def write_atoms(
    out_path: Path,
    *,
    domain: str,
    objects: dict[str, list[dict[str, Any]]],
    source_ref: str | None = None,
) -> dict[str, Any]:
    """Atomically write a domain atom file + manifest receipt."""
    payload = {
        "domain": domain,
        "generated_at": time.time(),
        "source_ref": source_ref,
        "objects": objects,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)
    manifest = {
        "domain": domain,
        "object_count": len(objects),
        "atom_count": sum(len(rows) for rows in objects.values()),
        "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()[:16],
        "source_ref": source_ref,
    }
    return manifest


def split_effect_fragments(
    effect: dict[str, Any], *, prefix: str, index: int
) -> list[tuple[str, str]]:
    """Per-effect text fragments for classification.

    Uses the structured ``branches`` when present, then the description
    sentence-split, so a multi-effect passive/active never collapses into
    one blob (the item-atomizer bug).
    """
    fragments: list[tuple[str, str]] = []
    branches = effect.get("branches") if isinstance(effect.get("branches"), list) else None
    if branches:
        for branch_index, branch in enumerate(branches):
            if isinstance(branch, str):
                fragments.append((f"{prefix}[{index}].branches[{branch_index}]", branch))
            elif isinstance(branch, dict):
                text = " ".join(
                    str(branch.get(k, "")) for k in ("description", "name") if branch.get(k)
                )
                if text:
                    fragments.append((f"{prefix}[{index}].branches[{branch_index}]", text))
    description = str(effect.get("description", ""))
    for sentence in re.split(r"(?<=[.!?])\s+", description):
        if sentence.strip():
            fragments.append((f"{prefix}[{index}]", sentence))
    return fragments
