"""Module for calculating champion stats at any level with items applied."""

from typing import Any

from .item_effects import ITEM_EFFECTS, get_terminus_light_resist_per_stack


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


def get_champion_base_stats(champion_data: dict[str, Any], level: int) -> dict[str, float]:
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
        stats["attackDamage"]["perLevel"], level,
    )
    armor = growth_stat(stats["armor"]["flat"], stats["armor"]["perLevel"], level)
    magic_resistance = growth_stat(
        stats["magicResistance"]["flat"],
        stats["magicResistance"]["perLevel"], level,
    )

    # Attack speed uses percentage growth with separate AS ratio
    as_ratio = stats.get("attackSpeedRatio", {}).get("flat", stats["attackSpeed"]["flat"])
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


def check_item_passives(item_data: dict[str, Any]) -> dict[str, Any]:
    """Check for relevant item passives that affect stats or damage.

    Args:
        item_data: Item data dictionary from the CDN.

    Returns:
        Dictionary of passive effects found.
    """
    passives = {}
    item_name = item_data.get("name", "")
    effect = ITEM_EFFECTS.get(item_name, {})

    if item_name == "Rabadon's Deathcap":
        ap_increase = effect.get("ap_percent_increase", 0.30)
        passives["ability_power_multiplier"] = 1.0 + ap_increase

    if item_name == "Blackfire Torch":
        # Assume 1 burning target for single-target calc
        ap_amp = effect.get("ap_amp_per_target", 0.04)
        passives["ability_power_multiplier"] = 1.0 + ap_amp

    return passives


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

    item_passives: list[dict[str, Any]] = []

    for item in items:
        item_stats = get_item_stats(item)
        for key in total_item_stats:
            total_item_stats[key] += item_stats.get(key, 0.0)
        passives = check_item_passives(item)
        if passives:
            item_passives.append(passives)

    # Aggregate ability power before multiplier
    raw_ability_power = base_stats["ability_power"] + total_item_stats["ability_power"]

    # Archangel's Staff Awe passive: bonus mana as AP
    for item in items:
        if item.get("name") == "Archangel's Staff":
            effect = ITEM_EFFECTS.get("Archangel's Staff", {})
            ratio = effect.get("bonus_mana_to_ap_ratio", 0.01)
            raw_ability_power += ratio * total_item_stats["mana"]
            break

    # Seraph's Embrace Awe passive: bonus mana as AP
    for item in items:
        if item.get("name") == "Seraph's Embrace":
            effect = ITEM_EFFECTS.get("Seraph's Embrace", {})
            ratio = effect.get("bonus_mana_to_ap_ratio", 0.02)
            raw_ability_power += ratio * total_item_stats["mana"]
            break

    # Dawncore First Light passive: AP per additional base mana regen
    for item in items:
        if item.get("name") == "Dawncore":
            effect = ITEM_EFFECTS.get("Dawncore", {})
            ap_per_unit = effect.get("ap_per_mana_regen_unit", 10.0)
            threshold = effect.get("mana_regen_threshold_percent", 100.0)
            bonus_mana_regen = total_item_stats["mana_regen_percent"]
            raw_ability_power += (bonus_mana_regen / threshold) * ap_per_unit
            break

    # Staff of Flowing Water Rapids: bonus AP (assumed always active)
    for item in items:
        if item.get("name") == "Staff of Flowing Water":
            effect = ITEM_EFFECTS.get("Staff of Flowing Water", {})
            raw_ability_power += effect.get("rapids_bonus_ap", 45.0)
            break

    # Apply AP multipliers (Rabadon's, Blackfire Torch, etc.) additively
    # In LoL, %AP increases stack additively: 30% + 4% = 34%, not 1.30 × 1.04
    ap_bonus_percent = 0.0
    for passive in item_passives:
        if "ability_power_multiplier" in passive:
            ap_bonus_percent += passive["ability_power_multiplier"] - 1.0
    ap_multiplier = 1.0 + ap_bonus_percent

    final_ability_power = raw_ability_power * ap_multiplier

    # Attack speed: base AS + (AS ratio × total bonus%)
    base_as = champion_data["stats"]["attackSpeed"]["flat"]
    as_ratio = champion_data["stats"].get("attackSpeedRatio", {}).get("flat", base_as)
    level_as_bonus = growth_stat(0, champion_data["stats"]["attackSpeed"]["perLevel"], level)
    total_as_bonus = level_as_bonus + total_item_stats["attack_speed_percent"]

    # Bandlepipes Fanfare passive: bonus AS (melee/ranged)
    is_melee = champion_data.get("attackType", "MELEE") == "MELEE"
    for item in items:
        if item.get("name") == "Bandlepipes":
            effect = ITEM_EFFECTS.get("Bandlepipes", {})
            if is_melee:
                total_as_bonus += effect.get("bonus_attack_speed_melee", 30.0)
            else:
                total_as_bonus += effect.get("bonus_attack_speed_ranged", 20.0)
            break

    # Experimental Hexplate Overdrive: bonus AS on R cast
    # Assumed always active since R is cast at fight start
    for item in items:
        if item.get("name") == "Experimental Hexplate":
            effect = ITEM_EFFECTS.get("Experimental Hexplate", {})
            total_as_bonus += effect.get("bonus_attack_speed_percent", 50.0)
            break

    # Yun Tal Wildarrows Flurry: bonus AS after attacking a champion
    # Assumed always active since the champion is auto-attacking
    for item in items:
        if item.get("name") == "Yun Tal Wildarrows":
            effect = ITEM_EFFECTS.get("Yun Tal Wildarrows", {})
            total_as_bonus += effect.get("bonus_attack_speed_percent", 30.0)
            break

    final_attack_speed = calculate_attack_speed(base_as, as_ratio, total_as_bonus)

    # Lethality converts to flat armor pen based on level
    lethality = total_item_stats["lethality"]
    flat_armor_pen = lethality * (0.6 + 0.4 * min(level, 18) / 18)

    # Mana: base + growth + items
    cdm = champion_data["stats"]
    base_mana = growth_stat(
        cdm.get("mana", {}).get("flat", 0),
        cdm.get("mana", {}).get("perLevel", 0),
        level,
    )
    total_mana = base_mana + total_item_stats["mana"]

    # Muramana Awe passive: max mana as bonus AD
    muramana_bonus_ad = 0.0
    for item in items:
        if item.get("name") == "Muramana":
            effect = ITEM_EFFECTS.get("Muramana", {})
            ratio = effect.get("max_mana_to_ad_ratio", 0.02)
            muramana_bonus_ad = ratio * total_mana
            break

    # Overlord's Bloodmail Tyranny passive: bonus health as bonus AD
    bloodmail_bonus_ad = 0.0
    for item in items:
        if item.get("name") == "Overlord's Bloodmail":
            effect = ITEM_EFFECTS.get("Overlord's Bloodmail", {})
            ratio = effect.get("bonus_health_to_ad_ratio", 0.025)
            bloodmail_bonus_ad = ratio * total_item_stats["health"]
            break

    # Sterak's Gage The Claws that Catch: base AD as bonus AD
    steraks_bonus_ad = 0.0
    for item in items:
        if item.get("name") == "Sterak's Gage":
            effect = ITEM_EFFECTS.get("Sterak's Gage", {})
            ratio = effect.get("base_ad_to_bonus_ad_ratio", 0.45)
            steraks_bonus_ad = ratio * base_stats["attack_damage"]
            break

    total_ad = (
        base_stats["attack_damage"]
        + total_item_stats["attack_damage"]
        + muramana_bonus_ad
        + bloodmail_bonus_ad
        + steraks_bonus_ad
    )
    total_health = base_stats["health"] + total_item_stats["health"]

    # Terminus Juxtaposition: light hits grant bonus armor + MR (max stacks),
    # dark hits grant % armor + magic pen (max stacks).
    # Assumed at max stacks since the champion is auto-attacking.
    terminus_bonus_resist = 0.0
    terminus_pen = 0.0
    for item in items:
        if item.get("name") == "Terminus":
            effect = ITEM_EFFECTS.get("Terminus", {})
            resist_per_stack = get_terminus_light_resist_per_stack(level)
            max_stacks = effect.get("dark_max_stacks", 3)
            terminus_bonus_resist = resist_per_stack * max_stacks
            pen_per_stack = effect.get("dark_pen_per_stack", 0.10)
            terminus_pen = pen_per_stack * max_stacks * 100.0  # as percentage
            break

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
        "basic_ability_haste": _get_basic_ability_haste(items),
        "level": level,
        "is_melee": is_melee,
    }


def _get_basic_ability_haste(items: list[dict[str, Any]]) -> float:
    """Sum basic ability haste from items (applies to Q, W, E only).

    Args:
        items: List of item data dictionaries.

    Returns:
        Total basic ability haste.
    """
    total = 0.0
    for item in items:
        if item.get("name") == "Spear of Shojin":
            effect = ITEM_EFFECTS.get("Spear of Shojin", {})
            total += effect.get("basic_ability_haste", 25.0)
    return total
