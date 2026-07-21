"""Champion ability registry.

To add a new champion, use /add-champion or see the add-champion skill.
In short: create a module in this package, implement ``parse_abilities()``,
and register the champion name below.

Champions NOT in ``_CHAMPION_MODULES`` fall through to the slot-archetype
engine running ``GENERIC_SLOTS``, which reads ability data directly from
the JSON with classifier-driven auto-detection.
"""

import importlib
from typing import Any

from .engine import build_parser
from .slotlib import on_hit_auto, simple_damage

# Slot map for champions without a registered module: classifier-driven
# damage detection on Q/W/E/R (including in-slot on-hit passives) and
# on-hit auto-detection for the champion passive.
GENERIC_SLOTS = {
    "Q": simple_damage(),
    "W": simple_damage(),
    "E": simple_damage(),
    "R": simple_damage(),
    "P": on_hit_auto(),
}


# Map display name -> module name within this package.
# Only champions with unique mechanics that the generic parser cannot
# handle need entries here. All other champions use the generic parser.
_CHAMPION_MODULES: dict[str, str] = {
    "Aatrox": "aatrox",
    "Ahri": "ahri",
    "Akali": "akali",
    "Akshan": "akshan",
    "Alistar": "alistar",
    "Ambessa": "ambessa",
    "Amumu": "amumu",
    "Anivia": "anivia",
    "Annie": "annie",
    "Ashe": "ashe",
    "Gnar": "gnar",
    "Kog'Maw": "kogmaw",
    "Vayne": "vayne",
}


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

    Dispatches to a champion-specific module if one is registered,
    otherwise falls through to the generic JSON-based parser.

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
    if module_name is not None:
        module = importlib.import_module(f".{module_name}", package=__name__)
        return module.parse_abilities(
            champion_data,
            level,
            total_ability_power,
            ability_ranks,
            champion_options=champion_options,
            champion_stats=champion_stats,
            target_stats=target_stats,
        )

    # Fall through to the slot-archetype engine with the generic slot map.
    # Skill-order lookup uses the data's own name (matching the old
    # generic parser exactly — e.g. Singed's custom order).
    generic_parse = build_parser(GENERIC_SLOTS, champion_data.get("name", ""))
    return generic_parse(
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


def get_champion_options_meta(champion_name: str) -> dict[str, list]:
    """Return a champion's option/assumption metadata for the frontend.

    Registered modules declare ``OPTIONS`` (a list of option dicts:
    ``key``, ``type`` ("bool"/"int"/"float"), ``default``, ``label``,
    plus ``min``/``max``/``step`` for numeric inputs) and
    ``ASSUMPTIONS`` (prose strings shown in the UI) beside their
    ``SLOTS``. Champions without a module have neither — the generic
    path takes no options.

    Returns:
        ``{"options": [...], "assumptions": [...]}`` (JSON-safe).
    """
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return {"options": [], "assumptions": []}
    module = importlib.import_module(f".{module_name}", package=__name__)
    return {"options": list(module.OPTIONS), "assumptions": list(module.ASSUMPTIONS)}


def champion_options_meta_map() -> dict[str, dict[str, list]]:
    """Option/assumption metadata for every champion that has any.

    The shape /api/config serves: champions absent from the map have no
    options and no assumptions (the frontend shows its generic "no
    special options" placeholder).
    """
    result = {}
    for name in _CHAMPION_MODULES:
        meta = get_champion_options_meta(name)
        if meta["options"] or meta["assumptions"]:
            result[name] = meta
    return result


def registered_champion_names() -> list[str]:
    """Display names of champions with a custom module, sorted.

    The sanctioned external view of the registry (the golden snapshot
    iterates it); everyone else goes through ``parse_champion_abilities``.
    """
    return sorted(_CHAMPION_MODULES)


def is_champion_supported(champion_name: str) -> bool:  # noqa: ARG001
    """Check whether a champion has ability damage implemented.

    Returns True for all champions — the generic parser handles
    any champion with JSON data.
    """
    return True
