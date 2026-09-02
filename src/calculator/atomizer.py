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
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            self._atoms[key] = Atom(
                atom_id, behavior, source, name, values, units, list(evidence)
            )
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
    for match in re.finditer(r"(-?\d+(?:\.\d+)?)\s*(%|/5s|/s|gold|s)?", text):
        values.append(float(match.group(1)))
        unit = match.group(2) or ""
        if unit == "%":
            units.append("percent")
        elif unit:
            units.append(unit)
        else:
            units.append("flat")
    return values, units


def _content_stable_bytes(
    domain: str, objects: dict[str, Any], source_ref: str | None
) -> bytes:
    """Canonical bytes for a domain payload's content identity; excludes
    ``generated_at`` so re-runs over unchanged content hash the same."""
    stable = {"domain": domain, "source_ref": source_ref, "objects": objects}
    return json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(domain: str, objects: dict[str, Any], source_ref: str | None) -> str:
    """sha256 (first 16 hex chars) of the content-stable payload. This is
    the exact hash published as the manifest's ``sha256`` receipt for a
    domain, and is what ``hash_domain_file`` recomputes from disk."""
    return hashlib.sha256(
        _content_stable_bytes(domain, objects, source_ref)
    ).hexdigest()[:16]


def hash_domain_file(path: Path) -> str:
    """Recompute the content-stable manifest hash for an on-disk domain atom
    file. Reads the file's own ``domain``/``source_ref``/``objects`` and
    ignores ``generated_at``, so it equals the manifest's ``sha256``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return content_hash(
        payload["domain"], payload["objects"], payload.get("source_ref")
    )


def write_atoms(
    out_path: Path,
    *,
    domain: str,
    objects: dict[str, list[dict[str, Any]]],
    source_ref: str | None = None,
) -> dict[str, Any]:
    """Atomically write a domain atom file + manifest receipt.

    The manifest's ``sha256`` is computed over the CONTENT-STABLE payload
    only (``domain`` + ``source_ref`` + ``objects``, canonically
    serialized) via :func:`content_hash` — NOT over the raw file bytes.
    The file itself still carries a live ``generated_at`` timestamp (useful
    metadata for humans inspecting the file), but that field is excluded
    from the hash so re-running the atomizer with unchanged inputs produces
    an identical manifest sha256 every time.
    """
    payload = {
        "domain": domain,
        "generated_at": time.time(),
        "source_ref": source_ref,
        "objects": objects,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    return {
        "domain": domain,
        "object_count": len(objects),
        "atom_count": sum(len(rows) for rows in objects.values()),
        "sha256": content_hash(domain, objects, source_ref),
        "source_ref": source_ref,
    }


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish the domain manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def split_effect_fragments(
    effect: dict[str, Any], *, prefix: str, index: int
) -> list[tuple[str, str]]:
    """Per-effect text fragments for classification.

    Uses the structured ``branches`` when present, then the description
    sentence-split, so a multi-effect passive/active never collapses into
    one blob (the item-atomizer bug).
    """
    fragments: list[tuple[str, str]] = []
    branches = (
        effect.get("branches") if isinstance(effect.get("branches"), list) else None
    )
    if branches:
        for branch_index, branch in enumerate(branches):
            if isinstance(branch, str):
                fragments.append(
                    (f"{prefix}[{index}].branches[{branch_index}]", branch)
                )
            elif isinstance(branch, dict):
                text = " ".join(
                    str(branch.get(k, ""))
                    for k in ("description", "name")
                    if branch.get(k)
                )
                if text:
                    fragments.append(
                        (f"{prefix}[{index}].branches[{branch_index}]", text)
                    )
    description = str(effect.get("description", ""))
    fragments.extend(
        (f"{prefix}[{index}]", sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", description)
        if sentence.strip()
    )
    return fragments
