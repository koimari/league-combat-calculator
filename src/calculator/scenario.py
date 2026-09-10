"""Typed champion loadouts for multi-champion combat scenarios.

The damage engine remains intentionally one attacker versus one target.  This
module composes that trusted path across a roster without weakening its
champion-specific rules or replacing item mechanics with generic estimates.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .ally_effects import combine_ally_stat_effects, resolve_ally_stat_effects
from .champion_loadout import (
    MAX_LOADOUT_ITEMS,
    ChampionLoadout,
    ResolvedLoadout,
    _validate_champion_options,
    load_public_champion,
    resolve_named_item,
)
from .combat_events import roster_ids
from .fight_params import FightParams
from .fight_request_bounds import MAX_ALLIES, MAX_ENEMIES
from .interaction_effects import target_physical_damage_reduction_params
from .item_coverage import (
    require_calculation_item_coverage,
    require_target_item_coverage,
)
from .loadout_rules import validate_resolved_loadout
from .request_parsing import (
    request_int as _request_int,
)
from .request_parsing import (
    request_string as _request_string,
)
from .request_parsing import (
    request_string_list as _request_string_list,
)
from .role_quests import require_level_within_cap
from .stats import MAX_LEVEL


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
# Shared scenario request boundary
# ---------------------------------------------------------------------------
# One parse + resolution boundary for /api/calculate, /api/optimize, and
# /api/bis so the three endpoints validate the same fields with the same
# messages (ValueError -> 400, LookupError -> 404) and run the same item
# coverage gates.  See tests/test_endpoint_parity.py.


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
    level = _request_int(data, "level", 1, minimum=1, maximum=MAX_LEVEL)
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

    event_target_ids = roster_ids(
        [enemy.champion_data["name"] for enemy in enemies], "enemy"
    )
    target_fight_params = tuple(
        replace(
            fight_params,
            roster_target_index=target_index,
            event_target_id=event_target_ids[target_index],
            roster_target_count=len(enemies),
            target_health=enemy.stats["health"],
            target_bonus_health=enemy.stats["bonus_health"],
            target_armor=enemy.stats["armor"],
            target_magic_resistance=enemy.stats["magic_resistance"],
            **target_physical_damage_reduction_params(enemy),
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
            target_champion_damage_flat_reduction=(
                enemy.defenses.champion_damage_flat_reduction
            ),
            target_champion_dot_damage_flat_reduction=(
                enemy.defenses.champion_dot_damage_flat_reduction
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
