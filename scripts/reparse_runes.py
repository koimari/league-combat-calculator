#!/usr/bin/env python3
"""Recompute data/runes.json's effects from its own cached description text.

A rune-parser fix reaches the cache without a wiki pull:

    python scripts/reparse_runes.py [--check]

``--check`` reparses into a scratch directory and reports the runes whose
committed effects disagree with what the parser produces, writing nothing.
Without it the cache is rewritten in place.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.data_updater import (  # noqa: E402
    DEFAULT_DATA_DIR,
    reparse_cached_rune_effects,
)

_COMPARED = ("effects", "parse_warnings")


def drifted_runes(data_dir: Path = DEFAULT_DATA_DIR) -> list[str]:
    """Names in ``data_dir/runes.json`` the current parser would rewrite."""
    cache = data_dir / "runes.json"
    committed = json.loads(cache.read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="reparse-runes-"))
    try:
        shutil.copy2(cache, scratch / "runes.json")
        reparsed = reparse_cached_rune_effects(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return sorted(
        name
        for name, entry in reparsed.items()
        if any(entry.get(key) != committed.get(name, {}).get(key) for key in _COMPARED)
    )


def main() -> int:
    """CLI entry point: rewrite the cache, or report its drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing the cache",
    )
    args = parser.parse_args()

    if not args.check:
        runes = reparse_cached_rune_effects()
        print(f"reparsed {len(runes)} runes into {DEFAULT_DATA_DIR / 'runes.json'}")
        return 0

    drifted = drifted_runes()
    if drifted:
        print(f"{len(drifted)} runes disagree with the current parser:")
        for name in drifted:
            print(" -", name)
        return 1
    print("every cached rune matches the current parser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
