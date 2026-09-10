"""What a cached item row's stat block is, validated once per data generation."""

import math
from collections.abc import Mapping
from functools import partial
from typing import Any

from .champions import get_champion_stat_conversion
from .data_registry import data_version, store_for_generation
from .interpreters.stat_derivation import armor_penetration_split
from .item_effects import override_item_stat
from .stat_conversion import BonusHealthConversion

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

    def stat_part(stat_name: str, part: str) -> float:
        stat = stats.get(stat_name, {})
        return stat.get(part, 0.0) if isinstance(stat, dict) else 0.0

    get_flat = partial(stat_part, part="flat")
    get_percent = partial(stat_part, part="percent")

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


def champion_stat_conversion(
    champion_data: Mapping[str, Any],
) -> BonusHealthConversion | None:
    """This champion's declared stat conversion, or ``None``."""
    return get_champion_stat_conversion(str(champion_data.get("name", "")))


# Only a MANA pool takes an item's mana: an energy pool is a fixed 200
# (Shen's 400) and no other declared resource grows from items either, so a
# mana item is a wasted stat line on those kits.  A record declaring no
# resource is a sparse unit fixture and keeps the mana pool.
def item_mana_reaches_pool(champion_data: Mapping[str, Any]) -> bool:
    """Whether an item's mana and mana regeneration reach this pool."""
    resource = champion_data.get("resource")
    return resource is None or str(resource) == "MANA"
