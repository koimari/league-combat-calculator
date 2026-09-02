#!/usr/bin/env python3
"""Decompose the local League of Legends game binaries into parsed JSON.

Extracts and parses the authoritative game data from the installed client
(/Applications/League of Legends.app) — the exact numeric layer behind every
wiki page:

- data/items/items.bin            -> all item data (ItemData entries)
- data/characters/<name>/<name>.bin -> CharacterRecord + spell + buff data
- data/maps/map11/map11.bin       -> Summoner's Rift map data

Requires the tool venv (league-tools + cdtb + hash tables):
    uv venv --python 3.12 ~/.local/mcp/wad-env
    uv pip install --python ~/.local/mcp/wad-env/bin/python league-tools cdtb
    (hash tables auto-download to ~/.local/share/cdragon/data/hashes/lol)

Usage:
    ~/.local/mcp/wad-env/bin/python scripts/decompose_binaries.py --champions --items
    ~/.local/mcp/wad-env/bin/python scripts/decompose_binaries.py --items --verify
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

LO_APP = "/Applications/League of Legends.app"
GAME_DIR = Path(LO_APP) / "Contents/LoL/Game"
FINAL_DIR = GAME_DIR / "DATA/FINAL"
HASH_URL_BASE = "https://raw.communitydragon.org/data/hashes/lol"
HASH_FILE = Path.home() / ".local/mcp/hashes.game.txt"
CDTB_HASH_DIR = Path.home() / ".local/share/cdragon/data/hashes/lol"
_REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = _REPO_ROOT / "data" / "bin"


def _download(url: str, dest: Path, chunk=1 << 20) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with Path(dest).open("wb") as f:
            f.writelines(r.iter_content(chunk))


def ensure_hash_tables() -> dict[int, str]:
    if not HASH_FILE.exists():
        print(f"downloading {HASH_FILE.name} ...")
        _download(f"{HASH_URL_BASE}/hashes.game.txt", HASH_FILE)
    table: dict[int, str] = {}
    with Path(HASH_FILE).open() as f:
        for line in f:
            h, _, path = line.partition(" ")
            table[int(h, 16)] = path.rstrip("\n")
    for name in [
        "hashes.binhashes.txt",
        "hashes.binfields.txt",
        "hashes.bintypes.txt",
        "hashes.binentries.txt",
    ]:
        dest = CDTB_HASH_DIR / name
        if not dest.exists():
            print(f"downloading {name} ...")
            _download(f"{HASH_URL_BASE}/{name}", dest)
    return table


def open_wad(path: Path):
    from league_tools import WAD

    return WAD(str(path))


def extract_path(wad, table, path: str) -> bytes | None:
    h = wad.get_hash(path)
    for sec in wad.files:
        if sec.path_hash == h:
            data = wad.extract_by_section(sec, "", raw=True)
            if data:
                return data
    return None


def parse_bin(data: bytes, name: str):
    import io

    from cdtb.binfile import BinFile

    bf = BinFile(io.BytesIO(data))
    return bf.to_serializable()


def champion_wads():
    champ_dir = FINAL_DIR / "Champions"
    for f in sorted(champ_dir.glob("*.wad.client")):
        if f.name.endswith(".en_US.wad.client"):
            continue
        yield f


def decompose_champions(table, out: Path) -> list[str]:

    done = []
    for wad_path in champion_wads():
        name = wad_path.stem.replace(".wad", "")
        target = f"data/characters/{name.lower()}/{name.lower()}.bin"
        w = open_wad(wad_path)
        data = extract_path(w, table, target)
        if data is None:
            # try without lowercase
            continue
        rec = parse_bin(data, name)
        dest = out / "characters" / f"{name.lower()}.bin.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(rec, default=str, indent=1))
        done.append(name.lower())
    return done


def decompose_items(table, out: Path):
    """Item data: local data/items/items.bin if present, else the pinned
    16.15 CommunityDragon dump (identical client version 16.15.8024387)."""
    w = open_wad(FINAL_DIR / "Global.wad.client")
    data = extract_path(w, table, "data/items/items.bin")
    source = "local"
    if data is None:
        import requests

        print(
            "items.bin not local; fetching pinned 16.15 dump from CommunityDragon ..."
        )
        r = requests.get(
            "https://raw.communitydragon.org/16.15/game/data/items/items.bin.json",
            timeout=300,
        )
        if r.status_code != 200:
            raise RuntimeError(
                "items.bin unavailable locally and 16.15 CDN dump 404; "
                "item decomposition will use per-item Lua scripts "
                "(data/items/<id>.lua) in a later step"
            )
        data = r.content
        source = "cdragon-16.15"
    # try parse as bin first, else treat as pre-parsed json
    try:
        rec = parse_bin(data, "items")
    except Exception:
        rec = json.loads(data)
    dest = out / "items" / "items.bin.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, default=str, indent=1))
    return dest, len(data), len(json.dumps(rec, default=str)), source


def decompose_map11(table, out: Path):

    map_wads = list((FINAL_DIR / "Maps/Shipping").glob("*.wad.client"))
    for mw in map_wads:
        try:
            w = open_wad(mw)
        except Exception:  # noqa: S112 - skip an unreadable wad
            continue
        data = extract_path(w, table, "data/maps/map11/map11.bin")
        if data:
            rec = parse_bin(data, "map11")
            dest = out / "maps" / "map11.bin.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(rec, default=str, indent=1))
            return dest, len(data)
    return None, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--champions", action="store_true")
    ap.add_argument("--items", action="store_true")
    ap.add_argument("--map11", action="store_true")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    if not any([args.champions, args.items, args.map11]):
        ap.error("choose at least one of --champions/--items/--map11")

    table = ensure_hash_tables()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    receipt: dict = {"source": "local client 16.15.8024387", "files": {}}

    if args.items:
        dest, raw, parsed, source = decompose_items(table, out)
        receipt["files"]["items"] = {
            "path": str(dest),
            "raw_bytes": raw,
            "json_chars": parsed,
            "source": source,
        }
        print(f"items -> {dest} ({raw} raw bytes)")

    if args.champions:
        done = decompose_champions(table, out)
        receipt["files"]["champions"] = {"count": len(done), "sample": done[:10]}
        print(f"champions parsed: {len(done)}")

    if args.map11:
        dest, raw = decompose_map11(table, out)
        if dest:
            receipt["files"]["map11"] = {"path": str(dest), "raw_bytes": raw}
            print(f"map11 -> {dest}")
        else:
            print("map11 not found")

    receipt_path = out / "decompose-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=1))
    print(f"receipt: {receipt_path}")


if __name__ == "__main__":
    main()
