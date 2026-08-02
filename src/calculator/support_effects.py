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
    ability_ranks: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return explicit shield/heal packets and their sourced cast times.

    The timeline has no player cursor/target selection, so packets carry a
    sourced target scope for the coupled resolver to apply deterministically:
    ``self``, one selected teammate, or all selected teammates.  A missing
    scope is never silently treated as an area effect.
    """
    effects: list[dict[str, Any]] = []
    requested_ranks = ability_ranks or {}
    for slot in ("Q", "W", "E", "R"):
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        default_rank = get_ability_rank(slot, level, champion_data.get("name", ""))
        requested_rank = requested_ranks.get(slot, default_rank)
        try:
            rank = max(0, int(requested_rank))
        except (TypeError, ValueError):
            rank = default_rank
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
            for marker in (
                "shields herself",
                "shields himself",
                "shields themselves",
                "shield themselves",
                "heals herself",
                "heals himself",
                "heals themselves",
                "to herself",
                "to himself",
                "to themselves",
            )
        )
        all_teammates = any(
            marker in description
            for marker in (
                "all allied champions",
                "all allied units",
                "nearby allied champions",
                "nearby allied units",
                "nearby allies",
                "all allies",
            )
        )
        target_scope = "self" if target_self else "all_teammates" if all_teammates else "one_teammate"
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
                            "target_scope": target_scope,
                            "rank": rank,
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
                            "target_scope": target_scope,
                            "rank": rank,
                        }
                    )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))
