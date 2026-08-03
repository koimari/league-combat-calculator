"""Sourced healing-reduction triggers for the coupled combat timeline."""

from __future__ import annotations

from typing import Any, Iterable

from .item_source import effect_text

# The cached item packets describe the trigger and three-second window.  The
# patch-wide Grievous Wounds rule supplies the current 40% reduction.
GRIEVOUS_WOUNDS_FACTOR = 0.60
GRIEVOUS_WOUNDS_DURATION = 3.0


def _trigger_damage_types(text: str) -> frozenset[str]:
    lowered = text.lower()
    if "grievous wounds" not in lowered or "inflict" not in lowered:
        return frozenset()
    damage_types: set[str] = set()
    if "physical damage" in lowered:
        damage_types.add("physical")
    if "magic damage" in lowered:
        damage_types.add("magic")
    return frozenset(damage_types)


def healing_reduction_profiles(
    items: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return exact anti-heal trigger packets from cached Wiki text.

    A packet is accepted only when both the Grievous Wounds marker and its
    damage-type trigger are present, so ambiguous effects fail closed.
    """
    profiles: list[dict[str, Any]] = []
    for item in items:
        item_name = str(item.get("name", ""))
        for passive in item.get("passives") or ():
            damage_types = _trigger_damage_types(effect_text(passive))
            if not damage_types:
                continue
            profiles.append(
                {
                    "item": item_name,
                    "source": str(passive.get("name") or "Grievous Wounds"),
                    "damage_types": damage_types,
                    "factor": GRIEVOUS_WOUNDS_FACTOR,
                    "duration": GRIEVOUS_WOUNDS_DURATION,
                }
            )
    return tuple(profiles)


def matching_healing_reduction(
    profiles: Iterable[dict[str, Any]],
    damage_type: str,
) -> tuple[dict[str, Any], ...]:
    """Return profiles whose Wiki trigger includes *damage_type*."""
    return tuple(
        profile
        for profile in profiles
        if damage_type in profile.get("damage_types", ())
    )
