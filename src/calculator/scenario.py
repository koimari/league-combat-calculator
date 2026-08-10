"""Typed champion loadouts for multi-champion combat scenarios.

The damage engine remains intentionally one attacker versus one target.  This
module composes that trusted path across a roster without weakening its
champion-specific rules or replacing item mechanics with generic estimates.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from .ally_effects import combine_ally_stat_effects, resolve_ally_stat_effects
from .champion_coverage import attacker_availability
from .champions import (
    get_champion_options_meta,
    registered_engine_champion_names,
    reviewed_champion_names,
)
from .data_fetcher import get_champion, get_item_by_name
from .defensive_effects import StartingDefenses, resolve_starting_defenses
from .item_coverage import (
    require_calculation_item_coverage,
    require_target_item_coverage,
    target_build_coverage,
)
from .item_effects import validate_item_input_options
from .loadout_rules import validate_resolved_loadout
from .pipeline import FightParams, validate_cast_order_shape
from .practice_dummy import (
    PRACTICE_DUMMY_KIND,
    PRACTICE_DUMMY_LEVEL,
    PRACTICE_DUMMY_NAME,
    apply_stat_overrides,
    parse_stat_overrides,
    practice_dummy_data,
)
from .role_quests import require_level_within_cap, validate_role
from .request_parsing import (
    request_int as _request_int,
    request_string as _request_string,
    request_string_list as _request_string_list,
)
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
    cast_order: list[str] | None = None
    target_stats: dict[str, float] = dataclass_field(default_factory=dict)

    @property
    def is_practice_dummy(self) -> bool:
        """Return whether this loadout is the passive Practice Tool dummy."""
        return self.kind == PRACTICE_DUMMY_KIND

    @classmethod
    def from_request(cls, value: object, *, field: str) -> "ChampionLoadout":
        """Parse one public request object with strict, bounded fields."""
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")

        kind = _short_string(value.get("kind", "champion"), f"{field}.kind")
        if kind not in {"champion", PRACTICE_DUMMY_KIND}:
            raise ValueError(
                f"{field}.kind must be 'champion' or '{PRACTICE_DUMMY_KIND}'"
            )
        is_practice_dummy = kind == PRACTICE_DUMMY_KIND
        champion = _short_string(
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
            _short_string(item, f"{field}.items entries", required=True)
            for item in raw_items
        )
        boots = _short_string(value.get("boots", ""), f"{field}.boots")
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
        ally_effects_enabled = value.get(
            "ally_effects_enabled", False if is_practice_dummy else True
        )
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
                if not 0 <= rank <= (3 if slot == "R" else 6):
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
        cast_order = value.get("cast_order")
        if is_practice_dummy and cast_order is not None:
            raise ValueError(f"{field} practice dummies have no cast order")
        # Champion-agnostic shape only, exactly as the main attacker's path
        # checks it; which slots this roster member may be told to cast is
        # decided against its parsed kit in ``validate_for_champion`` (D-11).
        validate_cast_order_shape(cast_order, field=f"{field}.cast_order")

        equipped_names = (*items, *((boots,) if boots else ()))
        if len(set(equipped_names)) != len(equipped_names):
            raise ValueError(f"{field} must not contain duplicate items")

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
            cast_order=list(cast_order) if cast_order is not None else None,
            target_stats=target_stats,
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
        stats = calculate_total_stats(
            champion_data,
            self.level,
            list(item_data),
            item_options=self.item_options,
            role=self.role,
            role_quest_complete=self.role_quest_complete,
        )
        if self.is_practice_dummy:
            stats = apply_stat_overrides(stats, self.target_stats)
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
            "cast_order": (
                list(self.request.cast_order)
                if self.request.cast_order is not None
                else None
            ),
            "target_stats": dict(self.request.target_stats),
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
    if key != "enemies" and any(entry.is_practice_dummy for entry in roster):
        raise ValueError("Practice Dummy is only available as an enemy target")
    names = [entry.champion.casefold() for entry in roster]
    if len(set(names)) != len(names):
        raise ValueError(f"{key} must not contain duplicate champions")
    return roster


# ---------------------------------------------------------------------------
# Shared scenario request boundary (issue #138)
# ---------------------------------------------------------------------------
# One parse + resolution boundary for /api/calculate, /api/optimize, and
# /api/bis so the three endpoints validate the same fields with the same
# messages (ValueError -> 400, LookupError -> 404) and run the same item
# coverage gates.  See tests/test_endpoint_parity.py.

ENGINE_CHAMPIONS = frozenset(registered_engine_champion_names())
VERIFIED_CHAMPIONS = frozenset(reviewed_champion_names())


def load_public_champion(name: str) -> dict[str, Any]:
    """Load one champion that the public UI and engine both support."""
    try:
        champion = get_champion(name)
    except KeyError as exc:
        raise LookupError(f"Champion '{name}' not found") from exc
    if champion["name"] not in ENGINE_CHAMPIONS:
        availability = attacker_availability(champion, VERIFIED_CHAMPIONS)
        reason = availability["blockers"][0]["label"]
        raise ValueError(f"Champion '{champion['name']}' is not verified: {reason}")
    return champion


def resolve_named_item(name: str, *, kind: str = "Item") -> dict[str, Any]:
    """Resolve one item name and translate data misses into a public 404."""
    try:
        return get_item_by_name(name)
    except KeyError as exc:
        raise LookupError(f"{kind} '{name}' not found") from exc


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    """One validated scenario request shared by calculate/optimize/BIS."""

    champion: str
    level: int
    fight_params: FightParams
    items: tuple[str, ...]  # ordinary items, in request order
    boots: str
    include_crossover: bool
    enemies: tuple[ChampionLoadout, ...]
    allies: tuple[ChampionLoadout, ...]


def parse_scenario_request(
    data: Mapping[str, object],
    *,
    deterministic: bool = False,
    parse_crossover: bool = True,
) -> ScenarioRequest:
    """Parse the shared scenario preamble with one strict message contract.

    Covers champion, level, items, boots, fight params, level-within-cap,
    ``include_crossover``, and the enemy/ally rosters.  The main champion's
    module-declared options are validated during resolution against the
    canonical cached name (so aliased spellings keep working); every
    shape/range violation raises ValueError and the routes map that to 400
    identically.
    """
    champion = _request_string(data, "champion", required=True)
    level = _request_int(data, "level", 1, 1, MAX_LEVEL)
    item_names = _request_string_list(data, "items", maximum=MAX_LOADOUT_ITEMS)
    boots_name = _request_string(data, "boots")
    fight_params = FightParams.from_request(data, deterministic=deterministic)
    require_level_within_cap(level, fight_params.role, fight_params.role_quest_complete)
    if parse_crossover:
        include_crossover = data.get("include_crossover", False)
        if not isinstance(include_crossover, bool):
            raise ValueError("include_crossover must be true or false")
    else:
        include_crossover = False
    enemies = parse_roster(data, "enemies", maximum=MAX_ENEMIES)
    allies = parse_roster(data, "allies", maximum=MAX_ALLIES)
    return ScenarioRequest(
        champion=champion,
        level=level,
        fight_params=fight_params,
        items=tuple(item_names),
        boots=boots_name,
        include_crossover=include_crossover,
        enemies=enemies,
        allies=allies,
    )


@dataclass(frozen=True, slots=True)
class ResolvedScenario:
    """A scenario joined to cached data, validated, and ready to run."""

    champion_data: dict[str, Any]
    items: tuple[dict[str, Any], ...]  # boots first, then ordinary items
    enemies: tuple[ResolvedLoadout, ...]
    allies: tuple[ResolvedLoadout, ...]
    fight_params: FightParams  # after ally-effect folding
    target_fight_params: tuple[FightParams, ...]  # per-enemy target overrides
    ally_effects: tuple[Any, ...]


def resolve_scenario(request: ScenarioRequest) -> ResolvedScenario:
    """Run the shared resolution + validation boundary for every endpoint.

    Loads the public champion, validates fight-mode/rank contracts, resolves
    and validates the inventory, applies calculation coverage to the
    attacker/enemies/allies and target coverage to enemies, checks the
    roster fight window, folds ally stat effects, and builds the per-target
    fight params.  Raises LookupError (->404) for missing champion/item data
    and ValueError (->400) for every validation failure.
    """
    champion_data = load_public_champion(request.champion)
    request.fight_params.validate_for_champion(champion_data["name"], request.level)
    # The main champion's options use the same module-declared contract as
    # every roster member's.  Validate against the canonical cached display
    # name (``champion_data["name"]``), not the raw request string, so
    # aliased spellings such as ``KSante`` behave exactly like the historic
    # calculate/optimize path.
    _validate_champion_options(
        request.fight_params.champion_options,
        champion_data["name"],
        field="champion_options",
    )
    resolved_boots = (
        resolve_named_item(request.boots, kind="Boots") if request.boots else None
    )
    ordinary_items = [resolve_named_item(name) for name in request.items]
    validate_resolved_loadout(
        ordinary_items,
        boots=resolved_boots,
        role=request.fight_params.role,
        role_quest_complete=request.fight_params.role_quest_complete,
    )
    items = ((resolved_boots,) if resolved_boots else ()) + tuple(ordinary_items)
    require_calculation_item_coverage(
        list(items),
        participant="Attacker",
        allow_ally_effects=True,
    )
    try:
        enemies = tuple(loadout.resolve() for loadout in request.enemies)
        allies = tuple(loadout.resolve() for loadout in request.allies)
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "requested data"
        raise LookupError(f"Scenario data '{missing}' not found") from exc

    # participant_timeline imports this module, so the roster-window gate is
    # imported lazily to keep the module graph acyclic.
    # pylint: disable-next=import-outside-toplevel  # deliberate, see above
    from .participant_timeline import require_roster_fight_window_support

    require_roster_fight_window_support(
        request.fight_params, enemies=enemies, allies=allies
    )
    for enemy in enemies:
        participant = f"Enemy {enemy.champion_data['name']}"
        require_calculation_item_coverage(
            list(enemy.item_data), participant=participant
        )
        require_target_item_coverage(list(enemy.item_data))
    for ally in allies:
        participant = f"Ally {ally.champion_data['name']}"
        require_calculation_item_coverage(
            list(ally.item_data),
            participant=participant,
            allow_ally_effects=True,
        )

    ally_effects = tuple(
        effect
        for ally in allies
        if ally.request.ally_effects_enabled
        for effect in resolve_ally_stat_effects(ally.item_data)
    )
    fight_params = request.fight_params
    if ally_effects:
        fight_params = replace(
            fight_params,
            ally_stat_bonuses=combine_ally_stat_effects(ally_effects),
        )

    target_fight_params = tuple(
        replace(
            fight_params,
            roster_target_index=target_index,
            roster_target_count=len(enemies),
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            target_magic_shield=enemy.defenses.magic_shield,
            target_physical_shield=enemy.defenses.physical_shield,
            target_general_shield=enemy.defenses.general_shield,
            target_basic_damage_multiplier=enemy.defenses.basic_damage_multiplier,
            target_basic_damage_flat_reduction=(
                enemy.defenses.basic_damage_flat_reduction
            ),
            target_basic_damage_flat_reduction_cap=(
                enemy.defenses.basic_damage_flat_reduction_cap
            ),
            target_critical_strike_damage_multiplier=(
                enemy.defenses.critical_strike_damage_multiplier
            ),
            target_threshold_shield_amount=enemy.defenses.threshold_shield_amount,
            target_threshold_shield_health_ratio=(
                enemy.defenses.threshold_shield_health_ratio
            ),
            target_threshold_shield_duration=(enemy.defenses.threshold_shield_duration),
            target_threshold_shield_damage_type=(
                enemy.defenses.threshold_shield_damage_type
            ),
            target_threshold_health_bonus=enemy.defenses.threshold_health_bonus,
            target_threshold_health_heal=enemy.defenses.threshold_health_heal,
            target_threshold_health_ratio=enemy.defenses.threshold_health_ratio,
            target_threshold_health_duration=(enemy.defenses.threshold_health_duration),
        )
        for target_index, enemy in enumerate(enemies)
    )
    return ResolvedScenario(
        champion_data=champion_data,
        items=items,
        enemies=enemies,
        allies=allies,
        fight_params=fight_params,
        target_fight_params=target_fight_params,
        ally_effects=ally_effects,
    )
