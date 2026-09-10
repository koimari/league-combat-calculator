"""The wiki rune-template pull and the reparse of the cached rune effects."""

import json
from collections.abc import Generator
from copy import deepcopy
from pathlib import Path
from typing import Any

from .data_fetcher import DEFAULT_DATA_DIR, _read_cache
from .data_registry import write_runtime_cache
from .rune_parser import (
    ADAPTIVE_FORCE_KEY,
    RESERVED_CACHE_KEYS,
    SHARDS_KEY,
    adaptive_force_payload,
    parse_rune_effects,
    path_order,
    rune_payload,
    shard_payload,
)
from .vendor_path import download_json
from .wiki_fetch import download_page, http_get

_WIKI_API_URL = "https://wiki.leagueoflegends.com/en-us/api.php"


_WIKI_PAGE_URL = "https://wiki.leagueoflegends.com/en-us/{title}"


_WIKI_RAW_URL = "https://wiki.leagueoflegends.com/en-us/{title}?action=raw"


_RUNE_TEMPLATE_PREFIX = "Template:Rune data "


#: The page whose Shards table is the stat-shard roster, and the template
#: that owns what one point of adaptive force converts to.  Neither has a
#: ``Rune data`` template, so both are read where the wiki writes them.
_RUNE_PAGE_TITLE = "Rune"


_ADAPTIVE_TEMPLATE_TITLE = "Template:Adaptive"


_RUNES_REFORGED_URL = (
    "http://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json"
)


def _wiki_api(**params: Any) -> dict[str, Any]:
    """One MediaWiki API read against the League Wiki."""
    params.setdefault("format", "json")
    params.setdefault("formatversion", 2)
    response = http_get(_WIKI_API_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _wiki_page(title: str) -> tuple[int, str]:
    """One wiki page's current revision id and wikitext.

    The revision travels with the text because the two pages read this way
    — the Rune page's shard table and ``Template:Adaptive`` — have no
    ``Rune data`` template to re-derive them from, so the cache records
    which revision it read.
    """
    page = _wiki_api(
        action="query",
        prop="revisions",
        rvprop="ids|content",
        rvslots="main",
        titles=title,
    )["query"]["pages"][0]
    revision = page["revisions"][0]
    return int(revision["revid"]), revision["slots"]["main"]["content"]


def rune_roster(latest_version: str) -> list[dict[str, Any]]:
    """Every rune the game offers, from Data Dragon's ``runesReforged.json``.

    Row 0 is the path's keystone row and rows 1-3 its minor slots, which is
    the roster's own ordering — the calculator keeps no second list of rune
    names to drift from it.
    """
    styles = download_json(_RUNES_REFORGED_URL.format(version=latest_version))
    return [
        {
            "name": perk["name"],
            "path": style["name"],
            "row": row,
            "icon": f"https://ddragon.leagueoflegends.com/cdn/img/{perk['icon']}",
        }
        for style in styles
        for row, slot in enumerate(style.get("slots", []))
        for perk in slot.get("runes", [])
    ]


def _rune_template_titles() -> dict[str, str]:
    """Every ``Template:Rune data`` page title, keyed by casefolded rune name.

    Data Dragon and the wiki capitalise differently ("Jack Of All Trades"
    against "Jack of All Trades"), and a title guessed from the roster name
    404s on exactly those runes.  One index read resolves every name against
    the wiki's own titles instead.
    """
    pages = _wiki_api(
        action="query",
        list="allpages",
        apprefix="Rune data ",
        apnamespace=10,
        aplimit="500",
    )["query"]["allpages"]
    return {
        page["title"][len(_RUNE_TEMPLATE_PREFIX) :].casefold(): page["title"]
        for page in pages
        if page["title"].startswith(_RUNE_TEMPLATE_PREFIX)
    }


def _process_runes(
    latest_version: str,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Fetch and parse every rune's wiki data template, plus the shard table.

    Yields progress events and returns the ``data/runes.json`` payload. A
    rune whose template fails to download is recorded with an ``error``
    field instead of silently dropping from the roster, and so are the two
    page-level reads.
    """
    roster = rune_roster(latest_version)
    titles = _rune_template_titles()
    runes: dict[str, Any] = {}
    rune_page = _rune_page_facts(runes)
    if rune_page is not None:
        roster = _ordered_roster(roster, rune_page)
    for index, entry in enumerate(roster, start=1):
        name = entry["name"]
        try:
            title = titles.get(name.casefold())
            if title is None:
                raise LookupError(f"no {_RUNE_TEMPLATE_PREFIX}{name} page on the wiki")
            wikitext = download_page(
                _WIKI_RAW_URL.format(title=title.replace(" ", "_"))
            )
            runes[name] = rune_payload(
                name,
                wikitext,
                icon=entry["icon"],
                path=entry["path"],
                row=entry["row"],
            )
            status = f"Parsed {name}"
        except Exception as exc:
            runes[name] = {**entry, "error": str(exc)}
            status = f"Failed {name}: {exc}"
        yield {
            "phase": "runes",
            "status": status,
            "current": index,
            "total": len(roster),
        }
    _adaptive_force_facts(runes)
    return runes


def _rune_page_facts(runes: dict[str, Any]) -> str | None:
    """Read the Rune page once: its shard table, and its path order.

    Returns the wikitext so the caller can order the roster by the same
    read, or ``None`` when the page could not be fetched — in which case the
    shard block records the error and the roster keeps Data Dragon's order.
    """
    try:
        revision, wikitext = _wiki_page(_RUNE_PAGE_TITLE)
        runes[SHARDS_KEY] = shard_payload(
            wikitext,
            source=_WIKI_PAGE_URL.format(title=_RUNE_PAGE_TITLE),
            revision=revision,
        )
    except Exception as exc:
        runes[SHARDS_KEY] = {"error": str(exc)}
        return None
    return wikitext


def _adaptive_force_facts(runes: dict[str, Any]) -> None:
    """Read ``Template:Adaptive``'s conversion into the payload."""
    title = _ADAPTIVE_TEMPLATE_TITLE
    try:
        revision, wikitext = _wiki_page(title)
        runes[ADAPTIVE_FORCE_KEY] = adaptive_force_payload(
            wikitext,
            source=_WIKI_PAGE_URL.format(title=title.replace(" ", "_")),
            revision=revision,
        )
    except Exception as exc:
        runes[ADAPTIVE_FORCE_KEY] = {"error": str(exc)}


def _ordered_roster(
    roster: list[dict[str, Any]], wikitext: str
) -> list[dict[str, Any]]:
    """Sort the roster into the Rune page's own path order, then by row.

    Data Dragon returns paths in its own order; the cache is written in the
    order the game shows them.  The sort is stable, so within a path a rune's
    position stays Data Dragon's fact."""
    rank = {name: index for index, name in enumerate(path_order(wikitext))}
    unknown = len(rank)
    return sorted(
        roster, key=lambda entry: (rank.get(entry["path"], unknown), entry["row"])
    )


def update_runes(
    latest_version: str,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Pull the whole rune page and write ``data/runes.json``.

    Its own door because the rune roster, unlike champions and items, can be
    re-pulled on its own: it is one Data Dragon read plus one wiki page per
    rune, and patch day should not have to re-scrape the champion corpus to
    refresh a rune's text.
    """
    yield {"phase": "runes", "status": "Updating runes..."}
    runes = yield from _process_runes(latest_version)
    write_runtime_cache(
        DEFAULT_DATA_DIR,
        "runes.json",
        runes,
        source_url=_WIKI_PAGE_URL.format(title=_RUNE_PAGE_TITLE),
    )
    failed = [name for name, entry in runes.items() if "error" in entry]
    status = f"Saved {len(runes) - len(failed)} rune entries"
    if failed:
        status += f" (failed: {', '.join(failed)})"
    yield {"phase": "runes", "status": status}
    return runes


def _reparse_entry(entry: dict[str, Any], name: str = "") -> None:
    """Recompute one cached rune's or shard option's effects, in place."""
    description = entry.get("description")
    if not description:
        return
    effects, warnings = parse_rune_effects(name, description)
    entry["effects"] = effects
    entry.pop("parse_warnings", None)
    if warnings:
        entry["parse_warnings"] = warnings


def reparse_cached_rune_effects(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    """Recompute every cached rune's effects from its stored description.

    ``data/runes.json`` keeps each rune's verbatim template text, so a
    parser improvement can reach the cache deterministically and offline —
    no wiki pull, no unrelated patch-day diffs. Entries without a
    description (failed downloads) are left untouched.
    """
    cached = _read_cache(data_dir, "runes.json")
    runes = {name: deepcopy(entry) for name, entry in cached.items()}
    for name, entry in runes.items():
        if name == SHARDS_KEY:
            for slot in entry.get("slots", ()):
                for option in slot.get("options", ()):
                    _reparse_entry(option)
        elif name not in RESERVED_CACHE_KEYS:
            _reparse_entry(entry, name)
    meta_path = data_dir / ".runes.json.meta"
    previous = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    )
    write_runtime_cache(
        data_dir,
        "runes.json",
        runes,
        source_url="https://wiki.leagueoflegends.com/en-us/Rune",
        fetched_at=previous.get("fetched_at"),
    )
    return runes
