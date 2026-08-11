"""Data-ownership registry: who may write under data/, and the only
runtime-cache write API.

Categories:
  RUNTIME_CACHE    — tracked inputs the calculator reads at runtime
                     (champions.json, items.json, runes.json).  Only
                     data_updater may write these, only via
                     write_runtime_cache().
  EXTERNAL_EVIDENCE— downloaded game/wiki files (gitignored or sample
                     tracked): gamefiles/, bin/, wiki/, wiki-raw/.
  DERIVED_ARTIFACT — regenerable outputs computed from cache/evidence:
                     economics-sourced.json, staleness.json, atoms/.
  HAND_AUTHORED    — worklists, audits, receipts: never written by scripts.

WRITERS maps every data/ subtree (or file) to the module(s) allowed to
write it.  tests/test_data_writer_inventory.py enforces the map with an
AST scan so a new downloader cannot silently join the boundary.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

CACHE_FILES = frozenset({"champions.json", "items.json", "runes.json"})

WRITERS: dict[str, tuple[str, ...]] = {
    "champions.json|items.json|runes.json": ("src/calculator/data_updater.py",),
    "staleness.json": ("scripts/patch_regression.py",),
    "economics-sourced.json": ("scripts/refresh_economics_data.py",),
    "onhit-matrix.json": ("scripts/build_onhit_matrix.py",),
    "gamefiles": ("scripts/patch_regression.py",),
    "bin": ("scripts/decompose_binaries.py",),
    "wiki": ("scripts/decompose_wiki.py",),
    "wiki-raw": ("scripts/decompose_wiki.py",),
    "atoms": ("scripts/atomize.py", "scripts/extract_atoms.py"),
    "practice-corpus": (),  # hand-authored only
}


def write_runtime_cache(
    data_directory: Path,
    filename: str,
    payload: dict[str, Any],
    *,
    source_url: str | None = None,
    source_version: str | None = None,
    source_hash: str | None = None,
) -> None:
    """Atomically write one tracked runtime-cache file with provenance meta.

    Refuses filenames outside CACHE_FILES: the three tracked caches have a
    single writer (data_updater) and every other data/ path has its own
    documented owner in WRITERS.
    """
    if filename not in CACHE_FILES:
        raise ValueError(
            f"{filename} is not a runtime-cache file; runtime cache is "
            f"limited to {sorted(CACHE_FILES)} (see data_registry.WRITERS)"
        )
    data_directory.mkdir(parents=True, exist_ok=True)
    data_path = data_directory / filename
    tmp_path = data_directory / f".{filename}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, data_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    from .data_fetcher import _read_json_version  # local: no import cycle

    _read_json_version.cache_clear()
    metadata: dict[str, Any] = {
        "fetched_at": time.time(),
        "filename": filename,
        "source_url": source_url,
        "source_version": source_version,
        "source_hash": source_hash,
    }
    meta_path = data_directory / f".{filename}.meta"
    with open(meta_path, "w", encoding="utf-8") as meta_file:
        json.dump(metadata, meta_file, indent=2)
