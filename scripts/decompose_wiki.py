#!/usr/bin/env python3
"""Decompose the League of Legends Wiki — full article inventory and fetcher.

The wiki is template-heavy: raw wikitext is thin (champion pages <4 KB) and
the real content lives in templates/modules. This tool owns the *inventory*
(which pages exist) and the *fetch layer* (raw wikitext on demand); per-family
parsers (champions, items, runes, summoner spells, buffs, mechanics, monsters,
minions) follow the lolstaticdata pattern.

Usage:
    python scripts/decompose_wiki.py --index              # rebuild data/wiki/article-index.json
    python scripts/decompose_wiki.py --fetch "Ahri"       # fetch one page's wikitext
    python scripts/decompose_wiki.py --fetch-family champions --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

API = "https://wiki.leagueoflegends.com/en-us/api.php"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _anchored_out_root() -> Path:
    """Resolve --out-root, refusing any path outside the repository."""
    root = Path(OUT_ROOT) if OUT_ROOT else _REPO_ROOT / "data"
    resolved = root.resolve()
    if (
        _REPO_ROOT.resolve() not in resolved.parents
        and resolved != _REPO_ROOT.resolve()
    ):
        raise SystemExit(f"--out-root {root} is outside the repository ({_REPO_ROOT})")
    return resolved


OUT_ROOT: str = ""  # set from --out-root below

INDEX_PATH = Path("data/wiki/article-index.json")
RAW_DIR = Path("data/wiki-raw")
UA = "Scryglass-wiki-decompose/0.1 (research)"


def api(client, params):
    params = dict(params)
    params["format"] = "json"
    r = client.get(API, params=params)
    r.raise_for_status()
    return r.json()


def build_index(out: Path) -> int:
    pages = {}
    cont = None
    with httpx.Client(
        timeout=60, headers={"User-Agent": UA}, follow_redirects=True
    ) as c:
        while True:
            params = {
                "action": "query",
                "generator": "allpages",
                "gapnamespace": "0",
                "gaplimit": "50",
                "gapfilterredir": "nonredirects",
                "prop": "info|categories",
                "inprop": "size",
                "cllimit": "25",
            }
            if cont:
                params.update(cont)
            d = api(c, params)
            for pid, p in d.get("query", {}).get("pages", {}).items():
                pages[p["title"]] = {
                    "pageid": pid,
                    "len": p.get("length", 0),
                    "cats": [
                        x["title"].replace("Category:", "")
                        for x in p.get("categories", [])
                    ],
                }
            cont = d.get("continue")
            if not cont:
                break
            time.sleep(0.35)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pages, indent=0, sort_keys=True))
    return len(pages)


def fetch_wikitext(title: str, out: Path) -> Path | None:
    with httpx.Client(
        timeout=120, headers={"User-Agent": UA}, follow_redirects=True
    ) as c:
        d = api(
            c,
            {
                "action": "query",
                "titles": title,
                "prop": "revisions",
                "rvprop": "content|ids",
                "rvslots": "main",
                "formatversion": "2",
            },
        )
        for page in d.get("query", {}).get("pages", []):
            if "missing" in page:
                return None
            revs = page.get("revisions", [])
            if not revs:
                return None
            text = revs[0].get("slots", {}).get("main", {}).get("content", "")
            safe = title.replace("/", "__")
            dest = out / f"{safe}.wiki"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            return dest
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--fetch", metavar="TITLE")
    ap.add_argument("--fetch-family", metavar="FAMILY")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--out-root", default="", help="data root (default <repo>/data)")
    args = ap.parse_args()

    global INDEX_PATH, RAW_DIR
    _anchored = _anchored_out_root()
    INDEX_PATH = _anchored / "wiki" / "article-index.json"
    RAW_DIR = _anchored / "wiki-raw"

    if args.index:
        n = build_index(INDEX_PATH)
        print(f"index: {n} articles -> {INDEX_PATH}")
        return
    if args.fetch:
        dest = fetch_wikitext(args.fetch, RAW_DIR)
        print(f"fetched {args.fetch} -> {dest}")
        return
    if args.fetch_family:
        index = json.loads(INDEX_PATH.read_text())
        members = [t for t in index if args.fetch_family.lower() in t.lower()][
            : args.limit
        ]
        for t in members:
            dest = fetch_wikitext(t, RAW_DIR)
            print(f"  {t} -> {dest}")
            time.sleep(0.35)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
