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
    "Ezreal": "ezreal",
    "Galio": "galio",
    "Gnar": "gnar",
    "Jarvan IV": "jarvan_iv",
    "Jayce": "jayce",
    "Kai'Sa": "kaisa",
    "Kog'Maw": "kogmaw",
    "Lissandra": "lissandra",
    "Orianna": "orianna",
    "Rakan": "rakan",
    "Shen": "shen",
    "Soraka": "soraka",
    "Syndra": "syndra",
    "Vayne": "vayne",
    "Vi": "vi",
    "Ziggs": "ziggs",
}


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
    revision-pinned ``SOURCES`` beside their ``SLOTS``. Champions without a
    module have none of these — the generic path takes no options.

    Returns:
        ``{"options": [...], "assumptions": [...], "sources": [...]}``
        (JSON-safe). A source row contains ``label``, ``url``,
        ``revision_id``, and ``revision_timestamp``.
    """
    module_name = _CHAMPION_MODULES.get(champion_name)
    if module_name is None:
        return {"options": [], "assumptions": [], "sources": []}
    module = importlib.import_module(f".{module_name}", package=__name__)
    result: dict[str, Any] = {
        "options": list(module.OPTIONS),
        "assumptions": list(module.ASSUMPTIONS),
        "sources": list(getattr(module, "SOURCES", [])),
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

    The shape /api/config serves: champions absent from the map have no
    options, assumptions, or sources (the frontend shows its generic
    "no special options" placeholder).
    """
    result = {}
    for name in _CHAMPION_MODULES:
        meta = get_champion_options_meta(name)
        if meta["options"] or meta["assumptions"] or meta["sources"]:
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
