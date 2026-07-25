"""Module for calculating champion stats at any level with items applied."""

from typing import Any

from .item_effects import resolve_stat_effects

# Level cap — 20 is top-lane-only as of this season, so this is
# season-volatile. Single source of truth: the API guards and the UI
# slider (via the index template) both read this constant.
MAX_LEVEL = 20


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
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"Level must be between 1 and {MAX_LEVEL}, got {level}")
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

    # Mana first — stat conversions read it (Awe → AP, Muramana → AD)
    cdm = champion_data["stats"]
    base_mana = growth_stat(
        cdm.get("mana", {}).get("flat", 0),
        cdm.get("mana", {}).get("perLevel", 0),
        level,
    )
    total_mana = base_mana + total_item_stats["mana"]
    is_melee = champion_data.get("attackType", "MELEE") == "MELEE"

    # Every stat-granting item passive, compiled once. item_effects owns
    # the per-item knowledge; this function owns the application order.
    bonuses = resolve_stat_effects(
        items,
        bonus_mana=total_item_stats["mana"],
        max_mana=total_mana,
        bonus_health=total_item_stats["health"],
        base_attack_damage=base_stats["attack_damage"],
        bonus_mana_regen_percent=total_item_stats["mana_regen_percent"],
        is_melee=is_melee,
        level=level,
    )

    # Ability power: base + items + converted AP, then the additive %AP
    # multiplier (Rabadon's, Blackfire Torch).
    raw_ability_power = (
        base_stats["ability_power"]
        + total_item_stats["ability_power"]
        + bonuses.bonus_ap
    )
    final_ability_power = raw_ability_power * bonuses.ap_multiplier

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
    )
    final_attack_speed = calculate_attack_speed(base_as, as_ratio, total_as_bonus)

    # Lethality is 1:1 flat armor penetration (no level scaling since V14.1)
    lethality = total_item_stats["lethality"]
    flat_armor_pen = lethality

    total_ad = (
        base_stats["attack_damage"]
        + total_item_stats["attack_damage"]
        + bonuses.bonus_ad
    )
    total_health = base_stats["health"] + total_item_stats["health"]

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

    return {
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
        "magic_penetration_flat": total_item_stats["magic_penetration_flat"],
        "magic_penetration_percent": final_magic_pen_percent,
        "base_attack_damage": round(base_stats["attack_damage"]),
        "bonus_attack_damage": round(
            total_item_stats["attack_damage"] + bonuses.bonus_ad
        ),
        "bonus_health": round(total_item_stats["health"]),
        # Base health = champion base stats + level growth, no items.
        # Derived as total - bonus rather than rounded on its own so
        # ``health == base_health + bonus_health`` holds by construction:
        # rounding the two components independently drifts by 1 whenever
        # base health lands on a .5 boundary (Ambessa/Karthus at 13).
        # Abilities scale off all three separately ("% base health",
        # "% bonus health", "% maximum health"), so each is first-class.
        "base_health": round(total_health) - round(total_item_stats["health"]),
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
        "critical_strike_chance": total_item_stats["critical_strike_chance"],
        "max_mana": round(total_mana),
        "bonus_mana": round(total_item_stats["mana"]),
        "ability_haste": total_item_stats["ability_haste"],
        "basic_ability_haste": bonuses.basic_ability_haste,
        "level": level,
        "is_melee": is_melee,
    }
