"""Champion ability registry.

Every champion in the pinned Wiki cache has a dedicated importable module.
Long-lived hand-authored modules remain authoritative for mechanics that need
stateful event timelines; the generated modules are explicit, source-pinned
packet modules for the remaining kits.  There is no runtime archetype or
implicit generic champion registration in the reviewed surface.
"""

import json
import importlib
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .generic import GENERIC_SLOTS, parse_abilities as parse_generic_abilities

# Map display name -> module name within this package.
# Hand-authored modules own mechanics that need stateful timelines. The
# generated packet modules below provide the same dedicated-module contract
# for every other cached champion; no champion is routed through an archetype
# parser at runtime.
_CUSTOM_CHAMPION_MODULES: dict[str, str] = {
    "Aatrox": "aatrox",
    "Ahri": "ahri",
    "Akali": "akali",
    "Akshan": "akshan",
    "Alistar": "alistar",
    "Ambessa": "ambessa",
    "Amumu": "amumu",
    "Aphelios": "aphelios",
    "Anivia": "anivia",
    "Annie": "annie",
    "Ashe": "ashe",
    "Aurelion Sol": "aurelion_sol",
    "Aurora": "aurora",
    "Azir": "azir",
    "Bard": "bard",
    "Bel'Veth": "belveth",
    "Blitzcrank": "blitzcrank",
    "Brand": "brand",
    "Braum": "braum",
    "Briar": "briar",
    "Caitlyn": "caitlyn",
    "Camille": "camille",
    "Cassiopeia": "cassiopeia",
    "Cho'Gath": "chogath",
    "Corki": "corki",
    "Darius": "darius",
    "Diana": "diana",
    "Dr. Mundo": "dr_mundo",
    "Draven": "draven",
    "Ezreal": "ezreal",
    "Ekko": "ekko",
    "Elise": "elise",
    "Evelynn": "evelynn",
    "Fiddlesticks": "fiddlesticks",
    "Fiora": "fiora",
    "Fizz": "fizz",
    "Gangplank": "gangplank",
    "Garen": "garen",
    "Gragas": "gragas",
    "Graves": "graves",
    "Gwen": "gwen",
    "Hecarim": "hecarim",
    "Heimerdinger": "heimerdinger",
    "Hwei": "hwei",
    "Illaoi": "illaoi",
    "Irelia": "irelia",
    "Ivern": "ivern",
    "Janna": "janna",
    "Jax": "jax",
    "Jhin": "jhin",
    "K'Sante": "ksante",
    "Karma": "karma",
    "Kassadin": "kassadin",
    "Katarina": "katarina",
    "Kayle": "kayle",
    "Kayn": "kayn",
    "Kennen": "kennen",
    "Kha'Zix": "khazix",
    "Kindred": "kindred",
    "Kled": "kled",
    "LeBlanc": "leblanc",
    "Lee Sin": "lee_sin",
    "Leona": "leona",
    "Lillia": "lillia",
    "Locke": "locke",
    "Lucian": "lucian",
    "Lulu": "lulu",
    "Lux": "lux",
    "Malphite": "malphite",
    "Malzahar": "malzahar",
    "Maokai": "maokai",
    "Master Yi": "master_yi",
    "Mel": "mel",
    "Milio": "milio",
    "Miss Fortune": "miss_fortune",
    "Mordekaiser": "mordekaiser",
    "Morgana": "morgana",
    "Naafiri": "naafiri",
    "Nami": "nami",
    "Nasus": "nasus",
    "Nautilus": "nautilus",
    "Neeko": "neeko",
    "Nidalee": "nidalee",
    "Nilah": "nilah",
    "Nocturne": "nocturne",
    "Nunu & Willump": "nunu_willump",
    "Olaf": "olaf",
    "Pantheon": "pantheon",
    "Poppy": "poppy",
    "Pyke": "pyke",
    "Quinn": "quinn",
    "Rammus": "rammus",
    "Rek'Sai": "reksai",
    "Rell": "rell",
    "Renata Glasc": "renata_glasc",
    "Renekton": "renekton",
    "Rengar": "rengar",
    "Riven": "riven",
    "Rumble": "rumble",
    "Ryze": "ryze",
    "Samira": "samira",
    "Sejuani": "sejuani",
    "Senna": "senna",
    "Seraphine": "seraphine",
    "Sett": "sett",
    "Shaco": "shaco",
    "Singed": "singed",
    "Sion": "sion",
    "Sivir": "sivir",
    "Skarner": "skarner",
    "Smolder": "smolder",
    "Galio": "galio",
    "Gnar": "gnar",
    "Jarvan IV": "jarvan_iv",
    "Jayce": "jayce",
    "Jinx": "jinx",
    "Kalista": "kalista",
    "Kai'Sa": "kaisa",
    "Karthus": "karthus",
    "Kog'Maw": "kogmaw",
    "Lissandra": "lissandra",
    "Orianna": "orianna",
    "Ornn": "ornn",
    "Qiyana": "qiyana",
    "Rakan": "rakan",
    "Shen": "shen",
    "Soraka": "soraka",
    "Syndra": "syndra",
    "Shyvana": "shyvana",
    "Taliyah": "taliyah",
    "Tahm Kench": "tahm_kench",
    "Vayne": "vayne",
    "Vi": "vi",
    "Wukong": "wukong",
    "Ziggs": "ziggs",
}


def _wiki_cache_names() -> tuple[str, ...]:
    """Read display names from the checked-in Wiki snapshot.

    Keeping generated registration derived from the same cache that feeds
    the browser prevents key/display-name drift (e.g. ``K'Sante`` and
    ``Nunu & Willump``).  A missing cache is treated conservatively: custom
    modules remain available, while deployment health can surface the missing
    ingestion artifact instead of inventing names.
    """
    path = Path(__file__).resolve().parents[3] / "data" / "champions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    names = {
        str(champion.get("name", "")).strip()
        for champion in payload.values()
        if isinstance(champion, dict) and str(champion.get("name", "")).strip()
    }
    return tuple(sorted(names))


# Explicit generated-module registrations for every cached champion that does
# not yet have a hand-authored stateful module. Each packet is a real module
# import target, not an implicit runtime archetype fallback.
_GENERATED_CHAMPION_MODULES: dict[str, str] = {
    name: "generated." + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    for name in _wiki_cache_names()
    if name not in _CUSTOM_CHAMPION_MODULES
}
_ENGINE_CHAMPION_MODULES: dict[str, str] = {
    **_CUSTOM_CHAMPION_MODULES,
    **_GENERATED_CHAMPION_MODULES,
}
# Compatibility alias for callers that used the old internal name. It does
# not indicate a runtime generic/archetype path.
_GENERIC_CHAMPION_MODULES = _GENERATED_CHAMPION_MODULES
# Public/internal callers historically imported ``_CHAMPION_MODULES``. Keep
# that symbol, but make it the complete engine registration map now that every
# cached champion has a dedicated packet module. Certification is exposed
# separately through ``reviewed_champion_names``.
_CHAMPION_MODULES: dict[str, str] = _ENGINE_CHAMPION_MODULES

# Resolved module ``parse_abilities`` callables — the import system already
# caches modules, but the coupled optimizer dispatches thousands of parses
# per request, so skip even the ``import_module`` lookup after the first.
_MODULE_PARSERS: dict[str, Any] = {}


@lru_cache(maxsize=1)
def _reviewed_packet_sources() -> dict[str, tuple[dict[str, Any], ...]]:
    """Load revision receipts from the tracked reviewed-packet manifest.

    Hand-authored modules may carry their own ``SOURCES`` rows.  The checked-in
    packet manifest is the authoritative fallback for modules that do not: it
    is local, patch-pinned data and must never trigger a network request.  A
    malformed or unavailable manifest fails closed to an empty mapping.
    """
    path = Path(__file__).resolve().parents[3] / "static" / "reviewed-packets.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    champions = payload.get("champions") if isinstance(payload, dict) else None
    if not isinstance(champions, dict):
        return {}

    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for name, entry in champions.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        rows = entry.get("sources")
        if not isinstance(rows, list):
            continue
        valid: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = row.get("label")
            url = row.get("url")
            revision_id = row.get("revision_id")
            revision_timestamp = row.get("revision_timestamp")
            if (
                not isinstance(label, str)
                or not label
                or not isinstance(url, str)
                or not url
                or isinstance(revision_id, bool)
                or not isinstance(revision_id, int)
                or revision_id <= 0
                or not isinstance(revision_timestamp, str)
                or not revision_timestamp
            ):
                continue
            valid.append(
                {
                    "label": label,
                    "url": url,
                    "revision_id": revision_id,
                    "revision_timestamp": revision_timestamp,
                }
            )
        if valid:
            result[name] = tuple(valid)
    return result


# Option keys owned by the pipeline — never user input, never a module
# OPTIONS declaration (tests/test_champion_options.py enforces the
# no-collision rule). Injected by ``pipeline.run_fight`` for timed
# fights; absent in one-rotation mode and direct parse calls, where
# modules fall back to their per-cast models.
# ``fight_duration_seconds``: the fight window, so duration-driven
# mechanics (e.g. Aurelion Sol's continuous Q channel) can scale with it.
# ``auto_attack_uptime``: the fight's auto uptime, so auto-timeline
# mechanics (e.g. Braum's passive stack cycle) walk the same auto
# cadence (attack_speed x uptime) the fight engine schedules.
RESERVED_OPTION_KEYS = frozenset({"fight_duration_seconds", "auto_attack_uptime"})


def parse_abilities(
    champion_name: str,
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
    champion_options: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse abilities for any champion.

    Dispatches to a dedicated reviewed module. Unknown synthetic fixtures keep
    the legacy generic parser contract, but cached champions never fall back
    to it.

    Args:
        champion_name: Display name of the champion (e.g., "Ahri").
        champion_data: Raw champion data from the data fetcher.
        level: Champion level (1-18).
        total_ability_power: Total AP after items and multipliers.
        ability_ranks: Optional ability rank overrides.
        champion_stats: Champion's calculated stats (for AD/HP scaling).
        target_stats: Target stats (for %HP abilities).
        champion_options: Champion-specific options from the frontend
            (e.g., ``{"sweetspot": True}`` for Aatrox).

    Returns:
        Ability damage dictionary keyed by Q/W/E/R.
    """
    module_name = _CHAMPION_MODULES.get(champion_name)
    # A few internal pipeline fixtures intentionally rename the display name;
    # keep their legacy generic behavior without promoting fixture names to
    # the public registration manifest.
    if module_name is None:
        return parse_generic_abilities(
            champion_data,
            level,
            total_ability_power,
            ability_ranks=ability_ranks,
            champion_options=champion_options,
            champion_stats=champion_stats,
            target_stats=target_stats,
        )
    module_parse = _MODULE_PARSERS.get(module_name)
    if module_parse is None:
        module = importlib.import_module(f".{module_name}", package=__name__)
        module_parse = module.parse_abilities
        _MODULE_PARSERS[module_name] = module_parse
    return module_parse(
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_options=champion_options,
        champion_stats=champion_stats,
        target_stats=target_stats,
    )


def parse_champion_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
    champion_options: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse loaded champion data through its display-name dispatcher.

    Prefer this entry point when the cached champion object is already in
    hand. It prevents data keys such as ``KogMaw`` from accidentally bypassing
    the registered ``Kog'Maw`` module.
    """
    return parse_abilities(
        champion_data["name"],
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_stats=champion_stats,
        target_stats=target_stats,
        champion_options=champion_options,
    )


def get_champion_cast_order(champion_name: str) -> list[str] | None:
    """The champion's own rotation order, or ``None`` for the default.

    A module declares ``CAST_ORDER`` when the engine's
    ``(Q, Q2, W, E, R)`` misrepresents how the kit is actually used —
    Jayce transforms INTO Cannon stance and only then casts its
    abilities, so his R (and the resistance shred its empowered attack
    applies) has to be resolved before Q/W, not after them.

    Returns:
        The declared order, or ``None`` when the champion has no module
        or does not override the default.
    """
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return None
    module = importlib.import_module(f".{module_name}", package=__name__)
    declared = getattr(module, "CAST_ORDER", None)
    return list(declared) if declared else None


def get_champion_options_meta(champion_name: str) -> dict[str, Any]:
    """Return a champion's option/assumption metadata for the frontend.

    Registered modules declare ``OPTIONS`` (a list of option dicts:
    ``key``, ``type`` ("bool"/"int"/"float"), ``default``, ``label``,
    plus ``min``/``max``/``step`` for numeric inputs) and
    ``ASSUMPTIONS`` (prose strings shown in the UI), and optionally
    revision-pinned ``SOURCES`` beside their ``SLOTS``. Unknown synthetic
    fixtures without a module have no metadata.

    Returns:
        ``{"options": [...], "assumptions": [...], "sources": [...]}``
        (JSON-safe). A source row contains ``label``, ``url``,
        ``revision_id``, and ``revision_timestamp``.
    """
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return {"options": [], "assumptions": [], "sources": []}
    module = importlib.import_module(f".{module_name}", package=__name__)
    module_sources = list(getattr(module, "SOURCES", []))
    if not module_sources:
        module_sources = list(_reviewed_packet_sources().get(champion_name, ()))
    result: dict[str, Any] = {
        "options": list(module.OPTIONS),
        "assumptions": list(module.ASSUMPTIONS),
        "sources": module_sources,
    }
    supported_modes = getattr(module, "SUPPORTED_FIGHT_MODES", None)
    if supported_modes is not None:
        result["supported_fight_modes"] = list(supported_modes)
    return result


def get_comparison_curve_unavailable_reason(champion_name: str) -> str | None:
    """Why timed crossover windows are withheld for a champion, if at all."""
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return None
    module = importlib.import_module(f".{module_name}", package=__name__)
    reason = getattr(module, "COMPARISON_CURVE_UNAVAILABLE_REASON", None)
    return str(reason) if reason else None


def get_supported_fight_modes(champion_name: str) -> tuple[str, ...] | None:
    """Return a module's certified public fight modes, when restricted."""
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return None
    module = importlib.import_module(f".{module_name}", package=__name__)
    modes = getattr(module, "SUPPORTED_FIGHT_MODES", None)
    return tuple(str(mode) for mode in modes) if modes is not None else None


def get_unsupported_fight_mode_reason(champion_name: str) -> str | None:
    """Return the sourced fail-closed explanation for restricted modes."""
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return None
    module = importlib.import_module(f".{module_name}", package=__name__)
    reason = getattr(module, "UNSUPPORTED_FIGHT_MODE_REASON", None)
    return str(reason) if reason else None


def get_custom_cast_order_unavailable_reason(champion_name: str) -> str | None:
    """Explain why a module's certified cast sequence cannot be reordered."""
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return None
    module = importlib.import_module(f".{module_name}", package=__name__)
    reason = getattr(module, "CUSTOM_CAST_ORDER_UNAVAILABLE_REASON", None)
    return str(reason) if reason else None


def champion_options_meta_map() -> dict[str, dict[str, list]]:
    """Option, assumption, and source metadata for every champion with any.

    The shape /api/config serves: every cached champion can expose its
    options, assumptions, and source receipts.
    """
    result = {}
    for name in _CHAMPION_MODULES:
        meta = get_champion_options_meta(name)
        if meta["options"] or meta["assumptions"] or meta["sources"]:
            result[name] = meta
    return result


def registered_champion_names() -> list[str]:
    """Display names of all champions with a dedicated engine module.

    This is the runnable registration surface, not the certification surface.
    Generated packet modules remain registered so the calculator can expose a
    deterministic, fail-closed result while their full champion-specific
    mechanics are completed.
    """
    return sorted(_CHAMPION_MODULES)


def reviewed_champion_names() -> list[str]:
    """Display names whose modules passed the exact champion review gate.

    Hand-authored modules are the only modules that currently carry the exact
    stateful contract.  Generated packet modules deliberately stay out of
    this set until their full Wiki parent entry, all P/Q/W/E/R mechanics, and
    focused tests are complete.  Keeping this separate from
    :func:`registered_champion_names` prevents a generated file from being
    presented as a reviewed champion merely because it imports successfully.
    """
    return sorted(_CUSTOM_CHAMPION_MODULES)


def registered_engine_champion_names() -> list[str]:
    """Display names with an importable backend module, sorted.

    This is the complete runnable registration surface.  It is retained as a
    separate name for API compatibility with older clients.
    """
    return sorted(_ENGINE_CHAMPION_MODULES)


def engine_registration_kind(champion_name: str) -> str | None:
    """Return the public registration kind for one champion module.

    ``generated_packet`` is intentionally distinct from ``reviewed_module``.
    A generated packet is a deterministic runtime implementation, but its
    full champion-specific Wiki mechanics have not yet passed the exact
    module gate in issue #15.  The API can therefore keep the backend path
    available without claiming that the packet is reviewed.
    """
    if champion_name in _CUSTOM_CHAMPION_MODULES:
        return "reviewed_module"
    if champion_name in _GENERATED_CHAMPION_MODULES:
        return "generated_packet"
    return None


def is_champion_supported(champion_name: str) -> bool:
    """Check whether a champion has ability damage implemented.

    Returns True only for cached champions with a dedicated module. Unknown
    synthetic fixtures may still use the legacy fallback in ``parse_abilities``
    but are not advertised as supported.
    """
    return champion_name in _CHAMPION_MODULES
