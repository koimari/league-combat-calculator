"""Champion-owned healing derived from the reviewed ability packets.

Healing is deliberately kept separate from item/stat heuristics.  A result
contains post-mitigation, ordered damage events; this module applies only
champion-specific Wiki rules to those events and returns another ordered
ledger for the participant simulator.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def _leveling_value(ability: dict[str, Any], attribute: str, rank: int) -> float:
    """Read one sourced leveling attribute without inventing a fallback."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                return 0.0
            values = modifiers[0].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _ability(champion_data: dict[str, Any], slot: str) -> dict[str, Any]:
    entries = champion_data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _event_source(event: dict[str, Any]) -> str:
    return str(event.get("source_key", ""))


def _is_persistent(event: dict[str, Any]) -> bool:
    """Return the source-certified persistent/periodic damage boundary.

    The engine's own source keys are stable public receipts for these rows;
    no damage amount or champion archetype is guessed here.
    """
    source = _event_source(event).lower()
    return (
        source.startswith("burn_")
        or source.startswith("stacking_dot_")
        or "tibbers_aura" in source
        or source.startswith("immolate_")
    )


def _attributed_events(
    events: Iterable[dict[str, Any]], predicate,
) -> list[dict[str, Any]]:
    return [event for event in events if predicate(_event_source(event), event)]


def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return sourced self-heal events in the engine's event order.

    Only champion packets with an explicit Wiki formula are handled.  An
    unsupported champion therefore returns an empty list instead of a role or
    archetype estimate.
    """
    name = str(champion_data.get("name", ""))
    healing: list[dict[str, Any]] = []

    if name == "Aatrox":
        # Deathbringer Stance: heals for the post-mitigation bonus damage.
        passive_events = _attributed_events(
            damage_events,
            lambda source, _event: "passive" in source.lower(),
        )
        # The reviewed packet says E healing is 16% + 1.1% per 100 bonus HP.
        e_description = " ".join(
            effect.get("description", "")
            for effect in _ability(champion_data, "E").get("effects", [])
        )
        ratio_match = re.search(
            r"heals for\s+(\d+(?:\.\d+)?)%\s*\(\+\s*(\d+(?:\.\d+)?)%\s*per\s*100\s*bonus health",
            e_description,
            flags=re.IGNORECASE,
        )
        base_ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
        per_100 = float(ratio_match.group(2)) / 100.0 if ratio_match else 0.0
        e_ratio = base_ratio + per_100 * (
            float(champion_stats.get("bonus_health", 0.0)) / 100.0
        )
        r_rank = int(ability_damages.get("R", {}).get("rank", 0) or 0)
        r_inc = _leveling_value(_ability(champion_data, "R"), "Increased Healing", r_rank)
        healing_amp = 1.0 + r_inc / 100.0 if r_rank > 0 else 1.0

        for event in passive_events:
            amount = max(0.0, float(event.get("damage", 0.0))) * healing_amp
            if amount > 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Deathbringer Stance",
                        "kind": "champion_passive",
                    }
                )

        # E's passive excludes persistent damage; it is post-mitigation damage
        # dealt to champions, then amplified by R.  Damage is already ordered
        # and mitigated by this point.
        for event in damage_events:
            if _is_persistent(event):
                continue
            amount = max(0.0, float(event.get("damage", 0.0))) * e_ratio * healing_amp
            if amount > 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Umbral Dash",
                        "kind": "champion_passive",
                    }
                )

    elif name == "Ambessa":
        r_rank = int(ability_damages.get("R", {}).get("rank", 0) or 0)
        ratio = _leveling_value(_ability(champion_data, "R"), "Healing Percentage", r_rank)
        # Public Execution heals from post-mitigation active ability damage.
        if ratio > 0:
            for event in damage_events:
                source = _event_source(event)
                if source not in {"Q", "Q2", "W", "E", "R"}:
                    continue
                amount = max(0.0, float(event.get("damage", 0.0))) * ratio / 100.0
                if amount > 0:
                    healing.append(
                        {
                            "time": float(event.get("time", 0.0)),
                            "amount": amount,
                            "source": "Public Execution",
                            "kind": "champion_passive",
                        }
                    )

    return sorted(healing, key=lambda event: (event["time"], event["source"]))
