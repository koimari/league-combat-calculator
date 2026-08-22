"""The stat block a champion parse takes, with every modifier at zero.

``parse_champion_abilities`` prices a row against a full stat dict, and the
ledger tests all want the same one: no penetration, no haste, no crit, so a
row's number is the row's own.  ``conftest.attacker_stats`` is the *engine*
shape (2000 HP, 50 armor, real resistances) and answers a different question.

This is a test helper, not a test module: it holds no assertions.
"""


def parse_stats(level: int) -> dict:
    """Every stat a parse reads, zeroed but for the reference 100 AD / 0.8 AS."""
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 300.0,
        "resource_regen_per_second": 0.0,
        "level": level,
    }
