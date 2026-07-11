"""Champion ability registry.

To add a new champion, use /add-champion or see the add-champion skill.
In short: create a module in this package, implement ``parse_abilities()``,
and register the champion name below.

Champions NOT in ``_CHAMPION_MODULES`` fall through to the generic parser,
which reads ability data directly from the JSON.
"""

import importlib
from typing import Any


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
            champion_data, level, total_ability_power, ability_ranks,
            champion_options=champion_options,
            champion_stats=champion_stats,
            target_stats=target_stats,
        )

    # Fall through to generic parser
    from .generic_parser import parse_abilities as generic_parse

    return generic_parse(
        champion_data, level, total_ability_power,
        ability_ranks=ability_ranks,
        champion_stats=champion_stats,
        target_stats=target_stats,
        champion_options=champion_options,
    )


def is_champion_supported(champion_name: str) -> bool:  # noqa: ARG001
    """Check whether a champion has ability damage implemented.

    Returns True for all champions — the generic parser handles
    any champion with JSON data.
    """
    return True
