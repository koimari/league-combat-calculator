"""Module for calculating champion stats at any level with items applied."""

import math
from collections.abc import Mapping
from typing import Any

from .data_registry import data_version, store_for_generation
from .interpreters.stat_derivation import armor_penetration_split
from .item_effects import (
    grouped_sustain_stat_percent,
    input_option_crit_chance,
    input_option_retribution_bonus_ad,
    input_option_stat_bonuses,
    override_item_stat,
    resolve_stat_effects,
)
from .role_quests import MID_QUEST_AP_PERCENT, MID_QUEST_BONUS_AD_PERCENT
from .rune_effects import RunePage, compile_rune_page
from .stat_conversion import BonusHealthConversion

# Level cap — 20 is top-lane-only as of this season, so this is
# season-volatile. Single source of truth: the API guards and the UI
# slider (via the index template) both read this constant.
MAX_LEVEL = 20


def growth_multiplier(level: int) -> float:
    """The growth formula's progression term, ``0.7025 + 0.0175 * (level - 1)``."""
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"Level must be between 1 and {MAX_LEVEL}, got {level}")
    return 0.7025 + 0.0175 * (level - 1)


def growth_stat(base: float, growth: float, level: int) -> float:
    """``base + growth * (level - 1) * (0.7025 + 0.0175 * (level - 1))``."""
    return base + growth * (level - 1) * growth_multiplier(level)


# Where two of the engine's item-stat keys name ONE stat in game.  What
# "a unique stat type gained from items" counts is the game's stat types
# (Jack Of All Trades' whole stack rule), and the engine splits three of
# them for its own arithmetic — so a build wearing boots earns one stack for
# movement speed rather than two.  Every other key is its own type.
_ONE_ITEM_STAT_TYPE: dict[str, str] = {
    "move_speed_flat": "move_speed",
    "move_speed_percent": "move_speed",
    "health_regen_flat": "health_regen",
    "health_regen_percent": "health_regen",
    "armor_penetration_percent": "armor_penetration",
    "armor_penetration_bonus_percent": "armor_penetration",
}


def item_stat_type_count(total_item_stats: Mapping[str, float]) -> int:
    """How many distinct stat types this build's items grant.

    Counted off the build's own item stat totals rather than a list of stat
    names, so an item that stops granting a stat stops being counted here.
    Only stat blocks are in those totals: a stat an item passive grants
    conditionally is not one the build currently has.
    """
    return len(
        {
            _ONE_ITEM_STAT_TYPE.get(key, key)
            for key, value in total_item_stats.items()
            if value
        }
    )


# The game clamps a unit's TOTAL attack speed to 3.003 (one basic attack
# per 0.333s); the floor is 0.2. See
# https://wiki.leagueoflegends.com/en-us/Attack_speed
# NOTE: ``calculate_attack_speed`` deliberately does NOT clamp — applying
# the cap fight-wide would move every attack-speed champion's numbers at
# once. Today only a burst that is *designed* to reach the cap reads it
# (Jayce's Hyper Charge: 360% on his 0.658 ratio lands at 3.027, which is
# why the in-game tooltip reads "maximum Attack Speed" and not a percent).
ATTACK_SPEED_CAP = 3.003


# base AS and the AS ratio are separate per-champion values.
# https://wiki.leagueoflegends.com/en-us/Attack_speed
def calculate_attack_speed(
    base_attack_speed: float,
    attack_speed_ratio: float,
    bonus_percent: float,
) -> float:
    """Attacks per second: ``base_AS + AS_ratio * (bonus_percent / 100)``."""
    return base_attack_speed + attack_speed_ratio * (bonus_percent / 100.0)


def resolve_move_speed(flat_total: float, percent_total: float) -> float:
    """The one fold from movement-speed components to a displayed number."""
    return apply_movement_speed_soft_caps(flat_total * (1.0 + percent_total / 100.0))


def apply_movement_speed_soft_caps(raw_speed: float) -> float:
    """Apply League's displayed movement-speed soft caps."""
    if raw_speed > 490:
        return raw_speed * 0.5 + 230
    if raw_speed > 415:
        return raw_speed * 0.8 + 83
    if raw_speed < 220:
        return raw_speed * 0.5 + 110
    return raw_speed


def get_champion_base_stats(
    champion_data: Mapping[str, Any], level: int
) -> dict[str, float]:
    """Calculate a champion's base stats at a given level (no items).

    Args:
        champion_data: Champion data dictionary from the CDN.
        level: Champion level (1-20; 19-20 need the completed top quest).

    Returns:
        Dictionary with stat names and their computed values.
    """
    stats = champion_data["stats"]

    health = growth_stat(stats["health"]["flat"], stats["health"]["perLevel"], level)
    attack_damage = growth_stat(
        stats["attackDamage"]["flat"],
        stats["attackDamage"]["perLevel"],
        level,
    )
    armor = growth_stat(stats["armor"]["flat"], stats["armor"]["perLevel"], level)
    magic_resistance = growth_stat(
        stats["magicResistance"]["flat"],
        stats["magicResistance"]["perLevel"],
        level,
    )

    # Attack speed uses percentage growth with separate AS ratio
    as_ratio = stats.get("attackSpeedRatio", {}).get(
        "flat", stats["attackSpeed"]["flat"]
    )
    attack_speed_bonus_percent = growth_stat(0, stats["attackSpeed"]["perLevel"], level)
    attack_speed = calculate_attack_speed(
        stats["attackSpeed"]["flat"], as_ratio, attack_speed_bonus_percent
    )

    return {
        "health": health,
        "attack_damage": attack_damage,
        "ability_power": 0.0,
        "armor": armor,
        "magic_resistance": magic_resistance,
        "attack_speed": attack_speed,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": stats["movespeed"]["flat"],
    }


# The optimizer recomputes candidate stats thousands of times over the same
# cached item dicts, so the pure extraction below is memoized by
# ``(data_version(), item_id)``: a value derived from the record the cache
# serves, never the record's address.  The pair is a value key because the
# data layer owns the corpus: within one generation an item id names exactly
# one cached record, every refresh goes through ``data_updater`` and moves
# the version, and nothing may mutate a cached record in place (CLAUDE.md
# rule 2).  Each entry keeps a strong reference to the record it was derived
# from and re-checks it on the way out, so two records sharing an id
# recompute rather than serve each other's stats.
#
# A record that declares no id is not memoized at all: sparse unit fixtures
# are exactly those records, and a key derived from nothing is one entry
# every fixture in the suite would share.
#
# The write goes through ``store_for_generation`` because this memo has no
# size bound, so the first write of a new generation drops the old one.  The
# read stays a bare key lookup: a hit has already matched the live
# generation, and this is one of the optimizer's inner loops.
_ITEM_STATS_MEMO: dict[tuple[int, int], tuple[dict[str, Any], dict[str, float]]] = {}
# The schema verdict on the same record, keyed the same way.  Keep the
# validated item and its nested stats map alive so coupled optimizer searches
# do not walk the same schema thousands of times.
_ITEM_STATS_VALIDATION_MEMO: dict[
    tuple[int, int], tuple[dict[str, Any], Mapping[str, Any]]
] = {}


# ``None`` refuses to cache rather than sharing a bucket: a fixture declaring
# no id would file every such fixture under one key.  ``bool`` is refused with
# the non-integers because ``hash(True) == hash(1)``, so a bool-id fixture
# would share the entry of the item whose id is 1.  A refusal is total: it
# skips both memos this key gates, and every record it refuses is a fixture.
def _record_key(item_data: Mapping[str, Any]) -> tuple[int, int] | None:
    """One cached item record's value key, or ``None`` when it has none."""
    item_id = item_data.get("id")
    if not isinstance(item_id, int) or isinstance(item_id, bool):
        return None
    return (data_version(), item_id)


def _validate_cached_item_stats(item_data: dict[str, Any]) -> None:
    """Reject malformed source stat maps while keeping synthetic fixtures sparse.

    Cached item records carry an ``id`` and a complete nested stat map.  Small
    unit-test fixtures intentionally omit those source markers and continue to
    receive zero for absent stats.  A malformed cached map must not silently
    turn a broken value into zero, however, because that changes every
    downstream stat and sustain calculation.
    """
    if item_data.get("id") is None and not item_data.get("icon"):
        return
    item_name = str(item_data.get("name") or "unknown item")
    raw_stats = item_data.get("stats")
    memo_key = _record_key(item_data)
    memo = None if memo_key is None else _ITEM_STATS_VALIDATION_MEMO.get(memo_key)
    if memo is not None and memo[0] is item_data and memo[1] is raw_stats:
        return
    if not isinstance(raw_stats, Mapping):
        raise ValueError(f"Cached item {item_name} has an invalid stats map")
    required_components = {
        "flat",
        "percent",
        "perLevel",
        "percentPerLevel",
        "percentBase",
        "percentBonus",
    }
    for stat_name, raw_stat in raw_stats.items():
        if not isinstance(raw_stat, Mapping):
            raise ValueError(
                f"Cached item {item_name} stat {stat_name} must be an object"
            )
        missing = required_components - set(raw_stat)
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise ValueError(
                f"Cached item {item_name} stat {stat_name} is missing "
                f"{missing_names}"
            )
        for component, value in raw_stat.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Cached item {item_name} stat {stat_name}.{component} "
                    "must be numeric"
                )
            if not math.isfinite(float(value)):
                raise ValueError(
                    f"Cached item {item_name} stat {stat_name}.{component} "
                    "must be finite"
                )
    if memo_key is not None:
        store_for_generation(
            _ITEM_STATS_VALIDATION_MEMO, memo_key, (item_data, raw_stats)
        )


def get_item_stats(item_data: dict[str, Any]) -> dict[str, float]:
    """Extract stat bonuses from an item.

    Args:
        item_data: Item data dictionary from the CDN.

    Returns:
        Dictionary with stat names and their flat values.  Treat it as
        read-only: the same dict is returned for repeated lookups of the
        same cached item.
    """
    _validate_cached_item_stats(item_data)
    memo_key = _record_key(item_data)
    memo = None if memo_key is None else _ITEM_STATS_MEMO.get(memo_key)
    if memo is not None and memo[0] is item_data:
        return memo[1]
    stats = item_data.get("stats", {})

    def get_flat(stat_name: str) -> float:
        stat = stats.get(stat_name, {})
        if isinstance(stat, dict):
            return stat.get("flat", 0.0)
        return 0.0

    def get_percent(stat_name: str) -> float:
        stat = stats.get(stat_name, {})
        if isinstance(stat, dict):
            return stat.get("percent", 0.0)
        return 0.0

    total_armor_pen_percent, bonus_armor_pen_percent = armor_penetration_split(
        str(item_data.get("name", "")), get_percent("armorPenetration")
    )
    extracted = {
        "health": get_flat("health"),
        "attack_damage": get_flat("attackDamage"),
        "ability_power": get_flat("abilityPower"),
        "armor": get_flat("armor"),
        "magic_resistance": get_flat("magicResistance"),
        "attack_speed_percent": get_flat("attackSpeed"),
        "magic_penetration_flat": get_flat("magicPenetration"),
        "magic_penetration_percent": get_percent("magicPenetration"),
        "ability_power_percent": 0.0,
        "lethality": get_flat("lethality"),
        "armor_penetration_percent": total_armor_pen_percent,
        "armor_penetration_bonus_percent": bonus_armor_pen_percent,
        "critical_strike_chance": (
            get_flat("criticalStrikeChance") + get_percent("criticalStrikeChance")
        ),
        "mana": get_flat("mana"),
        "ability_haste": get_flat("abilityHaste"),
        "mana_regen_percent": get_percent("manaRegen"),
        "lifesteal_percent": get_percent("lifesteal"),
        "omnivamp_percent": get_percent("omnivamp"),
        "heal_and_shield_power_percent": (
            get_flat("healAndShieldPower") + get_percent("healAndShieldPower")
        ),
        # Health regeneration has both a flat HP5 component (Doran's Shield,
        # Rejuvenation Bead, ...) and a percentage-base component (Warmog's,
        # Spirit Visage).  Dropping the flat value silently removed the
        # strongest part of several starter/defensive item entries.
        "health_regen_flat": get_flat("healthRegen"),
        "health_regen_percent": get_percent("healthRegen"),
        "tenacity_percent": get_percent("tenacity"),
        "gold_per_10": get_flat("goldPer10"),
        "critical_strike_damage_percent": get_percent("criticalStrikeDamage"),
        "move_speed_flat": get_flat("movespeed"),
        "move_speed_percent": get_percent("movespeed"),
    }
    extracted["omnivamp_percent"] = override_item_stat(
        str(item_data.get("name") or "unknown item"),
        "omnivamp_percent",
        extracted["omnivamp_percent"],
    )
    if memo_key is not None:
        store_for_generation(_ITEM_STATS_MEMO, memo_key, (item_data, extracted))
    return extracted


# Champion modules import this module, so the registry that owns their
# declarations is reached at call time rather than at import.
def champion_stat_conversion(
    champion_data: Mapping[str, Any],
) -> BonusHealthConversion | None:
    """This champion's declared stat conversion, or ``None``."""
    from .champions import (  # pylint: disable=import-outside-toplevel
        get_champion_stat_conversion,
    )

    return get_champion_stat_conversion(str(champion_data.get("name", "")))


# Only a MANA pool takes an item's mana: an energy pool is a fixed 200
# (Shen's 400) and no other declared resource grows from items either, so a
# mana item is a wasted stat line on those kits.  A record declaring no
# resource is a sparse unit fixture and keeps the mana pool.
def item_mana_reaches_pool(champion_data: Mapping[str, Any]) -> bool:
    """Whether an item's mana and mana regeneration reach this pool."""
    resource = champion_data.get("resource")
    return resource is None or str(resource) == "MANA"


def calculate_total_stats(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    item_options: Mapping[str, Mapping[str, int]] | None = None,
    role: str = "",
    role_quest_complete: bool = False,
    external_stat_bonuses: Mapping[str, float] | None = None,
    rune_page: RunePage | None = None,
) -> dict[str, float]:
    """Calculate total champion stats with items applied.

    Args:
        champion_data: Champion data dictionary from the CDN.
        level: Champion level (1-20).
        items: List of item data dictionaries.
        rune_page: The validated rune page whose stat runes grant into this
            build. ``None`` grants nothing, which is the answer for every
            participant but the attacker.

    Returns:
        Dictionary with final stat values.
    """
    base_stats = get_champion_base_stats(champion_data, level)

    total_item_stats: dict[str, float] = {
        "health": 0.0,
        "attack_damage": 0.0,
        "ability_power": 0.0,
        "armor": 0.0,
        "magic_resistance": 0.0,
        "attack_speed_percent": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "lethality": 0.0,
        "armor_penetration_percent": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "critical_strike_chance": 0.0,
        "mana": 0.0,
        "ability_haste": 0.0,
        "mana_regen_percent": 0.0,
        "lifesteal_percent": 0.0,
        "omnivamp_percent": 0.0,
        "heal_and_shield_power_percent": 0.0,
        "health_regen_flat": 0.0,
        "health_regen_percent": 0.0,
        "tenacity_percent": 0.0,
        "gold_per_10": 0.0,
        "critical_strike_damage_percent": 0.0,
        "move_speed_flat": 0.0,
        "move_speed_percent": 0.0,
    }

    for item in items:
        item_stats = get_item_stats(item)
        # Most items grant a handful of the tracked stats; adding the zeros
        # is a no-op bit-for-bit, so only non-zero grants touch the totals
        # (keys outside the tracked set are ignored exactly as before).
        for key, value in item_stats.items():
            if value:
                total = total_item_stats.get(key)
                if total is not None:
                    total_item_stats[key] = total + value

    # Stateful item inputs are explicit scenario state, not guessed proc
    # counts. Apply their sourced health/mana before conversions (Awe,
    # Muramana, Seraph's) read those totals.
    _, input_move_speed_percent, input_bonus_health, input_bonus_mana = (
        input_option_stat_bonuses(items, item_options)
    )
    total_item_stats["health"] += input_bonus_health
    total_item_stats["mana"] += input_bonus_mana
    is_melee = champion_data.get("attackType", "MELEE") == "MELEE"
    total_item_stats["critical_strike_chance"] += input_option_crit_chance(
        items, item_options, is_melee=is_melee
    )

    external = external_stat_bonuses or {}
    total_item_stats["ability_power"] += float(external.get("ability_power", 0.0))
    total_item_stats["ability_haste"] += float(external.get("ability_haste", 0.0))

    # Mana first — stat conversions read it (Awe → AP, Muramana → AD).
    # An item's mana grant lands in a MANA pool only; the item still grants
    # the stat (Jack Of All Trades counts it above), the kit just has no
    # pool it can grow. The two reads stay separate from the item totals so
    # every consumer of the pool — the published card, the conversions and
    # the fight's resource walk — sees the same one.
    pool_takes_item_mana = item_mana_reaches_pool(champion_data)
    pool_item_mana = total_item_stats["mana"] if pool_takes_item_mana else 0.0
    pool_item_mana_regen_percent = (
        total_item_stats["mana_regen_percent"] if pool_takes_item_mana else 0.0
    )
    cdm = champion_data["stats"]
    base_mana = growth_stat(
        cdm.get("mana", {}).get("flat", 0),
        cdm.get("mana", {}).get("perLevel", 0),
        level,
    )
    total_mana = base_mana + pool_item_mana
    base_resource_regen_per_five = growth_stat(
        cdm.get("manaRegen", {}).get("flat", 0),
        cdm.get("manaRegen", {}).get("perLevel", 0),
        level,
    )
    resource_regen_per_second = (
        base_resource_regen_per_five
        * (1.0 + pool_item_mana_regen_percent / 100.0)
        / 5.0
    )
    base_health_regen_per_five = growth_stat(
        cdm.get("healthRegen", {}).get("flat", 0),
        cdm.get("healthRegen", {}).get("perLevel", 0),
        level,
    )
    health_regen_per_five = (
        base_health_regen_per_five + total_item_stats["health_regen_flat"]
    ) * (1.0 + total_item_stats["health_regen_percent"] / 100.0)
    health_regen_per_second = health_regen_per_five / 5.0

    # The page compiles once and is totalled twice, because the fold needs
    # two of its answers at two different points.
    page = compile_rune_page(rune_page)
    item_stat_types = item_stat_type_count(total_item_stats)

    # Movement speed is the first of those two points, and it is settled
    # here: every source of it — items, item state, rune grants — is
    # already known, and the soft caps are what the champion actually
    # moves at. Swiftmarch converts that one number into adaptive force,
    # and the fight's ``item_state_receipts`` read the same published
    # ``move_speed``, so the item sees one movement speed rather than an
    # uncapped pre-rune one here and the real one there. No rune's
    # movement-speed grant reads the adaptive comparison, which is why
    # this total can be taken before the conversions that decide it.
    move_speed_flat = base_stats["move_speed"] + total_item_stats["move_speed_flat"]
    move_speed_percent = (
        total_item_stats["move_speed_percent"]
        + input_move_speed_percent
        + page.grants(
            level=level,
            is_melee=is_melee,
            bonus_attack_damage=total_item_stats["attack_damage"],
            ability_power=total_item_stats["ability_power"],
            item_stat_types=item_stat_types,
        ).move_speed_percent
    )
    final_move_speed = resolve_move_speed(move_speed_flat, move_speed_percent)

    # Every stat-granting item passive, compiled once. item_effects owns
    # the per-item knowledge; this function owns the application order.
    bonuses = resolve_stat_effects(
        items,
        bonus_mana=pool_item_mana,
        max_mana=total_mana,
        bonus_health=total_item_stats["health"],
        base_attack_damage=base_stats["attack_damage"],
        bonus_attack_damage=total_item_stats["attack_damage"],
        bonus_mana_regen_percent=pool_item_mana_regen_percent,
        is_melee=is_melee,
        level=level,
        item_options=item_options,
        total_move_speed=final_move_speed,
        adaptive_type=str(champion_data.get("adaptiveType", "")),
    )

    quest_ap_multiplier = (
        MID_QUEST_AP_PERCENT / 100.0 if role == "mid" and role_quest_complete else 0.0
    )
    quest_bonus_ad_multiplier = (
        1.0 + MID_QUEST_BONUS_AD_PERCENT / 100.0
        if role == "mid" and role_quest_complete
        else 1.0
    )

    # Rune stat grants resolve here, after the item passives, because every
    # adaptive grant asks which of the build's bonus attack damage and
    # ability power is larger — and neither is complete until the
    # conversions (Muramana → AD, Awe → AP), the %AP multiplier and the role
    # quest have been applied. The grants themselves are excluded from that
    # comparison, as in game, and are kept out of ``total_item_stats``: each
    # is added below where that stat belongs, because a rune's adaptive
    # force is not an item stat (Kai'Sa's evolutions exclude it) even though
    # it lands in the same total.
    runes = page.grants(
        level=level,
        is_melee=is_melee,
        bonus_attack_damage=(total_item_stats["attack_damage"] + bonuses.bonus_ad)
        * quest_bonus_ad_multiplier,
        ability_power=(
            base_stats["ability_power"]
            + total_item_stats["ability_power"]
            + bonuses.bonus_ap
        )
        * (bonuses.ap_multiplier + quest_ap_multiplier),
        item_stat_types=item_stat_types,
    )

    # Ability power: base + items + converted AP, then the additive %AP
    # multiplier (Rabadon's, Blackfire Torch).
    raw_ability_power = (
        base_stats["ability_power"]
        + total_item_stats["ability_power"]
        + bonuses.bonus_ap
        + runes.ability_power
    )
    # Total AP modifiers stack additively with Rabadon's/Blackfire.
    final_ability_power = raw_ability_power * (
        bonuses.ap_multiplier + quest_ap_multiplier
    )

    # Attack speed: base AS + (AS ratio × total bonus%)
    base_as = champion_data["stats"]["attackSpeed"]["flat"]
    as_ratio = champion_data["stats"].get("attackSpeedRatio", {}).get("flat", base_as)
    level_as_bonus = growth_stat(
        0, champion_data["stats"]["attackSpeed"]["perLevel"], level
    )
    total_as_bonus = (
        level_as_bonus
        + total_item_stats["attack_speed_percent"]
        + bonuses.attack_speed_percent
        + runes.attack_speed_percent
    )
    final_attack_speed = calculate_attack_speed(base_as, as_ratio, total_as_bonus)

    # Lethality is 1:1 flat armor penetration (no level scaling since V14.1)
    lethality = total_item_stats["lethality"] + runes.lethality
    flat_armor_pen = lethality

    effective_bonus_health = (
        total_item_stats["health"] + bonuses.bonus_health
    ) * bonuses.item_bonus_health_multiplier + runes.bonus_health

    # A kit that denies itself a stat rewrites it here, where the build's
    # bonus health is complete: every multiplier and rune grant has landed,
    # which is the order the wiki states (anything raising the health first
    # raises the converted attack damage with it).
    conversion = champion_stat_conversion(champion_data)
    converted_bonus_ad = 0.0
    if conversion is not None:
        converted_bonus_ad = effective_bonus_health * conversion.attack_damage_ratio
        effective_bonus_health = 0.0
    total_health = base_stats["health"] + effective_bonus_health

    raw_bonus_ad = (
        total_item_stats["attack_damage"]
        + bonuses.bonus_ad
        + runes.bonus_attack_damage
        + converted_bonus_ad
    )
    final_bonus_ad = raw_bonus_ad * quest_bonus_ad_multiplier
    total_ad = base_stats["attack_damage"] + final_bonus_ad
    retribution_bonus_ad = input_option_retribution_bonus_ad(
        items,
        item_options,
        total_attack_damage=total_ad,
    )
    final_bonus_ad += retribution_bonus_ad
    total_ad += retribution_bonus_ad
    # Living Weapon counts permanent stats from items plus stat growth, but
    # excludes level-1 stats, adaptive force, role quests, ally buffs, and
    # temporary combat passives. Keep the three owned totals first-class so
    # every optimizer candidate can resolve its own evolution state.
    level_attack_damage_growth = (
        base_stats["attack_damage"] - champion_data["stats"]["attackDamage"]["flat"]
    )
    evolution_attack_damage = (
        level_attack_damage_growth
        + total_item_stats["attack_damage"]
        + bonuses.permanent_bonus_ad
    )
    external_ability_power = float(external.get("ability_power", 0.0))
    item_flat_ability_power = total_item_stats["ability_power"] - external_ability_power
    evolution_ability_power = (
        item_flat_ability_power + bonuses.permanent_bonus_ap
    ) * bonuses.permanent_ap_multiplier
    evolution_attack_speed_percent = (
        level_as_bonus + total_item_stats["attack_speed_percent"]
    )
    # Terminus max-stack display assumption: bonus resists to both armor
    # and MR, percent pen to both armor and magic.
    final_armor = round(
        base_stats["armor"] + total_item_stats["armor"] + bonuses.bonus_resists
    )
    final_mr = round(
        base_stats["magic_resistance"]
        + total_item_stats["magic_resistance"]
        + bonuses.bonus_resists
    )

    final_armor_pen_percent = (
        total_item_stats["armor_penetration_percent"] + bonuses.bonus_pen_percent
    )
    final_magic_pen_percent = (
        total_item_stats["magic_penetration_percent"] + bonuses.bonus_pen_percent
    )
    result = {
        "health": round(total_health),
        "attack_damage": round(total_ad),
        "ability_power": round(final_ability_power),
        "armor": final_armor,
        "magic_resistance": final_mr,
        "attack_speed": final_attack_speed,
        "attack_speed_ratio": as_ratio,
        # Total bonus AS percent (level growth + items + item passives) —
        # champion mechanics that scale with bonus AS (Bel'Veth E's slash
        # count) read this; ability AS steroids add to it at fight time.
        "bonus_attack_speed": total_as_bonus,
        "magic_penetration_flat": (
            total_item_stats["magic_penetration_flat"] + runes.magic_penetration_flat
        ),
        "magic_penetration_percent": final_magic_pen_percent,
        "base_attack_damage": round(base_stats["attack_damage"]),
        "bonus_attack_damage": round(final_bonus_ad),
        "bonus_health": round(effective_bonus_health),
        # Base health = champion base stats + level growth, no items.
        # Derived as total - bonus rather than rounded on its own so
        # ``health == base_health + bonus_health`` holds by construction:
        # rounding the two components independently drifts by 1 whenever
        # base health lands on a .5 boundary (Ambessa/Karthus at 13).
        # Abilities scale off all three separately ("% base health",
        # "% bonus health", "% maximum health"), so each is first-class.
        "base_health": round(total_health) - round(effective_bonus_health),
        # Bonus (non-base) resists — champion mechanics scaling off bonus
        # armor/MR (Braum W's 36%) and the "% bonus armor" /
        # "% bonus magic resistance" scaling units read these.
        "bonus_armor": round(total_item_stats["armor"] + bonuses.bonus_resists),
        "bonus_magic_resistance": round(
            total_item_stats["magic_resistance"] + bonuses.bonus_resists
        ),
        "lethality": lethality,
        "flat_armor_penetration": flat_armor_pen,
        "armor_penetration_percent": final_armor_pen_percent,
        "armor_penetration_bonus_percent": total_item_stats.get(
            "armor_penetration_bonus_percent", 0.0
        ),
        "critical_strike_chance": total_item_stats["critical_strike_chance"],
        "max_mana": round(total_mana),
        "bonus_mana": round(pool_item_mana),
        "resource_regen_per_second": resource_regen_per_second,
        "base_health_regen_per_five": base_health_regen_per_five,
        "health_regen_per_five": health_regen_per_five,
        "health_regen_per_second": health_regen_per_second,
        "lifesteal_percent": grouped_sustain_stat_percent(items, "lifesteal_percent")
        + runes.lifesteal_percent,
        "omnivamp_percent": total_item_stats["omnivamp_percent"]
        + bonuses.bonus_omnivamp,
        "heal_and_shield_power_percent": total_item_stats[
            "heal_and_shield_power_percent"
        ]
        + bonuses.bonus_heal_shield_power * 100.0,
        "health_regen_percent": total_item_stats["health_regen_percent"],
        "tenacity_percent": total_item_stats["tenacity_percent"],
        "gold_per_10": total_item_stats["gold_per_10"],
        "critical_strike_damage_percent": total_item_stats[
            "critical_strike_damage_percent"
        ],
        "ability_haste": (
            total_item_stats["ability_haste"]
            + bonuses.ability_haste
            + runes.ability_haste
        ),
        "basic_ability_haste": bonuses.basic_ability_haste + runes.basic_ability_haste,
        "ultimate_haste": bonuses.ultimate_haste + runes.ultimate_haste,
        "level": level,
        "is_melee": is_melee,
        "move_speed": final_move_speed,
        # The two terms ``resolve_move_speed`` folded, published so a
        # mid-fight percent grant (a champion's own ``move_speed_percent``
        # stat buff) re-folds through the same call instead of trying to
        # decompose the soft-capped scalar.
        "move_speed_flat": move_speed_flat,
        "move_speed_percent": move_speed_percent,
    }
    if champion_data.get("name") == "Kai'Sa":
        result.update(
            {
                "evolution_attack_damage": evolution_attack_damage,
                "evolution_ability_power": evolution_ability_power,
                "evolution_attack_speed_percent": evolution_attack_speed_percent,
            }
        )
    return result


def resolve_pre_combat_stats(  # pylint: disable=too-many-arguments
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    *,
    item_options: Mapping[str, Mapping[str, int]] | None,
    role: str,
    role_quest_complete: bool,
    rune_page: RunePage | None,
    external_stat_bonuses: Mapping[str, float] | None,
) -> dict[str, float]:
    """The one recipe for a participant's stats as combat begins.

    Every input is a required keyword: a participant that receives none of
    a grant answers ``None`` here rather than by leaving an argument out.
    A caller holding a ``FightParams`` asks ``params.pre_combat_stats``,
    which is the one place a request is read into these five.
    """
    return calculate_total_stats(
        champion_data,
        level,
        items,
        item_options=item_options,
        role=role,
        role_quest_complete=role_quest_complete,
        external_stat_bonuses=external_stat_bonuses,
        rune_page=rune_page,
    )
