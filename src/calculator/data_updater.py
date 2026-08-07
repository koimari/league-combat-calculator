"""Module for updating champion and item data using lolstaticdata.

Wraps the lolstaticdata library to fetch fresh data from the League Wiki,
Data Dragon, and Community Dragon, with per-champion progress tracking.
"""

import json
import sys
import threading
from pathlib import Path
from typing import Any, Generator

import requests as _requests

# Add the vendored lolstaticdata to the import path so we can use its modules directly
_LOLSTATICDATA_ROOT = (
    Path(__file__).resolve().parent.parent.parent / "vendor" / "lolstaticdata"
)
if str(_LOLSTATICDATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_LOLSTATICDATA_ROOT))

from lolstaticdata.common import utils as _lsd_utils
from lolstaticdata.common.utils import download_json, get_latest_patch_version

_http_get = _requests.get


def _download_page(url: str) -> str:
    """Fetch wiki HTML with a finite wait and explicit HTTP error handling."""
    response = _http_get(url, timeout=30)
    response.raise_for_status()
    return response.text


# Monkey-patch download_soup on Windows: the original builds cache filenames
# via url.replace("/", "@") but never strips colons, which are illegal in
# Windows filenames.  download_json already does url.replace(":", ""), so
# we apply the same fix here.
if sys.platform == "win32":
    _orig_download_soup = _lsd_utils.download_soup

    def _win_download_soup(
        url: str,
        use_cache: bool = True,
        dir: str = "__cache__",
    ) -> str:
        import os as _os
        from bs4 import BeautifulSoup as _BS

        directory = _os.path.abspath(
            _os.path.join(
                _os.path.dirname(_os.path.realpath(_lsd_utils.__file__)), "../.."
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
            html = _download_page(url)
            if use_cache:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(html)

        soup = _BS(html, "lxml")
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

    _lsd_utils.download_soup = _win_download_soup

from lolstaticdata.champions.pull_champions_wiki import LolWikiDataHandler
from lolstaticdata.champions.pull_champions_dragons import get_ability_url
from lolstaticdata.champions.__main__ import get_ability_filenames

from .data_fetcher import DEFAULT_DATA_DIR, _read_cache
from .data_registry import write_runtime_cache
from .item_source import merge_item_sources
from .rune_parser import parse_effects, rune_payload

# Only one update can run at a time
_update_lock = threading.Lock()

# Keystone runes, in wiki path order. The roster changes only on major
# season reworks; each entry maps to one Template:Rune data <name> page.
KEYSTONE_NAMES: tuple[str, ...] = (
    # Precision
    "Press the Attack",
    "Lethal Tempo",
    "Fleet Footwork",
    "Conqueror",
    # Domination
    "Electrocute",
    "Dark Harvest",
    "Hail of Blades",
    # Sorcery
    "Summon Aery",
    "Arcane Comet",
    "Stormraider's Surge",
    "Deathfire Touch",
    # Resolve
    "Grasp of the Undying",
    "Aftershock",
    "Guardian",
    # Inspiration
    "Glacial Augment",
    "Unsealed Spellbook",
    "First Strike",
)

_RUNE_TEMPLATE_URL = (
    "https://wiki.leagueoflegends.com/en-us/Template:Rune_data_{name}?action=raw"
)
_RUNES_REFORGED_URL = (
    "http://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json"
)

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
        except Exception:
            pass  # Ability icons are non-critical

    champion_payload = json.loads(champion.__json__(ensure_ascii=False))
    champion_payload.pop("skins", None)
    champion_payload.pop("lore", None)
    champion_payload.pop("faction", None)

    return champion_payload


def _process_champions(
    latest_version: str,
) -> Generator[dict[str, Any], None, tuple[list[dict[str, Any]], list[str]]]:
    """Fetch and process all champion data from the League Wiki.

    Uses a two-phase approach:
      Phase 1 — bulk generator (fast).  If the generator crashes internally
        on a champion with unparseable wiki data, fall through to phase 2.
      Phase 2 — process each remaining champion individually via the
        ``target_champion`` parameter so one bad champion cannot block others.

    Yields progress events and returns (champions, skipped).
    """
    ddragon_champions = download_json(
        f"http://ddragon.leagueoflegends.com/cdn/{latest_version}"
        f"/data/en_US/championFull.json"
    )["data"]

    total_champions = len(ddragon_champions)
    yield {
        "phase": "champions",
        "status": "Processing champions...",
        "current": 0,
        "total": total_champions,
    }

    champions: list[dict[str, Any]] = []
    processed = 0
    skipped: list[str] = []
    processed_keys: set[str] = set()

    # ------------------------------------------------------------------
    # Phase 1: Bulk generator (fastest — single wiki download + parse)
    # ------------------------------------------------------------------
    bulk_crashed = False
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
                processed_keys.add(champion_key)

                if champion_key not in ddragon_champions:
                    continue

                ddragon_champion = ddragon_champions[champion_key]
                payload = _build_champion_payload(
                    champion,
                    latest_version,
                    ddragon_champion,
                )
                champions.append(payload)
                processed += 1
                yield {
                    "phase": "champions",
                    "status": f"Processed {champion.name}",
                    "current": processed,
                    "total": total_champions,
                    "champion": champion.name,
                }
            except Exception as exc:
                name = getattr(champion, "name", "Unknown")
                processed_keys.add(getattr(champion, "key", name))
                skipped.append(name)
                processed += 1
                yield {
                    "phase": "champions",
                    "status": f"Skipped {name}: {exc}",
                    "current": processed,
                    "total": total_champions,
                    "champion": name,
                }
    except Exception:
        # The generator itself crashed (wiki parse error for a champion).
        # Everything yielded so far is fine; fall through to phase 2.
        bulk_crashed = True
        skipped.append("Unknown (wiki parse error)")
        processed += 1
        yield {
            "phase": "champions",
            "status": "Bulk parse error — switching to individual mode",
            "current": processed,
            "total": total_champions,
        }

    # ------------------------------------------------------------------
    # Phase 2: Process remaining champions one-by-one (resilient but
    #          slower since each call re-parses the cached wiki page).
    # ------------------------------------------------------------------
    if bulk_crashed:
        remaining_keys = [key for key in ddragon_champions if key not in processed_keys]

        for champion_key in remaining_keys:
            try:
                single_handler = LolWikiDataHandler(
                    use_cache=True,
                    target_champion=champion_key,
                    process_stats=True,
                    process_abilities=True,
                    process_skins=False,
                )
                found = False
                for champion in single_handler.get_champions():
                    found = True
                    processed_keys.add(champion.key)
                    ddragon_champion = ddragon_champions[champion_key]
                    payload = _build_champion_payload(
                        champion,
                        latest_version,
                        ddragon_champion,
                    )
                    champions.append(payload)
                    processed += 1
                    yield {
                        "phase": "champions",
                        "status": f"Processed {champion.name}",
                        "current": processed,
                        "total": total_champions,
                        "champion": champion.name,
                    }
                if not found:
                    # Champion exists in ddragon but not in wiki data
                    processed += 1
            except Exception as exc:
                skipped.append(champion_key)
                processed += 1
                yield {
                    "phase": "champions",
                    "status": f"Skipped {champion_key}: {exc}",
                    "current": processed,
                    "total": total_champions,
                    "champion": champion_key,
                }

    return champions, skipped


def _wiki_item_table() -> dict[str, Any]:
    """Decode the Wiki's ``Module:ItemData/data`` table, keyed by item name.

    The generator reads the same page but keeps only the first description of
    each effect and drops mode availability entirely, so ``item_source`` needs
    the raw table to record what the cache would otherwise lose.
    """
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

    items_path = _LOLSTATICDATA_ROOT / "items.json"
    if items_path.exists():
        with open(items_path, "r", encoding="utf-8") as items_file:
            generated = json.load(items_file)
        return merge_item_sources(
            generated, _wiki_item_table(), _riot_item_descriptions()
        )
    return None


def refresh_item_sources(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    """Re-read the source tables into the tracked item cache.

    Maintenance path for ingestion fixes, the item counterpart of
    ``reparse_cached_rune_effects``: it re-merges mode availability, champion
    restriction, acquisition, and the complete effect branches without
    regenerating the whole cache, so an ingestion change reaches ``data/``
    without dragging unrelated patch churn along with it.
    """
    merged = merge_item_sources(
        _read_cache(data_dir, "items.json"),
        _wiki_item_table(),
        _riot_item_descriptions(),
    )
    write_runtime_cache(data_dir, "items.json", merged, source_version=latest_version, source_url="https://wiki.leagueoflegends.com/en-us/Item")
    return merged


def _rune_icon_map(latest_version: str) -> dict[str, str]:
    """Map rune names to Data Dragon icon URLs; icons are non-critical."""
    try:
        styles = download_json(_RUNES_REFORGED_URL.format(version=latest_version))
        return {
            perk["name"]: f"https://ddragon.leagueoflegends.com/cdn/img/{perk['icon']}"
            for style in styles
            for slot in style.get("slots", [])
            for perk in slot.get("runes", [])
        }
    except Exception:
        return {}


def _process_runes(
    latest_version: str,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Fetch and parse every keystone's wiki data template.

    Yields progress events and returns the ``data/runes.json`` payload.
    A keystone whose template fails to download is recorded with an
    ``error`` field instead of silently dropping from the roster.
    """
    icons = _rune_icon_map(latest_version)
    if not icons:
        yield {
            "phase": "runes",
            "status": "Warning: rune icons unavailable from Data Dragon",
        }
    runes: dict[str, Any] = {}
    for index, name in enumerate(KEYSTONE_NAMES, start=1):
        try:
            url = _RUNE_TEMPLATE_URL.format(name=name.replace(" ", "_"))
            wikitext = _download_page(url)
            runes[name] = rune_payload(name, wikitext, icon=icons.get(name, ""))
            status = f"Parsed {name}"
        except Exception as exc:
            runes[name] = {"name": name, "error": str(exc)}
            status = f"Failed {name}: {exc}"
        yield {
            "phase": "runes",
            "status": status,
            "current": index,
            "total": len(KEYSTONE_NAMES),
        }
    return runes


def update_rune_data() -> dict[str, Any]:
    """Runes-only refresh for maintenance (wiki rune-template fixes).

    Not wired to any route — patch day goes through ``update_data``,
    which covers runes alongside champions and items.
    """
    rune_generator = _process_runes(get_latest_patch_version())
    while True:
        try:
            next(rune_generator)
        except StopIteration as stop:
            runes = stop.value or {}
            break
    write_runtime_cache(DEFAULT_DATA_DIR, "runes.json", runes, source_url="https://wiki.leagueoflegends.com/en-us/Rune")
    return runes


def reparse_cached_rune_effects(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    """Recompute every cached rune's effects from its stored description.

    ``data/runes.json`` keeps each rune's verbatim template text, so a
    parser improvement can reach the cache deterministically and offline —
    no wiki pull, no unrelated patch-day diffs. Entries without a
    description (failed downloads) are left untouched.
    """
    runes = {
        name: dict(entry) for name, entry in _read_cache(data_dir, "runes.json").items()
    }
    for entry in runes.values():
        description = entry.get("description")
        if not description:
            continue
        effects, warnings = parse_effects(description)
        entry["effects"] = effects
        entry.pop("parse_warnings", None)
        if warnings:
            entry["parse_warnings"] = warnings
    write_runtime_cache(data_dir, "runes.json", runes, source_url="https://wiki.leagueoflegends.com/en-us/Rune")
    return runes


def update_data() -> Generator[dict[str, Any], None, None]:
    """Fetch fresh champion and item data from upstream sources.

    Yields progress dicts suitable for Server-Sent Events:
        phase: "init" | "champions" | "items" | "done" | "error"
        status: human-readable message
        current/total: numeric progress (champions phase)
        patch: patch version string (done phase)
    """
    if not _update_lock.acquire(blocking=False):
        yield {
            "phase": "error",
            "status": "An update is already in progress.",
        }
        return

    try:
        yield {"phase": "init", "status": "Fetching latest patch version..."}
        latest_version = get_latest_patch_version()
        yield {
            "phase": "init",
            "status": f"Latest patch: {latest_version}",
        }

        # --- Champions ---
        champion_gen = _process_champions(latest_version)
        champions: list[dict[str, Any]] = []
        skipped_champions: list[str] = []
        try:
            while True:
                event = next(champion_gen)
                yield event
        except StopIteration as stop:
            result = stop.value or ([], [])
            champions, skipped_champions = result

        champion_dict = {payload["key"]: payload for payload in champions}
        write_runtime_cache(DEFAULT_DATA_DIR, "champions.json", champion_dict, source_version=latest_version, source_url="https://wiki.leagueoflegends.com/en-us/List_of_champions")

        champ_status = f"Saved {len(champions)} champions"
        if skipped_champions:
            champ_status += (
                f" (skipped {len(skipped_champions)}:"
                f" {', '.join(skipped_champions)})"
            )
        yield {
            "phase": "champions",
            "status": champ_status,
            "current": len(champions),
            "total": len(champions),
        }

        # --- Items ---
        yield {
            "phase": "items",
            "status": "Updating items (this may take a moment)...",
        }

        items_data = _process_items()
        if items_data:
            write_runtime_cache(DEFAULT_DATA_DIR, "items.json", items_data, source_version=latest_version, source_url="https://wiki.leagueoflegends.com/en-us/Item")
            yield {
                "phase": "items",
                "status": f"Saved {len(items_data)} items",
            }
        else:
            yield {
                "phase": "items",
                "status": "Warning: no items data generated",
            }

        # --- Runes (keystones) ---
        yield {"phase": "runes", "status": "Updating keystone runes..."}
        runes = yield from _process_runes(latest_version)
        write_runtime_cache(DEFAULT_DATA_DIR, "runes.json", runes, source_url="https://wiki.leagueoflegends.com/en-us/Rune")
        failed_runes = [name for name, entry in runes.items() if "error" in entry]
        rune_status = f"Saved {len(runes) - len(failed_runes)} keystones"
        if failed_runes:
            rune_status += f" (failed: {', '.join(failed_runes)})"
        yield {"phase": "runes", "status": rune_status}

        yield {
            "phase": "done",
            "status": f"Update complete! Now on patch {latest_version}",
            "patch": latest_version,
            "champions_count": len(champions),
        }

    except Exception as exc:
        yield {
            "phase": "error",
            "status": f"Update failed: {exc}",
        }
    finally:
        _update_lock.release()
