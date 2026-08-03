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
that `source.sha256` no longer equals `sha256sum data/champions.json` on a
machine whose checkout uses LF; compare against `source_sha256()` instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


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
