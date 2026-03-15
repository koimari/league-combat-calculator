---
name: lol-damage-formulas
description: LoL damage formulas, stat growth, resistance math, and data structures. Loaded when working on damage calculations, stat computations, or debugging accuracy.
user-invocable: false
---

# League of Legends Damage Formulas

## Damage Calculation

```
Final Damage = Base Damage + (Scaling Ratio x Champion Stat)
```

Example: Ability deals 100 + (60% AP). If champion has 500 AP:
`100 + (0.6 x 500) = 400` raw damage before resistances.

Implementation: `src/calculator/champions/common.py` → `calculate_ability_damage()`

## Resistance Math

```
Actual Damage = Raw Damage x (100 / (100 + Resistance))
```

- Positive resistance reduces damage (e.g., 100 armor = 50% reduction)
- Negative resistance amplifies damage (e.g., -50 MR = 33% more damage taken)
- True damage ignores all resistances entirely

```
Effective HP = Actual HP x (100 + Armor) / 100
```

Implementation: `src/calculator/resistance.py` → `apply_resistance()`

## Penetration

Penetration applies in this order:
1. **Percent penetration** first: `effective_resist = target_resist x (1 - percent_pen)`
2. **Flat penetration** second: `effective_resist = result - flat_pen`
3. Result cannot go below 0

**Lethality** converts to flat armor penetration based on level:
```
flat_armor_pen = lethality x (0.6 + 0.4 x min(level, 18) / 18)
```

Implementation: `resistance.py` → `apply_magic_penetration()`, `apply_armor_penetration()`
Lethality conversion: `stats.py` → `calculate_total_stats()`

## Stat Growth

Champion stats scale per level using:
```
stat_at_level = base + growth x (level - 1) x (0.7025 + 0.0175 x (level - 1))
```

Implementation: `src/calculator/stats.py` → `growth_stat()`

## Attack Speed

```
total_attack_speed = base_AS + AS_ratio x (bonus_percent / 100)
```

Note: `AS_ratio` is a separate champion stat from `base_AS`. Found in `championData["attackSpeedRatio"]["flat"]`.

Implementation: `stats.py` → `calculate_attack_speed()`

## Damage Types

| Type | Reduced by | Notes |
|---|---|---|
| Physical | Armor | Most auto attacks and AD abilities |
| Magic | Magic Resistance | Most AP abilities |
| True | Nothing | Ignores all resistances |
| Mixed | Split | E.g., Ahri Q: outgoing = magic, returning = true |

## Champion Data Structure (from Meraki CDN)

```json
{
  "name": "Champion Name",
  "stats": {
    "health": {"flat": 580, "perLevel": 90},
    "attackDamage": {"flat": 60, "perLevel": 3},
    "armor": {"flat": 26, "perLevel": 4.7},
    "magicResistance": {"flat": 30, "perLevel": 1.3}
  },
  "abilities": {
    "Q": [{"effects": [{"leveling": [...]}]}]
  }
}
```

## Item Data Structure (from Meraki CDN)

```json
{
  "name": "Item Name",
  "stats": {
    "abilityPower": {"flat": 80},
    "health": {"flat": 350}
  },
  "shop": {"prices": {"total": 3000}}
}
```

## Reference Links

- [Damage](https://wiki.leagueoflegends.com/en-us/Damage)
- [Armor](https://wiki.leagueoflegends.com/en-us/Armor)
- [Magic Resistance](https://wiki.leagueoflegends.com/en-us/Magic_resistance)
- Use wiki.leagueoflegends.com to look up specific champion information
