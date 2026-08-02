"""Sourced ally-targeted shields/heals from champion ability packets."""

from __future__ import annotations

from typing import Any

from .champions.slotlib import extract_named
from .champions.skill_orders import get_ability_rank


def _ability(data: dict[str, Any], slot: str) -> dict[str, Any]:
    entries = data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _first_attribute(ability: dict[str, Any], names: tuple[str, ...]) -> str | None:
    available = {
        leveling.get("attribute", "")
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
    }
    return next((name for name in names if name in available), None)


def derive_ally_effects(
    champion_data: dict[str, Any],
    level: int,
    stats: dict[str, float],
    cast_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only explicit shield/heal packets and their sourced cast times."""
    effects: list[dict[str, Any]] = []
    for slot in ("Q", "W", "E", "R"):
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        rank = get_ability_rank(slot, level, champion_data.get("name", ""))
        if rank < 1:
            continue
        shield_attr = _first_attribute(ability, ("Shield Strength", "Shield"))
        heal_attr = _first_attribute(ability, ("Total Heal", "Heal", "Heal Per Tick"))
        if shield_attr is None and heal_attr is None:
            continue
        description = " ".join(
            str(effect.get("description", ""))
            for effect in ability.get("effects", [])
        ).lower()
        target_self = any(
            marker in description
            for marker in ("shields herself", "shields himself", "shields themselves", "shield themselves")
        )
        casts = [event for event in cast_timeline if event.get("slot") == slot]
        for cast in casts:
            if shield_attr is not None:
                amount = extract_named(ability, shield_attr, rank, stats, {})
                if amount > 0:
                    effects.append(
                        {
                            "time": float(cast.get("time", 0.0)),
                            "kind": "shield",
                            "amount": float(amount),
                            "source": f"{ability.get('name', slot)} · {shield_attr}",
                            "slot": slot,
                            "target_self": target_self,
                        }
                    )
            if heal_attr is not None:
                amount = extract_named(ability, heal_attr, rank, stats, {})
                # A per-tick entry is not a complete heal packet without its
                # authored duration/tick cadence; fail closed here rather than
                # multiplying a guessed number.
                if heal_attr == "Heal Per Tick":
                    continue
                if amount > 0:
                    effects.append(
                        {
                            "time": float(cast.get("time", 0.0)),
                            "kind": "heal",
                            "amount": float(amount),
                            "source": f"{ability.get('name', slot)} · {heal_attr}",
                            "slot": slot,
                            "target_self": False,
                        }
                    )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))
