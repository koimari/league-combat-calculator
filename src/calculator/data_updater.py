"""Module for updating champion and item data using lolstaticdata.

Wraps the lolstaticdata library to fetch fresh data from the League Wiki,
Data Dragon, and Community Dragon, with per-champion progress tracking.
"""

import json
import sys
import threading
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from .vendor_path import (
    LOLSTATICDATA_ROOT,
    download_json,
    get_latest_patch_version,
    lsd_utils,
)

# Monkey-patch download_soup on Windows: the original builds cache filenames
# via url.replace("/", "@") but never strips colons, which are illegal in
# Windows filenames.  download_json already does url.replace(":", ""), so
# we apply the same fix here.
if sys.platform == "win32":
    _orig_download_soup = lsd_utils.download_soup

    def _win_download_soup(
        url: str,
        use_cache: bool = True,
        dir: str = "__cache__",  # noqa: A002 - the vendor signature this replaces
    ) -> str:
        import os as _os

        from bs4 import BeautifulSoup as _BeautifulSoup

        directory = _os.path.abspath(
            _os.path.join(
                _os.path.dirname(_os.path.realpath(lsd_utils.__file__)), "../.."
            )
        )
        directory = _os.path.join(directory, dir)
        if not _os.path.exists(directory):
            _os.mkdir(directory)

        sanitized = url.replace(":", "").replace("/", "@")
        if "ITEM_DATA" not in url.upper():
            fn = _os.path.join(directory, sanitized)
        else:
            url_split = url.split("Item_data_")[1]
            fn = _os.path.join(directory, url_split.replace("/", "@"))

        if use_cache and _os.path.exists(fn):
            with open(fn, encoding="utf-8") as f:
                html = f.read()
        else:
            html = download_page(url)
            if use_cache:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(html)

        soup = _BeautifulSoup(html, "lxml")
        html = str(soup)
        for old, new in [
            ("\u00a0", " "),
            ("\u300c", "["),
            ("\u300d", "]"),
            ("\u00ba", "\u00b0"),
            ("\u200b", ""),
            ("\u200e", ""),
            ("\u2013", ":"),
            ("\xa0", " "),
            ("\uff06", "&"),
        ]:
            html = html.replace(old, new)
        return html

    lsd_utils.download_soup = _win_download_soup

from lolstaticdata.champions.__main__ import get_ability_filenames
from lolstaticdata.champions.pull_champions_dragons import get_ability_url
from lolstaticdata.champions.pull_champions_wiki import LolWikiDataHandler

from .data_fetcher import DEFAULT_DATA_DIR
from .data_registry import write_runtime_cache
from .item_source_merge import merge_item_sources
from .rune_pull import update_runes
from .wiki_fetch import download_page

# Only one update can run at a time
_update_lock = threading.Lock()


ABILITY_KEY_TO_IDENTIFIER = {
    "P": "passive",
    "Q": "q",
    "Q2": "q",
    "W": "w",
    "E": "e",
    "R": "r",
}


def _build_champion_payload(
    champion: Any,
    latest_version: str,
    ddragon_champion: dict[str, Any],
) -> dict[str, Any]:
    """Process a single champion object into a JSON-serializable payload."""
    champion.icon = (
        f"http://ddragon.leagueoflegends.com/cdn/{latest_version}"
        f"/img/champion/{ddragon_champion['image']['full']}"
    )

    if champion.abilities:
        try:
            icon_filenames = get_ability_filenames(
                "http://raw.communitydragon.org/latest/game/assets"
                f"/characters/{champion.key.lower()}/hud/icons2d/"
            )
            for ability_key, abilities_list in champion.abilities.items():
                for ability_index, ability in enumerate(abilities_list, start=1):
                    url = get_ability_url(
                        champion.key,
                        ABILITY_KEY_TO_IDENTIFIER[ability_key],
                        ability_index,
                        ability.name,
                        latest_version,
                        ddragon_champion,
                        icon_filenames,
                    )
                    ability.icon = url
        except Exception:  # noqa: S110 - icons are decoration
            pass

    champion_payload = json.loads(champion.__json__(ensure_ascii=False))
    champion_payload.pop("skins", None)
    champion_payload.pop("lore", None)
    champion_payload.pop("faction", None)

    return champion_payload


@dataclass
class _ChampionPass:
    """What one champion refresh accumulates across its bulk and single passes."""

    latest_version: str
    ddragon: dict[str, Any]
    champions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    processed_keys: set[str] = field(default_factory=set)
    processed: int = 0

    def event(self, status: str, champion: str | None = None) -> dict[str, Any]:
        """One progress event over the running count."""
        event: dict[str, Any] = {
            "phase": "champions",
            "status": status,
            "current": self.processed,
            "total": len(self.ddragon),
        }
        if champion is not None:
            event["champion"] = champion
        return event

    def add(self, champion: Any, key: str) -> dict[str, Any]:
        """Build one champion's payload and report it processed."""
        self.champions.append(
            _build_champion_payload(champion, self.latest_version, self.ddragon[key])
        )
        self.processed += 1
        return self.event(f"Processed {champion.name}", champion.name)


def _bulk_pass(state: _ChampionPass) -> Generator[dict[str, Any], None, bool]:
    """Every champion from one wiki download; True when the generator itself
    crashed, in which case everything yielded so far stands."""
    handler = LolWikiDataHandler(
        use_cache=False,
        process_stats=True,
        process_abilities=True,
        process_skins=False,
    )
    try:
        for champion in handler.get_champions():
            try:
                champion_key = champion.key
                state.processed_keys.add(champion_key)
                if champion_key not in state.ddragon:
                    continue
                yield state.add(champion, champion_key)
            except Exception as exc:
                name = getattr(champion, "name", "Unknown")
                state.processed_keys.add(getattr(champion, "key", name))
                state.skipped.append(name)
                state.processed += 1
                yield state.event(f"Skipped {name}: {exc}", name)
    except Exception:
        state.skipped.append("Unknown (wiki parse error)")
        state.processed += 1
        yield state.event("Bulk parse error — switching to individual mode")
        return True
    return False


def _single_pass(state: _ChampionPass) -> Generator[dict[str, Any], None, None]:
    """The champions the bulk pass never reached, one cached wiki page each,
    so one bad champion cannot block the others."""
    remaining = [key for key in state.ddragon if key not in state.processed_keys]
    for champion_key in remaining:
        try:
            handler = LolWikiDataHandler(
                use_cache=True,
                target_champion=champion_key,
                process_stats=True,
                process_abilities=True,
                process_skins=False,
            )
            found = False
            for champion in handler.get_champions():
                found = True
                state.processed_keys.add(champion.key)
                yield state.add(champion, champion_key)
            if not found:
                # In ddragon but not in the wiki data.
                state.processed += 1
        except Exception as exc:
            state.skipped.append(champion_key)
            state.processed += 1
            yield state.event(f"Skipped {champion_key}: {exc}", champion_key)


def _process_champions(
    latest_version: str,
) -> Generator[dict[str, Any], None, tuple[list[dict[str, Any]], list[str]]]:
    """Fetch and process all champion data from the League Wiki.

    One bulk wiki download first; if that generator crashes on a champion
    with unparseable wiki data, the remaining champions are pulled one page
    each.  Yields progress events and returns (champions, skipped).
    """
    ddragon = download_json(
        f"http://ddragon.leagueoflegends.com/cdn/{latest_version}"
        f"/data/en_US/championFull.json"
    )["data"]
    state = _ChampionPass(latest_version, ddragon)
    yield state.event("Processing champions...")
    if (yield from _bulk_pass(state)):
        yield from _single_pass(state)
    return state.champions, state.skipped


def _wiki_item_table() -> dict[str, Any]:
    """The Wiki's ``Module:ItemData/data`` table, keyed by item name.
    The generator keeps only each effect's first description and drops mode
    availability, so ``item_source`` needs the raw table."""
    from lolstaticdata.items.pull_items_wiki import get_item_urls

    return get_item_urls(False)


def _riot_item_descriptions() -> dict[int, str]:
    """Riot's rich item descriptions from CommunityDragon, keyed by item id.

    Caching them is what lets the source audit verify the Wiki cache against
    Riot offline, on any machine, without a second patch-day pull.
    """
    from lolstaticdata.items.pull_items_dragon import DragonItem

    return {
        int(entry["id"]): str(entry.get("description") or "")
        for entry in DragonItem.get_cdragon()
        if entry.get("id") is not None
    }


def _process_items() -> dict[str, Any] | None:
    """Run the lolstaticdata items generator and read the output.

    Returns the source-merged items dict, or None if generation failed.
    """
    # Import the generator only on the explicit refresh path.  Its module
    # class initialization probes Data Dragon for the latest patch, so an
    # ordinary cached-data import must never perform network I/O.
    from lolstaticdata.items.__main__ import main as run_items_generator

    run_items_generator()

    items_path = LOLSTATICDATA_ROOT / "items.json"
    if items_path.exists():
        with items_path.open(encoding="utf-8") as items_file:
            generated = json.load(items_file)
        return merge_item_sources(
            generated, _wiki_item_table(), _riot_item_descriptions()
        )
    return None


def _update_champions(latest_version: str) -> Generator[dict[str, Any], None, int]:
    """Refresh champions.json; returns the champion count for the done event."""
    champions, skipped = yield from _process_champions(latest_version)
    write_runtime_cache(
        DEFAULT_DATA_DIR,
        "champions.json",
        {payload["key"]: payload for payload in champions},
        source_version=latest_version,
        source_url="https://wiki.leagueoflegends.com/en-us/List_of_champions",
    )
    status = f"Saved {len(champions)} champions"
    if skipped:
        status += f" (skipped {len(skipped)}: {', '.join(skipped)})"
    yield {
        "phase": "champions",
        "status": status,
        "current": len(champions),
        "total": len(champions),
    }
    return len(champions)


def _update_items(latest_version: str) -> Generator[dict[str, Any], None, None]:
    """Refresh items.json, warning instead of writing when nothing came back."""
    yield {"phase": "items", "status": "Updating items (this may take a moment)..."}
    items_data = _process_items()
    if not items_data:
        yield {"phase": "items", "status": "Warning: no items data generated"}
        return
    write_runtime_cache(
        DEFAULT_DATA_DIR,
        "items.json",
        items_data,
        source_version=latest_version,
        source_url="https://wiki.leagueoflegends.com/en-us/Item",
    )
    yield {"phase": "items", "status": f"Saved {len(items_data)} items"}


def update_data() -> Generator[dict[str, Any], None, None]:
    """Fetch fresh champion and item data from upstream sources.

    Yields progress dicts suitable for Server-Sent Events:
        phase: "init" | "champions" | "items" | "done" | "error"
        status: human-readable message
        current/total: numeric progress (champions phase)
        patch: patch version string (done phase)
    """
    if not _update_lock.acquire(blocking=False):
        yield {"phase": "error", "status": "An update is already in progress."}
        return

    try:
        yield {"phase": "init", "status": "Fetching latest patch version..."}
        latest_version = get_latest_patch_version()
        yield {"phase": "init", "status": f"Latest patch: {latest_version}"}
        champions_count = yield from _update_champions(latest_version)
        yield from _update_items(latest_version)
        yield from update_runes(latest_version)
        yield {
            "phase": "done",
            "status": f"Update complete! Now on patch {latest_version}",
            "patch": latest_version,
            "champions_count": champions_count,
        }
    except Exception as exc:
        yield {"phase": "error", "status": f"Update failed: {exc}"}
    finally:
        _update_lock.release()
