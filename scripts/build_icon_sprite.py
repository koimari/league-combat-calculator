#!/usr/bin/env python3
"""Build static/icon-sprite.webp + .json, the reference art scoreboard.js matches against.

One cell per cached champion (Data Dragon square portrait) and per cached item
(CommunityDragon 2D icon), each area-resampled to CELL px and stored as lossy
WebP: the frames it is matched against are video captures, so the sheet keeps
nothing they lose. The index maps a champion name or item id to its cell
number; row and column follow from ``columns``. The browser and the tests/js
harness both read this one asset, so the matcher never depends on a CDN at
request time.

Downloads go through data/icons/ (gitignored); a cell whose icon cannot be
fetched fails the build rather than leaving a hole the matcher would read as
"never matches".
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.source_receipt import cache_patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CELL = 40
COLUMNS = 24
ICON_CACHE = ROOT / "data" / "icons"


def sprite_entries(champions: dict, items: dict) -> list[tuple[str, str, str]]:
    """(kind, key, url) per cell, in the order the index assigns cell numbers."""
    rows = [("champion", record["name"], record["icon"]) for record in champions.values()]
    rows += [
        (
            "item",
            str(record["id"]),
            record["icon"],
        )
        for record in items.values()
        if record.get("icon") and not record.get("removed")
    ]
    return rows


def _fetch(kind: str, key: str, url: str) -> Image.Image:
    safe = "".join(ch if ch.isalnum() else "_" for ch in key)
    path = ICON_CACHE / f"{kind}-{safe}.png"
    if not path.exists():
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        path.write_bytes(response.content)
    return Image.open(BytesIO(path.read_bytes())).convert("RGB")


def build(champions: dict, items: dict) -> tuple[Image.Image, dict]:
    """Composite every icon into one sheet and return it with its index."""
    entries = sprite_entries(champions, items)
    ICON_CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(16) as pool:
        icons = list(pool.map(lambda entry: _fetch(*entry), entries))
    rows = -(-len(entries) // COLUMNS)
    sheet = Image.new("RGB", (COLUMNS * CELL, rows * CELL))
    index: dict = {"cell": CELL, "columns": COLUMNS, "patch": cache_patch(champions), "champions": {}, "items": {}}
    for number, ((kind, key, _url), icon) in enumerate(zip(entries, icons)):
        resampled = icon.resize((CELL, CELL), Image.Resampling.BOX)
        sheet.paste(resampled, ((number % COLUMNS) * CELL, (number // COLUMNS) * CELL))
        index[f"{kind}s"][key] = number
    return sheet, index


def check(index_path: Path, sheet_path: Path, champions: dict, items: dict) -> str | None:
    """The reason the committed sprite is stale, or None when it is current."""
    if not index_path.exists() or not sheet_path.exists():
        return "sprite assets are missing"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = sprite_entries(champions, items)
    listed = {(kind[:-1], key) for kind in ("champions", "items") for key in index.get(kind, {})}
    wanted = {(kind, key) for kind, key, _url in expected}
    if listed != wanted:
        missing = sorted(wanted - listed)
        extra = sorted(listed - wanted)
        return f"index drift: missing {missing[:5]}, extra {extra[:5]}"
    with Image.open(sheet_path) as sheet:
        rows = -(-len(expected) // index["columns"])
        if sheet.size != (index["columns"] * index["cell"], rows * index["cell"]):
            return f"sheet is {sheet.size}, index implies {index['columns'] * index['cell']}x{rows * index['cell']}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champions", type=Path, default=ROOT / "data" / "champions.json")
    parser.add_argument("--items", type=Path, default=ROOT / "data" / "items.json")
    parser.add_argument("--output", type=Path, default=ROOT / "static" / "icon-sprite.webp")
    parser.add_argument("--check", action="store_true", help="fail instead of writing when the sprite has drifted")
    args = parser.parse_args()
    champions = json.loads(args.champions.read_text(encoding="utf-8"))
    items = json.loads(args.items.read_text(encoding="utf-8"))
    index_path = args.output.with_suffix(".json")

    if args.check:
        reason = check(index_path, args.output, champions, items)
        if reason:
            raise SystemExit(f"{args.output}: {reason}; rebuild with: python scripts/build_icon_sprite.py")
        print(f"{args.output} is current")
        return

    sheet, index = build(champions, items)
    sheet.save(args.output, quality=92, method=6)
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(index['champions'])} champions, {len(index['items'])} items)")


if __name__ == "__main__":
    main()
