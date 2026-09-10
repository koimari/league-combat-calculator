"""How many ranks a kit authored, and the ranks a roster card may ask for at a level."""

from collections.abc import Mapping
from typing import Any

from .champions.skill_orders import get_ability_rank


def _ability_max_rank(champion_data: Mapping[str, Any], slot: str) -> int:
    """Read the authored rank cardinality, including six-rank kits such as Jayce."""
    entries = champion_data.get("abilities", {}).get(slot, [])
    maximum = 0
    for ability in entries:
        if not isinstance(ability, Mapping):
            continue
        for effect in ability.get("effects", []):
            for leveling in effect.get("leveling", []):
                for modifier in leveling.get("modifiers", []):
                    maximum = max(maximum, len(modifier.get("values", [])))
    if maximum:
        return maximum
    return 3 if slot == "R" else 5


def _validate_ability_ranks(
    champion_data: Mapping[str, Any],
    level: int,
    supplied: Mapping[str, int],
    *,
    field: str,
) -> None:
    """Validate manual roster ranks; omitted ranks stay sourced level defaults."""
    if not supplied:
        return
    name = str(champion_data.get("name", ""))
    effective = {
        slot: int(supplied.get(slot, get_ability_rank(slot, level, name)))
        for slot in ("Q", "W", "E", "R")
    }
    for slot, rank in effective.items():
        maximum = _ability_max_rank(champion_data, slot)
        if rank < 0 or rank > maximum:
            raise ValueError(
                f"{field}.{slot} rank {rank} exceeds the authored maximum {maximum}"
            )
        if slot == "R":
            minimum_level = (0, 6, 11, 16)[min(rank, 3)]
        else:
            minimum_level = max(1, 2 * rank - 1) if rank else 0
        if rank and level < minimum_level:
            raise ValueError(
                f"{field}.{slot} rank {rank} requires champion level {minimum_level}"
            )
    if sum(effective.values()) > min(level, 18):
        raise ValueError(
            f"{field} spends more skill points than champion level {level} allows"
        )
