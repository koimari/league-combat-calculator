"""Opt-in outgoing ally effects with explicit sourced formulas."""

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class AllyStatEffect:
    """One ally effect applied to the champion being calculated."""

    source: str
    ability_power: float = 0.0
    ability_haste: float = 0.0
    duration: float = 0.0
    assumption: str = ""


def _staff_of_flowing_water(item: dict[str, Any]) -> AllyStatEffect | None:
    for passive in item.get("passives", []):
        if passive.get("name") != "Rapids":
            continue
        stats = passive.get("stats", {})
        duration_match = re.search(
            r"for\s+(\d+(?:\.\d+)?)\s+seconds?",
            str(passive.get("effects", "")),
            flags=re.IGNORECASE,
        )
        if duration_match is None:
            return None
        return AllyStatEffect(
            source="Staff of Flowing Water — Rapids",
            ability_power=float(stats.get("abilityPower", {}).get("flat", 0.0)),
            ability_haste=float(stats.get("abilityHaste", {}).get("flat", 0.0)),
            duration=float(duration_match.group(1)),
            assumption="The ally healed or shielded the attacker immediately before combat.",
        )
    return None


def resolve_ally_stat_effects(
    items: tuple[dict[str, Any], ...],
) -> tuple[AllyStatEffect, ...]:
    """Compile every supported outgoing effect in an enabled ally build."""
    effects: list[AllyStatEffect] = []
    for item in items:
        if item.get("name") == "Staff of Flowing Water":
            effect = _staff_of_flowing_water(item)
            if effect is not None:
                effects.append(effect)
    return tuple(effects)


def combine_ally_stat_effects(
    effects: tuple[AllyStatEffect, ...],
) -> dict[str, float]:
    """Combine active external stats into the pipeline input shape."""
    return {
        "ability_power": sum(effect.ability_power for effect in effects),
        "ability_haste": sum(effect.ability_haste for effect in effects),
    }
