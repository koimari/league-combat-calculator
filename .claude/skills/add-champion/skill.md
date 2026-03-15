---
name: add-champion
description: Step-by-step guide for adding a new LoL champion to the calculator. Use when creating a champion module, registering it, or writing champion ability tests.
---

# Add a New Champion

## Architecture Overview

Most champions (~80%+) are handled **automatically** by the generic parser — no code needed. Custom modules are only required for champions with unique mechanics.

```
src/calculator/champions/
├── __init__.py              # Registry: custom modules → generic parser fallback
├── common.py                # Shared: calculate_ability_damage, effective_cooldown
├── generic_parser.py        # Generic JSON parser — handles most champions automatically
├── scaling.py               # Unit string → stat resolution ("% AP", "% bonus AD", etc.)
├── attribute_classifier.py  # Detects damage vs utility attributes in JSON
├── skill_orders.py          # Default Q>W>E skill order + per-champion overrides
├── ahri.py                  # Custom: Ahri (mixed Q, multi-part W, multi-dash R)
└── <champion>.py            # Custom modules for other unique champions
```

### How it works

1. `__init__.py` checks if a custom module exists in `_CHAMPION_MODULES`
2. If yes → dispatches to that module's `parse_abilities()`
3. If no → falls through to `generic_parser.py` which reads directly from JSON

**Key principle:** `damage.py` is the generic fight engine. It uses **field-based dispatch** (checks for `"initial_damage"`, `"damage_per_cast"`, `"on_hit"` fields) rather than ability-key checks (`ability_key == "W"`), so it works with any champion.

## When You DON'T Need a Custom Module

The generic parser handles champions with:
- Standard Q/W/E/R abilities with base + ratio scaling
- AP, AD, bonus AD, %HP, armor, MR, mana scaling
- Physical, magic, true, or mixed damage types
- Passive on-hit effects (e.g., Vayne W detected via `targeting: "Passive"`)
- Any combination of flat + percentage scaling modifiers

**To add such a champion:** No code needed! The generic parser reads the JSON automatically. You may optionally add a skill order override in `skill_orders.py` if the champion doesn't use Q>W>E max order.

## When You DO Need a Custom Module

Create a custom module for champions with:
- **Transform kits:** Jayce, Nidalee, Elise (two ability sets)
- **Sub-ability selection:** Hwei (12+ sub-abilities), Karma (R-empowered Q/W/E)
- **Weapon systems:** Aphelios (weapon-dependent abilities)
- **No traditional R:** Udyr (all stances)
- **External stacking:** Nasus Q stacks, Veigar passive AP, Senna souls
- **Multi-part damage:** Abilities with initial + subsequent hits at different ratios (Ahri W)
- **Multi-cast abilities:** Abilities with N dashes/casts per use (Ahri R)

## Adding a Skill Order Override

If the champion maxes W or E first (instead of default Q>W>E), add to `skill_orders.py`:

```python
_SKILL_ORDERS: dict[str, list[str]] = {
    "Kog'Maw": [
        "Q", "W", "E", "W", "W", "R",
        "W", "Q", "W", "Q", "R", "Q",
        "Q", "E", "E", "R", "E", "E",
    ],
}
```

R is always at levels 6, 11, 16. The remaining 15 levels distribute Q/W/E.

## Creating a Custom Champion Module

### Step 1: Examine the Champion's JSON Data

```python
from src.calculator.data_fetcher import get_champion
champion_data = get_champion("Lux")
# Inspect: champion_data["abilities"]["Q"][0]["effects"][0]["leveling"]
```

Cross-reference with the [LoL Wiki](https://wiki.leagueoflegends.com). The JSON data is wiki-scraped and usually accurate, but verify edge cases.

### Step 2: Create the Module

Create `src/calculator/champions/<champion_name>.py`. You can import shared utilities:

```python
"""Lux ability parsing and damage calculation."""

from typing import Any

from .common import calculate_ability_damage
from .generic_parser import extract_cooldown, extract_damage  # Reuse JSON extraction
from .scaling import resolve_scaling                           # Reuse scaling math
from .skill_orders import get_ability_rank                     # Reuse rank calculation


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse Lux's abilities and calculate damage."""
    results: dict[str, dict[str, Any]] = {}

    def rank_for(key: str) -> int:
        if ability_ranks and key in ability_ranks:
            return ability_ranks[key]
        return get_ability_rank(key, level, "Lux")

    # Q - Light Binding
    q_rank = rank_for("Q")
    if q_rank > 0:
        q_base = [80, 120, 160, 200, 240][q_rank - 1]
        q_damage = calculate_ability_damage(q_base, 0.60, total_ability_power)
        results["Q"] = {
            "name": "Light Binding",
            "rank": q_rank,
            "cooldown": 11.0,  # or extract from JSON via extract_cooldown()
            "magic_damage": q_damage,
            "total_raw": q_damage,
            "damage_type": "magic",
        }

    # ... W, E, R follow the same pattern ...
    return results
```

### Hybrid Approach: Mix Generic + Custom

For champions where most abilities are standard but one is unique, you can parse most from JSON and override just the special one:

```python
from .generic_parser import parse_abilities as generic_parse

def parse_abilities(champion_data, level, total_ability_power, ability_ranks=None):
    # Let generic parser handle Q, E, R
    results = generic_parse(champion_data, level, total_ability_power, ability_ranks)
    # Override W with custom logic
    results["W"] = _custom_w_logic(...)
    return results
```

### Step 3: Register the Champion

Add to `_CHAMPION_MODULES` in `src/calculator/champions/__init__.py` (keep alphabetical):

```python
_CHAMPION_MODULES: dict[str, str] = {
    "Ahri": "ahri",
    "Lux": "lux",     # <-- add this line
}
```

Only champions in this dict use custom modules. All others automatically use the generic parser.

## Required Ability Fields

Every ability returned by `parse_abilities()` **must** include:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Display name (e.g., "Light Binding") |
| `rank` | `int` | Current rank (1-5 for basic, 1-3 for R) |
| `cooldown` | `float` | Base cooldown in seconds at current rank |
| `total_raw` | `float` | Total raw damage before resistances |
| `damage_type` | `str` | `"magic"`, `"physical"`, `"true"`, or `"mixed"` |

### Optional Fields (field-based dispatch in fight engine)

| Field | When to Use | Fight Engine Behavior |
|---|---|---|
| `magic_damage` | Magic type | Used for magic resistance calculation |
| `physical_damage` | Physical type | Used for armor calculation |
| `true_damage` | True/mixed type | Bypasses resistances |
| `initial_damage` + `subsequent_damage` | Multi-part (e.g., Fox-Fire) | 1 initial + 2 subsequent per cast |
| `damage_per_cast` + `total_casts` | Multi-dash (e.g., Spirit Rush) | N hits per ability use |
| `on_hit` | Passive on-hit | `{"name": "...", "damage_per_hit": X, "damage_type": "..."}` |

## Adding Tests

Add tests to `tests/test_generic_parser.py` (for generic parser champions) or create `tests/test_<champion>.py` for custom modules:

```python
class TestLuxAbilities:
    def test_q_rank5_with_500ap(self) -> None:
        abilities = parse_abilities({}, 18, 500.0)
        assert abs(abilities["Q"]["magic_damage"] - 540.0) < 0.1

    def test_damage_type(self) -> None:
        abilities = parse_abilities({}, 18, 0.0)
        assert abilities["Q"]["damage_type"] == "magic"
```

## Verify

```bash
pytest
```

All existing tests plus your new ones must pass.

## Data Accuracy

- The JSON data is scraped from the LoL Wiki and auto-updates via "Update to latest patch"
- For custom modules, cross-reference the [LoL Wiki](https://wiki.leagueoflegends.com)
- If the wiki disagrees with JSON data, trust the wiki and note the discrepancy
- Known-good test cases (validated against the game client) go in `tests/test_known_good.py`

## Scaling Unit Reference

Common unit strings in JSON and what stats they resolve against:

| Unit String | Stat Key | Example |
|---|---|---|
| `""` (empty) | Flat damage | `100` base damage |
| `"% AP"` | `ability_power` | `50% AP` |
| `"% AD"` | `attack_damage` | `100% AD` |
| `"% bonus AD"` | `bonus_attack_damage` | `75% bonus AD` |
| `"% bonus health"` | `bonus_health` | `8% bonus health` |
| `"% maximum health"` | `health` | `10% max health` |
| `"% of target's maximum health"` | `target_max_health` | `6% target max HP` |
| `"% of target's current health"` | `target_current_health` | `9% current HP` |
| `"% of target's missing health"` | `target_missing_health` | `8% missing HP` |
| `"% armor"` / `"% bonus armor"` | `armor` | `40% armor` |
| `"% magic resistance"` | `magic_resistance` | `50% MR` |
| `"% maximum mana"` / `"% bonus mana"` | `max_mana` / `bonus_mana` | `2% max mana` |

Full mapping in `src/calculator/champions/scaling.py`.
