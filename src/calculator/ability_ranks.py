"""How many ranks a kit authored, and the ranks a roster card may ask for at a level."""

from collections.abc import Mapping
from typing import Any

from .champions.skill_orders import get_ability_rank
from .rank_allocation import validate_manual_ranks


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
    try:
        validate_manual_ranks(name, level, effective)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc
