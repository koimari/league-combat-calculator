"""Compatibility exports for the shared healing helper layer.

Champion-specific healing resolvers now live beside their damage packets in
``src/calculator/champions/<name>.py``.  This module keeps older private
imports working while the public entrypoint and the champion modules move to
the typed ownership boundary.
"""

# This module preserves private helper imports for older callers.
# pylint: disable=unused-import

from __future__ import annotations

from typing import Any

from .healing_helpers import (
    _ability,
    _attributed_events,
    _cast_slot_times,
    _event_source,
    _heal_from_damage,
    _is_persistent,
    _leveling_flat_at_level,
    _leveling_modifier,
    _leveling_ratio,
    _leveling_value,
    _missing_health_scaled_heal,
    _rank,
    _taric_starlights_touch,
    _trigger_fields,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)  # pylint: disable=unused-import

HEALING_RULE_CHAMPIONS = frozenset(
    {
        "Aatrox",
        "Ahri",
        "Alistar",
        "Ambessa",
        "Darius",
        "Warwick",
        "Dr. Mundo",
        "Ekko",
        "Fiora",
        "Gangplank",
        "Garen",
        "Gragas",
        "Gwen",
        "Illaoi",
        "Irelia",
        "Karma",
        "Nami",
        "Nilah",
        "Renekton",
        "Soraka",
        "Briar",
        "Vladimir",
        "Kayle",
        "Kha'Zix",
        "Kindred",
        "Lissandra",
        "Master Yi",
        "Nidalee",
        "Naafiri",
        "Senna",
        "Smolder",
        "Sylas",
        "Tahm Kench",
        "Tryndamere",
        "Volibear",
        "Zac",
        "Rakan",
        "Sona",
        "Janna",
        "Milio",
        "Taric",
        "Zaahen",
        "Aphelios",
        "Camille",
        "Fiddlesticks",
        "Hecarim",
        "Swain",
        "Trundle",
        "Xin Zhao",
        "Yorick",
        "Udyr",
        "Yuumi",
        "Morgana",
        "Talon",
        "Nunu & Willump",
        "Shyvana",
        "Nasus",
    }
)

GREY_HEALTH_RULE_CHAMPIONS = frozenset(
    {"Pyke", "Rengar", "Tahm Kench", "Mordekaiser", "Locke"}
)


def _legacy_derive_self_healing(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    """Fail closed for callers that still import the retired dispatcher."""
    raise RuntimeError(
        "champion healing must be resolved by its champion module declaration"
    )
