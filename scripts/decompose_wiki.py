#!/usr/bin/env python3
"""Decompose the League of Legends Wiki — full article inventory and fetcher.

The wiki is template-heavy: raw wikitext is thin (champion pages <4 KB) and
the real content lives in templates/modules. This tool owns the *inventory*
(which pages exist) and the *fetch layer* (raw wikitext on demand); per-family
parsers (champions, items, runes, summoner spells, buffs, mechanics, monsters,
minions) follow the lolstaticdata pattern.

Usage:
    python scripts/decompose_wiki.py --index              # rebuild data/wiki/article-index.json
    python scripts/decompose_wiki.py --wiki-db            # rebuild data/wiki/league-wiki.sqlite3
    python scripts/decompose_wiki.py --fetch "Ahri"       # fetch one page's wikitext
    python scripts/decompose_wiki.py --fetch-family champions --limit 5
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

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
WIKI_DB_PATH = Path("data/wiki/league-wiki.sqlite3")
RAW_DIR = Path("data/wiki-raw")
UA = "Scryglass-wiki-decompose/0.1 (research)"


def _client(timeout: int) -> httpx.Client:
    """One wiki session: the research User-Agent, redirects followed."""
    return httpx.Client(
        timeout=timeout, headers={"User-Agent": UA}, follow_redirects=True
    )


def api(client: httpx.Client, params: Mapping[str, str]) -> dict[str, Any]:
    params = dict(params)
    params["format"] = "json"
    r = client.get(API, params=params)
    r.raise_for_status()
    return r.json()


def build_index(out: Path) -> int:
    pages = {}
    cont = None
    with _client(timeout=60) as c:
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


#: The reviewed-packet gate's whole read is ``SELECT title, revision_id,
#: revision_timestamp FROM pages WHERE namespace = 0``
#: (``build_reviewed_modules._wiki_revisions``), so those columns plus the page
#: id are the whole table.
PAGES_SCHEMA = (
    "CREATE TABLE pages ("
    "page_id INTEGER PRIMARY KEY, "
    "namespace INTEGER NOT NULL, "
    "title TEXT NOT NULL, "
    "revision_id INTEGER NOT NULL, "
    "revision_timestamp TEXT NOT NULL)"
)


def revision_rows(client: httpx.Client) -> Iterator[tuple[int, int, str, int, str]]:
    """Yield ``(page_id, namespace, title, revision_id, timestamp)`` for namespace 0.

    ``gaplimit`` is 50 because ``prop=revisions`` serves at most 50 pages per
    request. Redirects stay in, unlike ``build_index``: ``Nunu & Willump`` is
    one, and the packet asset receipts its revision like any other champion.
    """
    cont: dict[str, str] | None = None
    while True:
        params = {
            "action": "query",
            "generator": "allpages",
            "gapnamespace": "0",
            "gaplimit": "50",
            "prop": "revisions",
            "rvprop": "ids|timestamp",
            "formatversion": "2",
        }
        if cont:
            params.update(cont)
        payload = api(client, params)
        for page in payload.get("query", {}).get("pages", []):
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            yield (
                int(page["pageid"]),
                int(page["ns"]),
                str(page["title"]),
                int(revisions[0]["revid"]),
                str(revisions[0]["timestamp"]),
            )
        cont = payload.get("continue")
        if not cont:
            return
        time.sleep(0.35)


def build_wiki_db(out: Path, client: httpx.Client | None = None) -> int:
    """Write the local revision index the reviewed-packet gate reads.

    Staged through a sibling file and moved into place, so an interrupted run
    leaves no half-populated database for the gate to trust.
    """
    session = nullcontext(client) if client else _client(timeout=60)
    with session as connected:
        rows = list(revision_rows(connected))
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = out.with_name(out.name + ".building")
    staging.unlink(missing_ok=True)
    with closing(sqlite3.connect(staging)) as connection:
        connection.execute(PAGES_SCHEMA)
        connection.executemany("INSERT INTO pages VALUES (?, ?, ?, ?, ?)", rows)
        connection.commit()
    staging.replace(out)
    return len(rows)


def fetch_wikitext(title: str, out: Path) -> Path | None:
    with _client(timeout=120) as c:
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
    ap.add_argument(
        "--wiki-db",
        action="store_true",
        help="rebuild the revision index the reviewed-packet gate reads",
    )
    ap.add_argument("--fetch", metavar="TITLE")
    ap.add_argument("--fetch-family", metavar="FAMILY")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--out-root", default="", help="data root (default <repo>/data)")
    args = ap.parse_args()

    global INDEX_PATH, WIKI_DB_PATH, RAW_DIR
    _anchored = _anchored_out_root()
    INDEX_PATH = _anchored / "wiki" / "article-index.json"
    WIKI_DB_PATH = _anchored / "wiki" / "league-wiki.sqlite3"
    RAW_DIR = _anchored / "wiki-raw"

    if args.index:
        n = build_index(INDEX_PATH)
        print(f"index: {n} articles -> {INDEX_PATH}")
        return
    if args.wiki_db:
        n = build_wiki_db(WIKI_DB_PATH)
        print(f"wiki-db: {n} namespace-0 revisions -> {WIKI_DB_PATH}")
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
