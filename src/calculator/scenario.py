"""Typed champion loadouts for multi-champion combat scenarios.

The damage engine remains intentionally one attacker versus one target.  This
module composes that trusted path across a roster without weakening its
champion-specific rules or replacing item mechanics with generic estimates.
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping

from .data_fetcher import get_champion, get_item_by_name
from .item_effects import validate_item_input_options
from .stats import MAX_LEVEL, calculate_total_stats

MAX_ENEMIES = 5
MAX_ALLIES = 4
MAX_LOADOUT_ITEMS = 6


def _short_string(value: object, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    parsed = value.strip()
    if required and not parsed:
        raise ValueError(f"{field} is required")
    if len(parsed) > 100:
        raise ValueError(f"{field} must be at most 100 characters")
    return parsed


@dataclass(frozen=True, slots=True)
class ChampionLoadout:
    """One champion, their level, and the items that contribute stats."""

    champion: str
    level: int
    items: tuple[str, ...] = ()
    boots: str = ""
    item_options: dict[str, dict[str, int]] = dataclass_field(default_factory=dict)

    @classmethod
    def from_request(cls, value: object, *, field: str) -> "ChampionLoadout":
        """Parse one public request object with strict, bounded fields."""
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")

        champion = _short_string(
            value.get("champion", ""), f"{field}.champion", required=True
        )
        level = value.get("level", 1)
        if isinstance(level, bool) or not isinstance(level, int):
            raise ValueError(f"{field}.level must be an integer")
        if not 1 <= level <= MAX_LEVEL:
            raise ValueError(f"{field}.level must be between 1 and {MAX_LEVEL}")

        raw_items = value.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError(f"{field}.items must be a list")
        if len(raw_items) > MAX_LOADOUT_ITEMS:
            raise ValueError(
                f"{field}.items may contain at most {MAX_LOADOUT_ITEMS} entries"
            )
        items = tuple(
            _short_string(item, f"{field}.items entries", required=True)
            for item in raw_items
        )
        boots = _short_string(value.get("boots", ""), f"{field}.boots")
        item_options = validate_item_input_options(value.get("item_options"))

        equipped_names = (*items, *((boots,) if boots else ()))
        if len(set(equipped_names)) != len(equipped_names):
            raise ValueError(f"{field} must not contain duplicate items")

        return cls(
            champion=champion,
            level=level,
            items=items,
            boots=boots,
            item_options=item_options,
        )

    def resolve(self) -> "ResolvedLoadout":
        """Resolve cached Wiki data and calculate the complete stat matrix."""
        champion_data = get_champion(self.champion)
        item_names = (*((self.boots,) if self.boots else ()), *self.items)
        item_data = tuple(get_item_by_name(name) for name in item_names)
        stats = calculate_total_stats(
            champion_data,
            self.level,
            list(item_data),
            item_options=self.item_options,
        )
        return ResolvedLoadout(
            request=self,
            champion_data=champion_data,
            item_data=item_data,
            stats=stats,
        )


@dataclass(frozen=True, slots=True)
class ResolvedLoadout:
    """A loadout joined to locally cached champion/item data and final stats."""

    request: ChampionLoadout
    champion_data: dict[str, Any]
    item_data: tuple[dict[str, Any], ...]
    stats: dict[str, float]

    def public_summary(self) -> dict[str, Any]:
        """Return the UI-safe identity, source images, build, and stat matrix."""
        return {
            "champion": self.champion_data["name"],
            "icon": self.champion_data.get("icon", ""),
            "level": self.request.level,
            "items": [item["name"] for item in self.item_data],
            "item_icons": [item.get("icon", "") for item in self.item_data],
            "item_options": dict(self.request.item_options),
            "stats": dict(self.stats),
        }


def parse_roster(
    data: Mapping[str, object], key: str, *, maximum: int
) -> tuple[ChampionLoadout, ...]:
    """Parse one bounded roster while rejecting duplicate champions."""
    raw_roster = data.get(key, [])
    if not isinstance(raw_roster, list):
        raise ValueError(f"{key} must be a list")
    if len(raw_roster) > maximum:
        raise ValueError(f"{key} may contain at most {maximum} champions")
    roster = tuple(
        ChampionLoadout.from_request(value, field=f"{key}[{index}]")
        for index, value in enumerate(raw_roster)
    )
    names = [entry.champion.casefold() for entry in roster]
    if len(set(names)) != len(names):
        raise ValueError(f"{key} must not contain duplicate champions")
    return roster
