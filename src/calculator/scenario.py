"""Typed champion loadouts for multi-champion combat scenarios.

The damage engine remains intentionally one attacker versus one target.  This
module composes that trusted path across a roster without weakening its
champion-specific rules or replacing item mechanics with generic estimates.
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping

from .data_fetcher import get_champion, get_item_by_name
from .defensive_effects import StartingDefenses, resolve_starting_defenses
from .item_effects import validate_item_input_options
from .item_coverage import target_build_coverage
from .loadout_rules import validate_resolved_loadout
from .role_quests import require_level_within_cap, validate_role
from .stats import MAX_LEVEL, calculate_total_stats
from .champions.skill_orders import get_ability_rank

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
    role: str = ""
    role_quest_complete: bool = False
    ally_effects_enabled: bool = False
    ability_ranks: dict[str, int] = dataclass_field(default_factory=dict)

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
        role = validate_role(value.get("role", ""))
        role_quest_complete = value.get("role_quest_complete", False)
        if not isinstance(role_quest_complete, bool):
            raise ValueError(f"{field}.role_quest_complete must be true or false")
        if role_quest_complete and not role:
            raise ValueError(f"{field}.role is required when role quest is complete")
        require_level_within_cap(
            level, role, role_quest_complete, field=f"{field}.level"
        )
        # Historical requests omitted this field; keep sourced ally effects
        # active for compatibility.  The browser sends an explicit false when
        # the user turns the opt-in toggle off.
        ally_effects_enabled = value.get("ally_effects_enabled", True)
        if not isinstance(ally_effects_enabled, bool):
            raise ValueError(f"{field}.ally_effects_enabled must be true or false")

        raw_ranks = value.get("ability_ranks")
        if raw_ranks is None:
            ability_ranks = {}
        elif not isinstance(raw_ranks, Mapping):
            raise ValueError(f"{field}.ability_ranks must be an object")
        else:
            unknown = set(raw_ranks) - {"Q", "W", "E", "R"}
            if unknown:
                raise ValueError(
                    f"{field}.ability_ranks contains unknown key {sorted(unknown)[0]}"
                )
            ability_ranks = {}
            for slot, rank in raw_ranks.items():
                if isinstance(rank, bool) or not isinstance(rank, int):
                    raise ValueError(f"{field}.ability_ranks.{slot} must be an integer")
                if not 0 <= rank <= (3 if slot == "R" else 6):
                    raise ValueError(
                        f"{field}.ability_ranks.{slot} is outside the legal rank range"
                    )
                ability_ranks[slot] = rank

        equipped_names = (*items, *((boots,) if boots else ()))
        if len(set(equipped_names)) != len(equipped_names):
            raise ValueError(f"{field} must not contain duplicate items")

        return cls(
            champion=champion,
            level=level,
            items=items,
            boots=boots,
            item_options=item_options,
            role=role,
            role_quest_complete=role_quest_complete,
            ally_effects_enabled=ally_effects_enabled,
            ability_ranks=ability_ranks,
        )

    def resolve(self) -> "ResolvedLoadout":
        """Resolve cached Wiki data and calculate the complete stat matrix."""
        champion_data = get_champion(self.champion)
        _validate_ability_ranks(
            champion_data,
            self.level,
            self.ability_ranks,
            field="loadout.ability_ranks",
        )
        ordinary_items = tuple(get_item_by_name(name) for name in self.items)
        boots_data = get_item_by_name(self.boots) if self.boots else None
        validate_resolved_loadout(
            ordinary_items,
            boots=boots_data,
            role=self.role,
            role_quest_complete=self.role_quest_complete,
        )
        item_data = (*((boots_data,) if boots_data else ()), *ordinary_items)
        stats = calculate_total_stats(
            champion_data,
            self.level,
            list(item_data),
            item_options=self.item_options,
            role=self.role,
            role_quest_complete=self.role_quest_complete,
        )
        return ResolvedLoadout(
            request=self,
            champion_data=champion_data,
            item_data=item_data,
            stats=stats,
            defenses=resolve_starting_defenses(
                champion_data["name"], self.level, stats, item_data
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedLoadout:
    """A loadout joined to locally cached champion/item data and final stats."""

    request: ChampionLoadout
    champion_data: dict[str, Any]
    item_data: tuple[dict[str, Any], ...]
    stats: dict[str, float]
    defenses: StartingDefenses

    def public_summary(self) -> dict[str, Any]:
        """Return the UI-safe identity, source images, build, and stat matrix."""
        return {
            "champion": self.champion_data["name"],
            "icon": self.champion_data.get("icon", ""),
            "level": self.request.level,
            "items": [item["name"] for item in self.item_data],
            "item_icons": [item.get("icon", "") for item in self.item_data],
            "item_options": dict(self.request.item_options),
            "role": self.request.role,
            "role_quest_complete": self.request.role_quest_complete,
            "ally_effects_enabled": self.request.ally_effects_enabled,
            "ability_ranks": dict(self.request.ability_ranks),
            "stats": dict(self.stats),
            "starting_defenses": self.defenses.public_summary(),
            "target_model_coverage": target_build_coverage(list(self.item_data)),
        }


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
