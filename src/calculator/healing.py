"""Shared healing entrypoint for the participant and fight pipelines.

Champion modules own their typed declarations. This module owns generic
ordering and receipt shape.
"""

from __future__ import annotations

import importlib
from typing import Any

from .champions import _CHAMPION_MODULES
from .champions.healing_contract import ChampionHealingRule
from .healing_helpers import _taric_starlights_touch as _LEGACY_TARIC_STARLIGHTS_TOUCH
from .healing_legacy import GREY_HEALTH_RULE_CHAMPIONS as _GREY_HEALTH_RULE_CHAMPIONS

GREY_HEALTH_RULE_CHAMPIONS = _GREY_HEALTH_RULE_CHAMPIONS
_taric_starlights_touch = _LEGACY_TARIC_STARLIGHTS_TOUCH


def _load_declarations() -> dict[str, ChampionHealingRule]:
    declarations: dict[str, ChampionHealingRule] = {}
    for champion_name, module_name in sorted(_CHAMPION_MODULES.items()):
        module = importlib.import_module(
            f".champions.{module_name}", package=__package__
        )
        declaration = getattr(module, "SELF_HEALING_RULE", None)
        if declaration is None:
            continue
        if not isinstance(declaration, ChampionHealingRule):
            raise RuntimeError(f"{module.__name__} must declare SELF_HEALING_RULE")
        if declaration.champion_name != champion_name:
            raise RuntimeError(
                f"{module.__name__} declares {declaration.champion_name!r}, "
                f"expected {champion_name!r}"
            )
        if declaration.resolver is None:
            raise RuntimeError(
                f"{module.__name__} must provide a champion-local healing resolver"
            )
        declarations[champion_name] = declaration
    return declarations


_HEALING_RULES = _load_declarations()
HEALING_RULE_CHAMPIONS = frozenset(_HEALING_RULES)


def derive_self_healing(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Return sorted self-healing receipts from the champion declaration."""
    champion_name = str(champion_data.get("name", ""))
    declaration = _HEALING_RULES.get(champion_name)
    if declaration is None:
        return []
    events = declaration.derive(
        champion_data,
        champion_stats,
        ability_damages,
        damage_events,
        cast_timeline,
        fight_duration_seconds,
    )
    return sorted(events, key=lambda event: (event["time"], event["source"]))
