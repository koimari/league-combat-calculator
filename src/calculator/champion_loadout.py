"""One roster card: its champion, level, boots, items, item state, role and quest state,
and what resolving it produces."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from .ability_ranks import _validate_ability_ranks
from .auto_attack_policy import AUTO_ATTACK_UPTIME_MODES
from .capabilities import PRE_COMBAT_STATS
from .champions import get_champion_options_meta
from .data_fetcher import get_champion, get_item_by_name
from .defensive_effects import resolve_starting_defenses
from .fight_request_bounds import (
    MAX_ALLIES,
    _bounded_request_float,
    validate_cast_order_shape,
)
from .item_coverage import target_build_coverage
from .item_effects import validate_item_input_options
from .loadout_rules import validate_resolved_loadout
from .practice_dummy import (
    PRACTICE_DUMMY_KIND,
    PRACTICE_DUMMY_LEVEL,
    PRACTICE_DUMMY_NAME,
    apply_stat_overrides,
    parse_stat_overrides,
    practice_dummy_data,
)
from .request_parsing import request_bool, request_index_map, short_string
from .role_quests import require_level_within_cap, validate_role
from .rune_effects import RunePage, validate_rune_page
from .starting_defenses import StartingDefenses
from .stats import MAX_LEVEL, resolve_pre_combat_stats

MAX_LOADOUT_ITEMS = 6


def _validate_champion_options(
    value: object, champion: str, *, field: str
) -> dict[str, Any]:
    """Validate one roster champion's module-declared option controls.

    Roster requests use the same option metadata as the main request.  A
    missing declaration is therefore an empty contract: accepting arbitrary
    keys would make a typo look like an authored control while silently
    dropping it from the participant timeline.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    declared = {
        option["key"]: option
        for option in get_champion_options_meta(champion).get("options", [])
    }
    unknown = set(value) - set(declared)
    if unknown:
        raise ValueError(f"{field} contains unknown option {sorted(unknown)[0]}")
    parsed: dict[str, Any] = {}
    for key, option_value in value.items():
        option = declared[key]
        option_type = option["type"]
        if option_type == "bool":
            if not isinstance(option_value, bool):
                raise ValueError(f"{field}.{key} must be true or false")
        elif option_type == "select":
            if isinstance(option_value, bool) and option.get("legacy_bool"):
                pass
            elif not isinstance(option_value, str):
                raise ValueError(f"{field}.{key} must be a string")
            elif option_value not in {
                choice["value"] for choice in option.get("choices", [])
            }:
                raise ValueError(
                    f"{field}.{key} must be one of "
                    f"{sorted(choice['value'] for choice in option.get('choices', []))}"
                )
        elif option_type == "string_list":
            if not isinstance(option_value, list):
                raise ValueError(f"{field}.{key} must be a list")
            maximum = int(option.get("max_items", 24))
            if len(option_value) > maximum:
                raise ValueError(f"{field}.{key} may contain at most {maximum} entries")
            parsed_values: list[str] = []
            for raw in option_value:
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError(f"{field}.{key} entries must be strings")
                value = raw.strip()
                if len(value) > 100:
                    raise ValueError(
                        f"{field}.{key} entries must be at most 100 characters"
                    )
                parsed_values.append(value)
            if len(set(parsed_values)) != len(parsed_values):
                raise ValueError(f"{field}.{key} must not contain duplicates")
            parsed[key] = parsed_values
            continue
        else:
            if isinstance(option_value, bool) or not isinstance(
                option_value, (int, float)
            ):
                raise ValueError(f"{field}.{key} must be a number")
            if option_type == "int" and not isinstance(option_value, int):
                raise ValueError(f"{field}.{key} must be an integer")
            if not math.isfinite(option_value):
                raise ValueError(f"{field}.{key} must be finite")
            if "min" in option and option_value < option["min"]:
                raise ValueError(
                    f"{field}.{key} must be between {option['min']} and {option['max']}"
                )
            if "max" in option and option_value > option["max"]:
                raise ValueError(
                    f"{field}.{key} must be between {option['min']} and {option['max']}"
                )
        parsed[key] = option_value
    return parsed


def _requested_rune_page(
    value: Mapping[str, Any], *, field: str, is_practice_dummy: bool
) -> RunePage | None:
    """Validate one loadout's rune page, or ``None`` when it selects nothing.

    The same four request fields the fight boundary reads, validated by the
    same rules — a loadout's stat card and the fight it feeds must not
    disagree about what the page is. A page that names nothing resolves to
    ``None``: the stat matrix then takes the no-rune path exactly as it did
    before the page existed.
    """
    keys = ("keystone", "minor_runes", "stat_shards", "rune_options")
    if is_practice_dummy:
        if any(value.get(key) for key in keys):
            raise ValueError(f"{field} practice dummies have no runes")
        return None
    page = validate_rune_page(*(value.get(key) for key in keys))
    if not page.keystone and not page.minor_runes and not any(page.stat_shards):
        return None
    return page


@dataclass(frozen=True, slots=True)
class ChampionLoadout:
    """One champion, their level, and the items that contribute stats."""

    champion: str
    level: int
    kind: str = "champion"
    items: tuple[str, ...] = ()
    boots: str = ""
    item_options: dict[str, dict[str, int]] = dataclass_field(default_factory=dict)
    role: str = ""
    role_quest_complete: bool = False
    ally_effects_enabled: bool = False
    ability_ranks: dict[str, int] = dataclass_field(default_factory=dict)
    champion_options: dict[str, Any] = dataclass_field(default_factory=dict)
    support_target_selections: dict[str, int] = dataclass_field(default_factory=dict)
    cast_order: list[str] | None = None
    target_stats: dict[str, float] = dataclass_field(default_factory=dict)
    # A page that selects nothing stays ``None`` rather than an empty
    # ``RunePage``, so a loadout with no runes takes the same code path
    # through ``calculate_total_stats`` it took before runes existed.
    rune_page: RunePage | None = None
    #: Optional starting health for this participant.  ``None`` means the
    #: participant starts the fight at full health; a number starts them at
    #: exactly that many health, bounded by their resolved maximum health.
    current_health: float | None = None
    include_auto_attacks: bool | None = None
    auto_attack_uptime_mode: str | None = None
    auto_attack_uptime: float | None = None

    @property
    def is_practice_dummy(self) -> bool:
        """Return whether this loadout is the passive Practice Tool dummy."""
        return self.kind == PRACTICE_DUMMY_KIND

    @classmethod
    def from_request(cls, value: object, *, field: str) -> "ChampionLoadout":
        """Parse one public request object with strict, bounded fields."""
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")

        kind = short_string(value.get("kind", "champion"), f"{field}.kind")
        if kind not in {"champion", PRACTICE_DUMMY_KIND}:
            raise ValueError(
                f"{field}.kind must be 'champion' or '{PRACTICE_DUMMY_KIND}'"
            )
        is_practice_dummy = kind == PRACTICE_DUMMY_KIND
        champion = short_string(
            value.get("champion", PRACTICE_DUMMY_NAME if is_practice_dummy else ""),
            f"{field}.champion",
            required=True,
        )
        if is_practice_dummy and champion.casefold() != PRACTICE_DUMMY_NAME.casefold():
            raise ValueError(
                f"{field}.champion must be '{PRACTICE_DUMMY_NAME}' for a practice dummy"
            )
        if is_practice_dummy:
            champion = PRACTICE_DUMMY_NAME
        level = value.get("level", PRACTICE_DUMMY_LEVEL if is_practice_dummy else 1)
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
            short_string(item, f"{field}.items entries", required=True)
            for item in raw_items
        )
        boots = short_string(value.get("boots", ""), f"{field}.boots")
        if is_practice_dummy and boots:
            raise ValueError(f"{field}.boots is not available for a practice dummy")
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
        if is_practice_dummy and (role or role_quest_complete):
            raise ValueError(f"{field} practice dummies do not use a role or quest")
        target_stats = parse_stat_overrides(
            value.get("target_stats"), field=f"{field}.target_stats"
        )
        if not is_practice_dummy and value.get("target_stats") is not None:
            raise ValueError(
                f"{field}.target_stats is only available for a practice dummy"
            )
        # Historical requests omitted this field; keep sourced ally effects
        # active for compatibility.  The browser sends an explicit false when
        # the user turns the opt-in toggle off.
        ally_effects_enabled = value.get("ally_effects_enabled", not is_practice_dummy)
        if not isinstance(ally_effects_enabled, bool):
            raise ValueError(f"{field}.ally_effects_enabled must be true or false")
        if is_practice_dummy and ally_effects_enabled:
            raise ValueError(f"{field} practice dummies cannot apply ally effects")

        raw_ranks = value.get("ability_ranks")
        if is_practice_dummy and raw_ranks:
            raise ValueError(f"{field} practice dummies have no abilities")
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
                if not 0 <= rank <= 6:
                    raise ValueError(
                        f"{field}.ability_ranks.{slot} is outside the legal rank range"
                    )
                ability_ranks[slot] = rank

        if is_practice_dummy and value.get("champion_options"):
            raise ValueError(f"{field} practice dummies have no champion options")
        champion_options = (
            {}
            if is_practice_dummy
            else _validate_champion_options(
                value.get("champion_options"),
                champion,
                field=f"{field}.champion_options",
            )
        )
        support_target_selections = request_index_map(
            value.get("support_target_selections"),
            field=f"{field}.support_target_selections",
            maximum_index=MAX_ALLIES - 1,
        )
        cast_order = value.get("cast_order")
        if is_practice_dummy and cast_order is not None:
            raise ValueError(f"{field} practice dummies have no cast order")
        # Champion-agnostic shape only, exactly as the main attacker's path
        # checks it; which slots this roster member may be told to cast is
        # decided against its parsed kit in ``validate_for_champion`` (D-11).
        validate_cast_order_shape(cast_order, field=f"{field}.cast_order")

        raw_current_health = value.get("current_health")
        if raw_current_health is None:
            current_health = None
        else:
            if isinstance(raw_current_health, bool) or not isinstance(
                raw_current_health, (int, float)
            ):
                raise ValueError(f"{field}.current_health must be a number")
            current_health = float(raw_current_health)
            if not math.isfinite(current_health):
                raise ValueError(f"{field}.current_health must be finite")
            if current_health <= 0.0:
                raise ValueError(f"{field}.current_health must be greater than 0")

        include_auto_attacks = (
            request_bool(value, "include_auto_attacks", False)
            if "include_auto_attacks" in value
            else None
        )
        auto_attack_uptime_mode = value.get("auto_attack_uptime_mode")
        if "auto_attack_uptime_mode" in value and (
            not isinstance(auto_attack_uptime_mode, str)
            or auto_attack_uptime_mode not in AUTO_ATTACK_UPTIME_MODES
        ):
            raise ValueError(
                f"{field}.auto_attack_uptime_mode must be legacy, explicit, or calculated"
            )
        auto_attack_uptime = (
            _bounded_request_float(value, "auto_attack_uptime", 0.0)
            if "auto_attack_uptime" in value
            else None
        )
        equipped_names = (*items, *((boots,) if boots else ()))
        if len(set(equipped_names)) != len(equipped_names):
            raise ValueError(f"{field} must not contain duplicate items")

        rune_page = _requested_rune_page(
            value, field=field, is_practice_dummy=is_practice_dummy
        )

        return cls(
            champion=champion,
            level=level,
            kind=kind,
            items=items,
            boots=boots,
            item_options=item_options,
            role=role,
            role_quest_complete=role_quest_complete,
            ally_effects_enabled=ally_effects_enabled,
            ability_ranks=ability_ranks,
            champion_options=champion_options,
            support_target_selections=support_target_selections,
            cast_order=list(cast_order) if cast_order is not None else None,
            target_stats=target_stats,
            rune_page=rune_page,
            current_health=current_health,
            include_auto_attacks=include_auto_attacks,
            auto_attack_uptime_mode=auto_attack_uptime_mode,
            auto_attack_uptime=auto_attack_uptime,
        )

    def resolve(self) -> "ResolvedLoadout":
        """Resolve cached Wiki data and calculate the complete stat matrix."""
        champion_data = (
            practice_dummy_data()
            if self.is_practice_dummy
            else get_champion(self.champion)
        )
        if not self.is_practice_dummy:
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
        stats = resolve_pre_combat_stats(
            champion_data,
            self.level,
            list(item_data),
            item_options=self.item_options,
            role=self.role,
            role_quest_complete=self.role_quest_complete,
            rune_page=self.rune_page,
            # A roster card receives no ally aura: ``ally_stat_bonuses`` is
            # combined from the *resolved* allies (``resolve_scenario``) and
            # lands on the selected attacker alone, so nothing this card
            # could take exists yet when it resolves.
            external_stat_bonuses=None,
        )
        if self.is_practice_dummy:
            stats = apply_stat_overrides(stats, self.target_stats)
        # The starting-health input is bounded by the participant's resolved
        # maximum health, which is only known here.  A request that asks for
        # more health than the build provides fails closed instead of being
        # silently clamped.
        if self.current_health is not None:
            maximum_health = float(stats.get("health", 0.0) or 0.0)
            if self.current_health > maximum_health:
                raise ValueError(
                    "current_health must not exceed "
                    f"{self.champion}'s maximum health ({maximum_health:g})"
                )
        return ResolvedLoadout(
            request=self,
            champion_data=champion_data,
            item_data=item_data,
            stats=stats,
            defenses=resolve_starting_defenses(
                champion_data["name"],
                self.level,
                stats,
                item_data,
                item_options=self.item_options,
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

    @property
    def is_practice_dummy(self) -> bool:
        """Return whether this resolved participant is the passive dummy."""
        return self.request.is_practice_dummy

    def public_summary(self) -> dict[str, Any]:
        """Return the UI-safe identity, source images, build, and stat matrix."""
        return {
            "champion": self.champion_data["name"],
            "kind": self.request.kind,
            "is_practice_dummy": self.request.is_practice_dummy,
            "icon": self.champion_data.get("icon", ""),
            "level": self.request.level,
            "items": [item["name"] for item in self.item_data],
            "item_icons": [item.get("icon", "") for item in self.item_data],
            "item_options": dict(self.request.item_options),
            "role": self.request.role,
            "role_quest_complete": self.request.role_quest_complete,
            "ally_effects_enabled": self.request.ally_effects_enabled,
            "ability_ranks": dict(self.request.ability_ranks),
            "champion_options": dict(self.request.champion_options),
            "support_target_selections": dict(self.request.support_target_selections),
            "cast_order": (
                list(self.request.cast_order)
                if self.request.cast_order is not None
                else None
            ),
            "target_stats": dict(self.request.target_stats),
            "stats": dict(self.stats),
            "stats_state": PRE_COMBAT_STATS,
            "starting_defenses": self.defenses.public_summary(),
            "target_model_coverage": target_build_coverage(list(self.item_data)),
        }


def load_public_champion(name: str) -> dict[str, Any]:
    """Load one cached champion, translating a data miss into a public 404."""
    try:
        return get_champion(name)
    except KeyError as exc:
        raise LookupError(f"Champion '{name}' not found") from exc


def resolve_named_item(name: str, *, kind: str = "Item") -> dict[str, Any]:
    """Resolve one item name and translate data misses into a public 404."""
    try:
        return get_item_by_name(name)
    except KeyError as exc:
        raise LookupError(f"{kind} '{name}' not found") from exc
