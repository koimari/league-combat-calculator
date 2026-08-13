"""Shared healing entrypoint for the participant and fight pipelines.

Champion modules own their typed declarations. This module owns generic
ordering and receipt shape. Formula migration stays behind the registry so
event output stays stable during the split.
"""

from __future__ import annotations

import importlib
from typing import Any

from .champions import _CHAMPION_MODULES
from .champions.healing_contract import ChampionHealingRule
from .healing_legacy import (
    GREY_HEALTH_RULE_CHAMPIONS as _GREY_HEALTH_RULE_CHAMPIONS,
    HEALING_RULE_CHAMPIONS as _DECLARED_HEALING_CHAMPIONS,
    _taric_starlights_touch as _LEGACY_TARIC_STARLIGHTS_TOUCH,
)
from .trigger_stream import ChampionSlotOwner

GREY_HEALTH_RULE_CHAMPIONS = _GREY_HEALTH_RULE_CHAMPIONS
_taric_starlights_touch = _LEGACY_TARIC_STARLIGHTS_TOUCH

# The declaration site a self-heal rule occupies in its champion module.
# ``ChampionSlotOwner`` names a champion and the slot that declares a
# mechanic; a reviewed self-heal rule spans a champion's whole kit — Aatrox
# drains from every damage source, Gangplank heals off a cast — and no
# declaration in the tree narrows it to one ability.  So the slot names the
# module symbol the rule is declared at, which is the site an auditor can
# open, rather than an ability letter somebody guessed.
SELF_HEAL_RULE_SLOT = "SELF_HEALING_RULE"


def _load_declarations() -> dict[str, ChampionHealingRule]:
    declarations: dict[str, ChampionHealingRule] = {}
    for champion_name in sorted(_DECLARED_HEALING_CHAMPIONS):
        module_name = _CHAMPION_MODULES.get(champion_name)
        if module_name is None:
            raise RuntimeError(f"no champion module for {champion_name!r}")
        module = importlib.import_module(
            f".champions.{module_name}", package=__package__
        )
        declaration = getattr(module, "SELF_HEALING_RULE", None)
        if not isinstance(declaration, ChampionHealingRule):
            raise RuntimeError(f"{module.__name__} must declare SELF_HEALING_RULE")
        if declaration.champion_name != champion_name:
            raise RuntimeError(
                f"{module.__name__} declares {declaration.champion_name!r}, "
                f"expected {champion_name!r}"
            )
        declarations[champion_name] = declaration
    return declarations


_HEALING_RULES = _load_declarations()
HEALING_RULE_CHAMPIONS = frozenset(_HEALING_RULES)


def self_heal_rule_owner(champion_name: str) -> ChampionSlotOwner | None:
    """Who owns this champion's reviewed self-heal rule, or ``None``.

    The registry's answer to the question every consumer of
    ``HEALING_RULE_CHAMPIONS`` was really asking, returned as the campaign's
    typed owner rather than as membership in a name set.  A caller deciding
    whether a narrowed fight result can still serve its readers gets a
    receipt naming the declaration site, not a boolean it would have to
    re-explain; and the registry that loads the declarations is the one thing
    that can answer without importing the champion package, which the leaf
    consuming this must not do.
    """
    if champion_name not in _HEALING_RULES:
        return None
    return ChampionSlotOwner(champion=champion_name, slot=SELF_HEAL_RULE_SLOT)


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
