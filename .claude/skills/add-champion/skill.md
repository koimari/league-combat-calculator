---
name: add-champion
description: Step-by-step guide for adding a new LoL champion to the calculator. Use when creating a champion module, registering it, or writing champion ability tests.
---

# Add a New Champion

## When You DON'T Need a Custom Module

Most champions (~80%+) are handled automatically by `generic_parser.py` — no code needed. Custom modules are only for unique mechanics. The dispatcher in `champions/__init__.py` checks `_CHAMPION_MODULES` first, then falls through to the generic parser.

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
- **Multi-cast with different damage per cast:** Abilities where each cast does different damage (Aatrox Q — 3 casts summed)
- **Stat-buff ultimates:** R that grants stats (bonus AD, AP, etc.) instead of dealing damage (Aatrox R)
- **Conditional hit counts:** Abilities that hit multiple times conditionally (Aatrox W — initial + pull-back)
- **Passive on-hit with per-level scaling:** Passives where damage scales with champion level (Aatrox P, Akali P) — now auto-extracted from JSON

## No Hardcoded Values

**All numeric values must come from the champion JSON data.** Do not hardcode base damages, scaling ratios, cooldowns, or stat buff percentages. Use:
- `extract_cooldown(ability, rank)` for cooldowns
- `extract_damage(ability, rank, stats, target_stats)` for standard abilities
- `_extract_leveling_damage(ability, attribute_name, rank, stats)` for specific named attributes (when the generic `extract_damage` picks the wrong one)
- `_extract_r_bonus_ad_percent(ability, rank)` pattern for reading specific leveling values

### Per-level scaling data

Champion abilities with "X : Y (based on level)" scaling now have structured leveling data in the JSON. The lolstaticdata scraper extracts actual per-level values from the wiki's `data-bot-values` HTML attributes (typically 20 values for levels 1-20). This captures non-linear growth curves that linear interpolation would get wrong.

**Where it appears:** Per-level data is stored as synthetic leveling entries on the effect that contains the scaling in its description. Common attributes:
- `"Bonus Magic Damage"` — flat per-level damage (e.g., Akali passive)
- `"Max Health Damage"` — % max HP scaling (e.g., Aatrox passive)
- `"Bonus Damage"` — generic per-level bonus damage

**How to use it:** Search `effects[].leveling[]` for the appropriate attribute. The first modifier's `values` array contains the per-level base values. Subsequent modifiers contain scaling ratios (e.g., `"% bonus AD"`, `"% AP"`).

```python
# Example: reading Akali passive per-level damage
for effect in passive.get("effects", []):
    for leveling in effect.get("leveling", []):
        if "damage" in leveling["attribute"].lower():
            base_values = leveling["modifiers"][0]["values"]  # 20 values
            base_at_level = base_values[level - 1]
            # Additional modifiers have scaling ratios
```

**Note:** This only applies to champion abilities. Item per-level scaling uses a separate pipeline (`passive_parser.py`) that currently does linear interpolation and may need a separate fix for non-linear item scaling.

### JSON attribute gotchas

The generic `extract_damage()` uses `attribute_classifier.py` to find the primary damage attribute. It **excludes** attributes containing keywords like "total", "subsequent", "minion", "monster". This means:
- `"Physical Damage"` → picked (single hit)
- `"Total Damage"` → excluded (even though it may be what you want for multi-hit)
- `"First Cast Damage"` → excluded by generic parser, but you can extract it directly

When the generic parser picks the wrong attribute, use `_extract_leveling_damage(ability, "Total Damage", rank, stats)` to target the exact attribute you need.

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
import json, pprint
from src.calculator.data_fetcher import get_champion
champion_data = get_champion("ChampionName")
for slot in ['P', 'Q', 'W', 'E', 'R']:
    ab = champion_data['abilities'][slot][0]
    print(f'=== {slot}: {ab["name"]} ===')
    print(f'damageType: {ab.get("damageType")}')
    print(f'targeting: {ab.get("targeting")}')
    for i, effect in enumerate(ab.get('effects', [])):
        for j, lev in enumerate(effect.get('leveling', [])):
            attr = lev.get('attribute', '')
            mods = [{'values': m['values'][:5], 'units': m['units'][:5]}
                    for m in lev.get('modifiers', [])]
            print(f'  effect[{i}].leveling[{j}]: attr="{attr}" mods={mods}')
```

Cross-reference with the [LoL Wiki](https://wiki.leagueoflegends.com). The JSON data is wiki-scraped and usually accurate, but verify edge cases.

### Step 2: Create the Module

Create `src/calculator/champions/<champion_name>.py`. The full signature for custom modules:

```python
"""Champion ability parsing and damage calculation."""

from typing import Any

from .generic_parser import extract_cooldown, extract_damage
from .scaling import is_flat_unit, resolve_scaling
from .skill_orders import get_ability_rank


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse abilities and calculate damage."""
    ...
```

**Important:** Custom modules receive `champion_options`, `champion_stats`, and `target_stats` from the dispatcher. Use `champion_stats` for AD/HP scaling, `target_stats` for %HP abilities, and `champion_options` for user-configurable toggles.

### Hybrid Approach: Mix Generic + Custom

For champions where most abilities are standard but one is unique, you can parse most from JSON and override just the special one:

```python
from .generic_parser import parse_abilities as generic_parse

def parse_abilities(champion_data, level, total_ability_power, ability_ranks=None,
                    champion_options=None, champion_stats=None, target_stats=None):
    # Let generic parser handle standard abilities
    results = generic_parse(champion_data, level, total_ability_power, ability_ranks,
                            champion_stats=champion_stats, target_stats=target_stats)
    # Override W with custom logic
    results["W"] = _custom_w_logic(...)
    return results
```

### Step 3: Register the Champion

Add to `_CHAMPION_MODULES` in `src/calculator/champions/__init__.py` (keep alphabetical):

```python
_CHAMPION_MODULES: dict[str, str] = {
    "Aatrox": "aatrox",
    "Ahri": "ahri",
    "NewChampion": "new_champion",  # <-- add in alphabetical order
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
| `stat_buff` | Stat-granting abilities (e.g., Aatrox R) | `{"bonus_attack_damage": X}` — applied to `champion_stats` by `damage.py` before fight calculations |

### Stat Buff Abilities (e.g., Aatrox R)

For abilities that grant stats instead of dealing damage:
1. Return the ability with `total_raw: 0.0` and the appropriate damage key set to `0.0`
2. Include a `stat_buff` dict mapping stat keys to bonus values
3. `damage.py` applies stat buffs to `champion_stats` before the fight engine runs, so auto-attack damage benefits from the buff
4. Apply the same buff in your parser's `stats_context` before calculating other abilities, so ability damage also benefits

```python
# Example: R grants 20/30/40% bonus AD
bonus_ad = stats_context["attack_damage"] * bonus_ad_fraction
stats_context["attack_damage"] += bonus_ad
stats_context["bonus_attack_damage"] += bonus_ad

results["R"] = {
    "name": "World Ender",
    "rank": r_rank,
    "cooldown": r_cooldown,
    "damage_type": "physical",
    "total_raw": 0.0,
    "physical_damage": 0.0,
    "stat_buff": {"bonus_attack_damage": bonus_ad},
}
```

## Champion Options (Frontend Toggles)

For champion-specific configuration (e.g., "assume sweetspot hits"), add a frontend toggle:

### Step 1: Register in `static/js/app.js`

Add an entry to `championOptionsDefs` (near the top of the file, after the empty dict declaration):

```javascript
championOptionsDefs["Aatrox"] = {
    render(container) {
        container.innerHTML = `
            <label class="toggle-label compact">
                <input type="checkbox" id="opt-aatrox-sweetspot" checked>
                <span class="toggle-text">Q Sweetspot hits</span>
            </label>`;
        document.getElementById("opt-aatrox-sweetspot")
            .addEventListener("change", scheduleRecalc);
    },
    getValues() {
        return {
            sweetspot: document.getElementById("opt-aatrox-sweetspot")?.checked ?? true,
        };
    },
    assumptions: [
        "Assumed R is always active",
        "W always hits both initial and pull-back damage",
    ],
};
```

**Three functions/properties:**
- `render(container)`: Populates the panel HTML with checkboxes/inputs. **Must** call `scheduleRecalc` on change events for live updates.
- `getValues()`: Returns an object with current settings. This is sent as `champion_options` in the API payload.
- `assumptions`: Array of strings displayed in the "Champion Assumptions" section below the damage breakdown. Use for any simplifying assumptions the calculator makes (e.g., "R always active", "all hits land", "full stacks assumed").

The panel **auto-opens** when selecting a champion that has options defined. Champions without options show "No special options for this champion." when manually opened via the "+" button.

### Step 2: Consume in the Champion Module

The `champion_options` dict is passed through: `app.js → app.py → __init__.py → your_module.parse_abilities()`. Access it in your parser:

```python
def parse_abilities(..., champion_options=None, ...):
    sweetspot = True  # default
    if champion_options and "sweetspot" in champion_options:
        sweetspot = bool(champion_options["sweetspot"])
```

### ID Convention

Use `id="opt-<champion>-<option>"` for option input elements to avoid collisions.

## Champion Assumptions

When a champion module makes simplifying assumptions (e.g., R is always active, all hits land), document them in the `assumptions` array of the champion's `championOptionsDefs` entry. These display as a list below the damage breakdown in the results panel.

Common assumptions to document:
- Stat buff ultimates always active (e.g., "Assumed R is always active")
- Conditional damage always lands (e.g., "W always hits both initial and pull-back damage")
- Passive always available / off cooldown
- Full stacks assumed
- All projectiles hit

## Adding Tests

Create `tests/test_<champion>.py` for custom modules. Shared fixtures are in `tests/conftest.py`:

- **`<champion>_data`** — fixture that loads champion JSON (add new ones to conftest.py)
- **`parse_at`** — factory fixture: `stats, abilities = parse_at(data, level, *, items=None, ap=0.0, **kwargs)` — calculates stats and parses abilities in one call via the dispatcher

```python
# tests/conftest.py — add a new data fixture for each champion:
@pytest.fixture
def champion_data() -> dict:
    return get_champion("ChampionName")
```

```python
# tests/test_<champion>.py — use shared fixtures:
from src.calculator.champions.<champion> import _private_helper  # only if needed
from src.calculator.damage import calculate_fight_damage


class TestQAbilityName:
    def test_q_is_physical_damage(self, champion_data, parse_at) -> None:
        _, abilities = parse_at(champion_data, 9)
        assert abilities["Q"]["damage_type"] == "physical"

    def test_q_has_cooldown(self, champion_data, parse_at) -> None:
        _, abilities = parse_at(champion_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_with_options(self, champion_data, parse_at) -> None:
        _, abilities = parse_at(
            champion_data, 9, champion_options={"sweetspot": True},
        )
        assert abilities["Q"]["total_raw"] > 0
```

### Test categories to cover:

1. **Each ability's damage type** (physical/magic/true/mixed)
2. **Damage values match JSON data** (use `parse_at` which includes stat calculation)
3. **Cooldowns are present and positive**
4. **Champion options toggle behavior** (sweetspot on vs off, etc.)
5. **Non-damaging abilities excluded** (E not in results if utility)
6. **Stat buff abilities** (R deals 0 damage, has stat_buff key, buff value is correct)
7. **Fight engine integration** (stat_buff applied to champion_stats, R 0 damage in breakdown)
8. **Level awareness** (test at levels where R is/isn't ranked to avoid R buff distortion)
9. **On-hit passive** (correct damage type, scales with level, correct % values)

**Important:** When testing ability damage at levels where R is ranked, the R stat buff will be applied. If comparing manual calculations to parser output, use a level where R is not yet ranked (pre-level 6) to avoid the buff distorting the comparison.

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

## Reference Implementations

See `src/calculator/champions/scaling.py` for the full unit-string → stat-key mapping used by scaling resolution.

When writing a new custom module, study these existing ones for patterns:
- **`aatrox.py`** (preferred pattern): JSON-driven, 3-cast Q with sweetspot option, R stat buff, W double-hit, passive on-hit from per-level data.
- **`akali.py`**: JSON-driven, E total (both hits), R with missing-HP scaling, passive with user-configurable proc count.
- **`ahri.py`**: JSON-driven, mixed damage Q (magic + true), multi-part W (initial + subsequent), multi-dash R (3 casts).
