#!/usr/bin/env python3
"""Provenance receipts for the static artifacts derived from tracked data.

Lives in one place because getting this wrong is silent and platform-shaped.
Git normalises line endings on checkout, so with `core.autocrlf=true` (the
Windows default) `data/champions.json` is CRLF in the working copy and LF on
macOS/Linux -- the same tracked file, two different digests. A receipt that
hashes raw working-tree bytes therefore only ever matches on the machine that
wrote it, and reports a false "stale artifact" everywhere else.

Hashing LF-normalised content makes the digest reproducible on any platform,
which is the only way a checked-in artifact can carry one at all. The trade is
that `source.sha256` does not equal `sha256sum data/champions.json` on a
machine whose checkout uses LF; compare against `source_sha256()` instead.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CHAMPIONS_CACHE = Path(__file__).resolve().parents[1] / "data" / "champions.json"


def source_sha256(source: Path) -> str:
    """Digest a tracked text file's LF-normalised bytes, so it is platform-stable."""
    return hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def source_receipt(source: Path, kind: str = "local Wiki cache") -> dict[str, str]:
    """Describe the tracked data file an artifact was derived from."""
    return {
        "kind": kind,
        # as_posix() so a Windows rebuild matches a macOS/Linux one.
        "path": source.relative_to(source.parents[1]).as_posix(),
        "sha256": source_sha256(source),
    }


def cache_patch(champions: Mapping[str, Any] | None = None) -> str:
    """The Wiki patch ``data/`` pins: the newest ``patchLastChanged`` it carries.

    Derived so no builder has to carry a patch number of its own. A literal
    default stamps last patch's version onto this patch's artifact the first
    time someone re-runs a builder without the flag.
    """
    if champions is None:
        champions = json.loads(CHAMPIONS_CACHE.read_text(encoding="utf-8"))
    patches = {
        str(record.get("patchLastChanged") or "")
        for record in champions.values()
        if isinstance(record, Mapping)
    }
    patches.discard("")
    if not patches:
        raise ValueError(
            "no champion in the cached table carries patchLastChanged — "
            "cannot derive the patch the cache pins"
        )
    return max(
        patches,
        key=lambda patch: [
            int(part) if part.isdigit() else -1 for part in patch.split(".")
        ],
    )
