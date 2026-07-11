"""Module for calculating champion stats at any level with items applied."""

from typing import Any

from .item_effects import (
    get_ap_multiplier,
    get_basic_ability_haste,
    get_bloodmail_bonus_ad,
    get_dawncore_bonus_ap,
    get_flowing_water_bonus_ap,
    get_mana_to_ap_bonus,
    get_muramana_bonus_ad,
    get_passive_attack_speed_bonus,
    get_steraks_bonus_ad,
    get_terminus_max_stack_bonuses,
)
from .resistance import lethality_to_flat_pen


def growth_stat(base: float, growth: float, level: int) -> float:
    """Calculate a champion stat at a given level using the LoL growth formula.

    Formula: base + growth * (level - 1) * (0.7025 + 0.0175 * (level - 1))

    Args:
        base: The base stat value at level 1.
        growth: The per-level growth value.
        level: Champion level (1-20).

    Returns:
        The stat value at the given level (not rounded).
    """
    if level < 1 or level > 20:
        raise ValueError(f"Level must be between 1 and 20, got {level}")
    return base + growth * (level - 1) * (0.7025 + 0.0175 * (level - 1))


def calculate_attack_speed(
    base_attack_speed: float,
    attack_speed_ratio: float,
    bonus_percent: float,
) -> float:
    """Calculate total attack speed.

    Formula: base AS + (AS ratio × bonus AS%)
    The AS ratio is a per-champion value separate from base AS.
    See: https://wiki.leagueoflegends.com/en-us/Attack_speed

    Args:
        base_attack_speed: Champion's base attack speed at level 1.
        attack_speed_ratio: Champion's attack speed ratio (scaling factor).
        bonus_percent: Total bonus attack speed as a percentage (e.g., 20.0 for 20%).

    Returns:
        Total attacks per second.
    """
    return base_attack_speed + attack_speed_ratio * (bonus_percent / 100.0)


def get_champion_base_stats(
    champion_data: dict[str, Any], level: int
) -> dict[str, float]:
    """Calculate a champion's base stats at a given level (no items).

    Args:
        champion_data: Champion data dictionary from the CDN.
        level: Champion level (1-18).

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
    }


def get_item_stats(item_data: dict[str, Any]) -> dict[str, float]:
    """Extract stat bonuses from an item.

    Args:
        item_data: Item data dictionary from the CDN.

    Returns:
        Dictionary with stat names and their flat values.
    """
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

    return {
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
        "armor_penetration_percent": get_percent("armorPenetration"),
        "critical_strike_chance": (
            get_flat("criticalStrikeChance") + get_percent("criticalStrikeChance")
        ),
        "mana": get_flat("mana"),
        "ability_haste": get_flat("abilityHaste"),
        "mana_regen_percent": get_percent("manaRegen"),
    }


def calculate_total_stats(
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
) -> dict[str, float]:
    """Calculate total champion stats with items applied.

    Args:
        champion_data: Champion data dictionary from the CDN.
        level: Champion level (1-20).
        items: List of item data dictionaries.

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
        "critical_strike_chance": 0.0,
        "mana": 0.0,
        "ability_haste": 0.0,
        "mana_regen_percent": 0.0,
    }

    for item in items:
        item_stats = get_item_stats(item)
        for key in total_item_stats:
            total_item_stats[key] += item_stats.get(key, 0.0)

    # Ability power: base + items + stat-converting passives, then the
    # additive %AP multiplier (Rabadon's, Blackfire Torch).
    raw_ability_power = base_stats["ability_power"] + total_item_stats["ability_power"]
    raw_ability_power += get_mana_to_ap_bonus(items, total_item_stats["mana"])
    raw_ability_power += get_dawncore_bonus_ap(
        items, total_item_stats["mana_regen_percent"]
    )
    raw_ability_power += get_flowing_water_bonus_ap(items)

    final_ability_power = raw_ability_power * get_ap_multiplier(items)

    # Attack speed: base AS + (AS ratio × total bonus%)
    base_as = champion_data["stats"]["attackSpeed"]["flat"]
    as_ratio = champion_data["stats"].get("attackSpeedRatio", {}).get("flat", base_as)
    level_as_bonus = growth_stat(
        0, champion_data["stats"]["attackSpeed"]["perLevel"], level
    )
    total_as_bonus = level_as_bonus + total_item_stats["attack_speed_percent"]

    # Assumed-active AS passives (Bandlepipes, Hexplate, Yun Tal)
    is_melee = champion_data.get("attackType", "MELEE") == "MELEE"
    total_as_bonus += get_passive_attack_speed_bonus(items, is_melee)

    final_attack_speed = calculate_attack_speed(base_as, as_ratio, total_as_bonus)

    # Lethality converts to flat armor pen based on level
    lethality = total_item_stats["lethality"]
    flat_armor_pen = lethality_to_flat_pen(lethality, level)

    # Mana: base + growth + items
    cdm = champion_data["stats"]
    base_mana = growth_stat(
        cdm.get("mana", {}).get("flat", 0),
        cdm.get("mana", {}).get("perLevel", 0),
        level,
    )
    total_mana = base_mana + total_item_stats["mana"]

    # Stat-to-AD conversion passives (Muramana, Bloodmail, Sterak's)
    muramana_bonus_ad = get_muramana_bonus_ad(items, total_mana)
    bloodmail_bonus_ad = get_bloodmail_bonus_ad(items, total_item_stats["health"])
    steraks_bonus_ad = get_steraks_bonus_ad(items, base_stats["attack_damage"])

    total_ad = (
        base_stats["attack_damage"]
        + total_item_stats["attack_damage"]
        + muramana_bonus_ad
        + bloodmail_bonus_ad
        + steraks_bonus_ad
    )
    total_health = base_stats["health"] + total_item_stats["health"]

    # Terminus Juxtaposition: light hits grant bonus armor + MR, dark hits
    # grant % armor + magic pen. Assumed at max stacks while auto-attacking.
    terminus_bonus_resist, terminus_pen = get_terminus_max_stack_bonuses(items, level)

    final_armor = round(
        base_stats["armor"] + total_item_stats["armor"] + terminus_bonus_resist
    )
    final_mr = round(
        base_stats["magic_resistance"]
        + total_item_stats["magic_resistance"]
        + terminus_bonus_resist
    )

    final_armor_pen_percent = (
        total_item_stats["armor_penetration_percent"] + terminus_pen
    )
    final_magic_pen_percent = (
        total_item_stats["magic_penetration_percent"] + terminus_pen
    )

    return {
        "health": round(total_health),
        "attack_damage": round(total_ad),
        "ability_power": round(final_ability_power),
        "armor": final_armor,
        "magic_resistance": final_mr,
        "attack_speed": final_attack_speed,
        "attack_speed_ratio": as_ratio,
        "magic_penetration_flat": total_item_stats["magic_penetration_flat"],
        "magic_penetration_percent": final_magic_pen_percent,
        "base_attack_damage": round(base_stats["attack_damage"]),
        "bonus_attack_damage": round(
            total_item_stats["attack_damage"]
            + muramana_bonus_ad
            + bloodmail_bonus_ad
            + steraks_bonus_ad
        ),
        "bonus_health": round(total_item_stats["health"]),
        "lethality": lethality,
        "flat_armor_penetration": flat_armor_pen,
        "armor_penetration_percent": final_armor_pen_percent,
        "critical_strike_chance": total_item_stats["critical_strike_chance"],
        "max_mana": round(total_mana),
        "bonus_mana": round(total_item_stats["mana"]),
        "ability_haste": total_item_stats["ability_haste"],
        "basic_ability_haste": get_basic_ability_haste(items),
        "level": level,
        "is_melee": is_melee,
    }
