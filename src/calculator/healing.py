"""Shared healing entrypoint for the participant and fight pipelines.

Champion modules own their typed declarations. This module owns generic
ordering and receipt shape: it walks the champion registry, demands a
resolver from every module that declares one, and sorts what they return.
The shared readers and the payment machinery a resolver uses live in
``healing_helpers``; no healing formula lives here.
"""

from __future__ import annotations

import importlib
from typing import Any

from .champions import _CHAMPION_MODULES
from .champions.healing_contract import ChampionHealingRule
from .trigger_stream import ChampionSlotOwner

# Grey-health champions whose self-heals are sourced from damage TAKEN
# (post-mitigation) stored as a grey pool, then paid back when the
# champion's active consumes it (Pyke P out-of-vision, Rengar W, Tahm
# Kench E out-of-combat, Mordekaiser W recast).  A champion module's
# resolver only sees its own OUTGOING events, so these receipts are
# authored by the participant timeline against its incoming ledger (the
# enemy -> main pair events) rather than by a declaration; the set names
# that pipeline branch and so lives here, beside the registry the same
# callers read.  Kled's Skaarl pool is a revive-boundary pattern
# (dismount/remount) documented in the Kled module, not authored as a heal.
GREY_HEALTH_RULE_CHAMPIONS = frozenset(
    {"Pyke", "Rengar", "Tahm Kench", "Mordekaiser", "Locke"}
)

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


def self_heal_rule_owner(champion_name: str) -> ChampionSlotOwner | None:
    """Who owns this champion's reviewed self-heal rule, or ``None``.  The
    registry answers without importing the champion package, which the leaf
    consuming this must not do."""
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
