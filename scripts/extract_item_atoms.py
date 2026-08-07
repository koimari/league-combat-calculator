#!/usr/bin/env python3
"""RETIRED (issue #140) — item atom extraction now lives in the unified
Atomizer item domain (src/calculator/atomizer_domains.atomize_item*).

The legacy classifier classified every passive/active against one whole-item
text blob with a process-global ``seen`` set, so the first passive absorbed
the atoms of every later passive and the active (94% of later-position
effects emitted zero atoms, receipts destroyed).

This module is kept ONLY as a compatibility CLI: it runs the unified item
domain (per-effect fragments, (atom_id, behavior) dedup, exact evidence
receipts) and writes the standard unified Atomizer output
``data/atoms/items.json`` + manifest — the same artifact
``scripts/atomize.py items`` produces. It performs no classification of its
own. Per-item files are no longer written under the gitignored
``data/item-atoms/`` tree; consumers must read ``data/atoms/items.json``
(scripts/build_receipts.py still reads the legacy per-item files until it is
migrated — see data_registry.WRITERS / .gitignore TODOs in this file).

Usage:
    python scripts/extract_item_atoms.py                 # all items
    python scripts/extract_item_atoms.py --out <dir>     # custom output dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calculator.atomizer import write_atoms  # noqa: E402
from src.calculator.atomizer_domains import atomize_item_catalogue  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "atoms" / "items.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    items = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    objects = atomize_item_catalogue(items)
    out_path = Path(args.out)
    manifest = write_atoms(out_path, domain="items", objects=objects)
    print(f"RETIRED CLI: delegated to the unified item domain -> {out_path}")
    print(f"items: {manifest['object_count']} | atoms: {manifest['atom_count']}")
    print(
        "(data/item-atoms/ per-item files are no longer written; "
        "read data/atoms/items.json instead)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
