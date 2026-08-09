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

data_version() is the other half of that ownership statement, read from
the consumer's side: one monotonic counter naming *which* runtime cache a
derived value was computed from, so a memo can tell "still current" from
"computed before the last refresh".
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
    "atoms": ("scripts/extract_atoms.py",),
    "practice-corpus": (),  # hand-authored only
}

# How many times this process has replaced a runtime cache.  Starts at zero
# and only ever grows, so "same version" is a sound reason to reuse a value
# derived from data/ and a bump is the one signal that invalidates every
# such memo at once.
_DATA_VERSION = 0


def data_version() -> int:
    """The current runtime-cache generation — monotonic, process-local.

    Every memo over data/-derived values keys on this number: two reads
    that see the same version saw the same cache, and write_runtime_cache
    bumping it is what makes a mid-process refresh recompute rather than
    serve a value derived from the cache it replaced.

    Deliberately unread for now.  The memos that will key on it belong to
    two lanes that are live at once, and a counter either of them declared
    would be a counter the other could not use, so it is declared here —
    in the module that owns the write it counts.
    """
    return _DATA_VERSION


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

    # The file on disk has changed, so the parsed-JSON cache is stale and so
    # is everything derived from it.  Both are invalidated here, before the
    # provenance metadata is written: a reader that sees the new version has
    # a live parse behind it.  ``global`` is the honest spelling of a
    # module-level counter; hiding it in a container would not make the
    # state any less module-level.
    _read_json_version.cache_clear()
    global _DATA_VERSION  # pylint: disable=global-statement
    _DATA_VERSION += 1

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
