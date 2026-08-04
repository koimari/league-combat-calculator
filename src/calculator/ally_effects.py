"""Opt-in outgoing ally effects with explicit sourced formulas."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from typing import Any

from .item_effects import flowing_water_bonus_ap
from .item_source import effect_text


@dataclass(frozen=True, slots=True)
class AllyStatEffect:
    """One ally effect applied to the champion being calculated."""

    source: str
    ability_power: float = 0.0
    ability_haste: float = 0.0
    duration: float = 0.0
    assumption: str = ""


def _required_flat_stat(
    passive: Mapping[str, Any], *, item_name: str, stat_name: str
) -> float:
    """Read one cached passive stat without silently converting omissions to zero."""
    stats = passive.get("stats")
    if not isinstance(stats, Mapping):
        raise ValueError(f"{item_name} Rapids is missing its cached stats mapping")
    stat = stats.get(stat_name)
    if not isinstance(stat, Mapping) or "flat" not in stat:
        raise ValueError(f"{item_name} Rapids is missing numeric {stat_name}.flat")
    value = stat["flat"]
    if isinstance(value, bool):
        raise ValueError(f"{item_name} Rapids {stat_name}.flat must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{item_name} Rapids {stat_name}.flat must be numeric"
        ) from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name} Rapids {stat_name}.flat must be finite")
    return parsed


def _staff_of_flowing_water(item: dict[str, Any]) -> AllyStatEffect | None:
    item_name = "Staff of Flowing Water"
    found = False
    for passive in item.get("passives", []):
        if not isinstance(passive, Mapping):
            raise ValueError(f"{item_name} Rapids passive must be a mapping")
        if passive.get("name") != "Rapids":
            continue
        found = True
        # AP is owned by the item-effects registry; the cached packet is still
        # validated so a partial source record cannot silently lose the ally
        # buff before the typed accessor is consulted.
        _required_flat_stat(passive, item_name=item_name, stat_name="abilityPower")
        ability_power = flowing_water_bonus_ap([item])
        ability_haste = _required_flat_stat(
            passive, item_name=item_name, stat_name="abilityHaste"
        )
        duration_match = re.search(
            r"for\s+(\d+(?:\.\d+)?)\s+seconds?",
            effect_text(passive),
            flags=re.IGNORECASE,
        )
        if duration_match is None:
            raise ValueError(f"{item_name} Rapids is missing numeric duration")
        try:
            duration = float(duration_match.group(1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{item_name} Rapids duration must be numeric") from exc
        if not math.isfinite(duration):
            raise ValueError(f"{item_name} Rapids duration must be finite")
        return AllyStatEffect(
            source="Staff of Flowing Water — Rapids",
            ability_power=ability_power,
            ability_haste=ability_haste,
            duration=duration,
            assumption="The ally healed or shielded the attacker immediately before combat.",
        )
    if not found:
        raise ValueError(f"{item_name} is missing its Rapids passive")
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
