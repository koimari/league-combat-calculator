---
name: add-item-effect
description: Guide for adding item passive/active effects to the LoL calculator. Use when implementing on-hit effects, spellblade, burn/DoT, ability amplifiers, or stat-granting passives.
---

# Add an Item Effect

## How Values Are Loaded

1. `passive_parser.py` reads item JSON from `data/items.json`
2. For each configured item, it extracts numeric values from the wiki markup in the `passives` or `active` arrays
3. `item_effects.py` merges parsed values over `_DEFAULT_ITEM_EFFECTS` defaults
4. Values not parseable from JSON (e.g. cooldowns not stored in the data, structural flags) are preserved from the defaults

When the user clicks "Update to latest patch", calling `refresh_item_effects()` re-parses and updates `ITEM_EFFECTS` in place.

## Step-by-Step: Adding a New Item Effect

### Step 1: Check the item's JSON data

Look up the item in `data/items.json` to see its `passives` and `active` arrays. Note the passive/active **name** and the **effects** text (wiki markup).

### Step 2: Add a parser in `passive_parser.py`

1. Write a parser function that extracts the relevant values from the wiki markup text:

```python
def _parse_my_item(text: str) -> dict[str, Any]:
    """Parse My Item's passive effect."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {"damage_type": "magic"}
    # Extract base damage
    base_match = re.search(r"\{\{as\|(\d+(?:\.\d+)?)", text_resolved)
    if base_match:
        result["base"] = float(base_match.group(1))
    # Extract AP ratio
    ap_match = re.search(r"\+\s*(\d+(?:\.\d+)?)%\s*AP", text_resolved)
    if ap_match:
        result["ap_ratio"] = float(ap_match.group(1)) / 100.0
    return result
```

2. Add the item to `_ITEM_PARSE_CONFIG`:

```python
"My Item": [("passive", "Passive Name", _parse_my_item, {})],
```

**Common parser patterns:**
- `_resolve_simple_templates(text)` — resolves `{{fd|N}}`, `{{ap|EXPR}}`, `{{#vardefineecho:...|N}}`
- `_extract_rd_values(text)` — extracts melee/ranged from `{{rd|M|R}}`
- `_extract_ft_parts(text)` — extracts display/tooltip from `{{ft|D|T}}`
- Use `cooldown_field` parameter + `"use_cooldown_field": True` in config to get the JSON cooldown field

### Step 3: Add defaults in `item_effects.py`

Add an entry to `_DEFAULT_ITEM_EFFECTS` with the item's `type` and any values that **cannot** be parsed from JSON (structural flags, behavioral constants):

```python
"My Item": {
    "type": "on_hit",       # Required: tells the fight engine how to apply
    "damage_type": "magic",
    # Only include values NOT available in JSON markup:
    "cooldown": 10.0,       # If cooldown isn't in JSON passive/active fields
},
```

The parser will automatically overlay the numeric values from JSON on top of these defaults.

### Step 4: Add calculation logic (if needed)

If the item uses a new effect type, add handling in:
- `item_effects.py` — new calculation function (e.g. `calculate_my_item_damage()`)
- `damage.py` — call the new function from `calculate_fight_damage()`

If the item fits an existing type (on_hit, spellblade, burn, proc, active, etc.), the fight engine picks it up automatically.

### Step 5: Test

1. Run the parser standalone to verify values match the wiki:
```python
from src.calculator.passive_parser import parse_item_effect
from src.calculator.data_fetcher import fetch_item_data
items = fetch_item_data()
print(parse_item_effect("My Item", items))
```

2. Write tests for both the isolated effect AND full fight integration:
```python
class TestMyItemEffect:
    def test_parsed_values_match_expected(self) -> None:
        """Verify parser extracts correct values from JSON."""
        ...

    def test_on_hit_damage(self) -> None:
        """Unit test for the raw damage value."""
        ...

    def test_full_fight_with_item(self) -> None:
        """Integration test through calculate_fight_damage."""
        ...
```

3. Run the test suite: `pytest`

## Wiki Markup Reference

Common templates in item effect descriptions:

| Template | Meaning | Example |
|----------|---------|---------|
| `{{as\|VALUE}}` | Stat display | `{{as\|30 '''bonus''' magic damage}}` |
| `{{rd\|M\|R}}` | Melee/ranged split | `{{rd\|9%\|6%}}` |
| `{{fd\|N}}` | Floor display (number) | `{{fd\|1.5}}` → 1.5 |
| `{{ap\|EXPR}}` | AP-colored value | `{{ap\|60*3}}` → 180 |
| `{{ft\|D\|T}}` | Tooltip (display/total) | Per-tick vs total values |
| `{{pp\|...}}` | Per-level scaling | `{{pp\|25 to 10 for 6\|...}}` |
| `'''text'''` | Bold (wiki) | `'''bonus'''`, `'''base'''` |

## Stat-Granting Passives (stat conversions)

Items that modify stats beyond their flat values (AP multipliers, mana→AP, health→AD, etc.) follow the same parser pipeline as damage effects but are consumed by `stats.py` instead of `damage.py`.

**Data flow:** `passive_parser.py` → `ITEM_EFFECTS` registry → `stats.py` looks up values at calculation time.

**Important:** `stats.py` must **never hardcode** numeric item values. All values come from `ITEM_EFFECTS` with a fallback default in the `.get()` call.

### Where stat passives are applied in `stats.py`

- **`check_item_passives()`** — AP multipliers (Rabadon's, Blackfire Torch). Returns `ability_power_multiplier` flags that `calculate_total_stats()` aggregates additively.
- **`calculate_total_stats()`** — Stat conversions (mana→AP, health→AD, mana regen→AP, conditional AS bonuses). Each block looks up the item in `ITEM_EFFECTS` and reads the parsed ratio/value.

### Step-by-Step: Adding a Stat-Granting Passive

#### Step 1: Check the item's JSON data

Same as damage effects — look up the item in `data/items.json` and find the passive name and wiki markup text.

#### Step 2: Add a parser in `passive_parser.py`

Write a parser that extracts the conversion ratio or bonus value. Common patterns:

```python
# Percentage of a stat converted to another stat (e.g. "2% bonus mana")
def _parse_my_stat_conversion(text: str) -> dict[str, Any]:
    """Parse My Item's stat conversion passive."""
    text_resolved = _resolve_simple_templates(text)
    result: dict[str, Any] = {}
    ratio_match = re.search(
        r"(\d+(?:\.\d+)?)%\s+'''bonus'''\s+mana", text_resolved,
    )
    if ratio_match:
        result["bonus_mana_to_ap_ratio"] = float(ratio_match.group(1)) / 100.0
    return result

# AP multiplier (e.g. "increase your ability power by 30%")
def _parse_my_ap_multiplier(text: str) -> dict[str, Any]:
    """Parse My Item's AP multiplier passive."""
    result: dict[str, Any] = {}
    amp_match = re.search(
        r"(?:ability\s+power)\}\}\s+by\s+(\d+(?:\.\d+)?)%",
        text, re.IGNORECASE,
    )
    if amp_match:
        result["ap_percent_increase"] = float(amp_match.group(1)) / 100.0
    return result

# Melee/ranged split bonus (e.g. "{{rd|30|20}}% bonus attack speed")
def _parse_my_melee_ranged_bonus(text: str) -> dict[str, Any]:
    """Parse My Item's melee/ranged bonus."""
    result: dict[str, Any] = {}
    all_rds = _extract_all_rd_values(text)
    for melee_text, ranged_text in all_rds:
        m = _extract_number(melee_text)
        r = _extract_number(ranged_text)
        if m is not None and r is not None and m >= 20:
            result["bonus_attack_speed_melee"] = m
            result["bonus_attack_speed_ranged"] = r
            break
    return result
```

Register in `_ITEM_PARSE_CONFIG` under the `# ── Stat Conversion ──` section:

```python
"My Item": [("passive", "Passive Name", _parse_my_stat_conversion, {})],
```

**Tip:** If multiple items share the same passive pattern (e.g. Archangel's Staff and Seraph's Embrace both have "Awe" with `N% bonus mana → AP`), use a single shared parser function for both.

#### Step 3: Add defaults in `item_effects.py`

Add an entry to `_DEFAULT_ITEM_EFFECTS` under the `# ── Stat Conversion ──` section:

```python
"My Item": {
    "type": "stat_conversion",
    "bonus_mana_to_ap_ratio": 0.02,  # Fallback if parser fails
},
```

For items that already have damage entries (e.g. Muramana has on-hit damage AND a stat conversion), add the stat-conversion key to the **existing** entry rather than creating a new one.

#### Step 4: Add the stat application in `stats.py`

In `calculate_total_stats()`, add a block that reads from `ITEM_EFFECTS`:

```python
# My Item passive: bonus mana as AP
for item in items:
    if item.get("name") == "My Item":
        effect = ITEM_EFFECTS.get("My Item", {})
        ratio = effect.get("bonus_mana_to_ap_ratio", 0.02)
        raw_ability_power += ratio * total_item_stats["mana"]
        break
```

For AP multipliers, add to `check_item_passives()` instead:

```python
if item_name == "My Item":
    ap_increase = effect.get("ap_percent_increase", 0.30)
    passives["ability_power_multiplier"] = 1.0 + ap_increase
```

**Key rules:**
- Always use `ITEM_EFFECTS.get(item_name, {}).get(key, fallback)` — never hardcode the value directly
- The fallback in `.get()` should match the default in `_DEFAULT_ITEM_EFFECTS` (safety net if registry fails)
- AP multipliers stack **additively** (Rabadon's 30% + Blackfire 4% = 34% total, not 1.30 × 1.04)

#### Step 5: Test

1. Verify the parser extracts correct values:
```python
from src.calculator.passive_parser import parse_item_effect
from src.calculator.data_fetcher import fetch_item_data
items = fetch_item_data()
print(parse_item_effect("My Item", items))
```

2. Write a regression test that the stat value is correct:
```python
def test_my_item_stat_conversion(self, champion_data: dict) -> None:
    item = get_item_by_name("My Item")
    stats = calculate_total_stats(champion_data, 18, [item])
    assert stats["ability_power"] == expected_value
```

3. Write a mock test proving the registry is used (not hardcoded):
```python
def test_my_item_reads_from_registry(self, champion_data: dict, monkeypatch) -> None:
    from src.calculator import item_effects
    item = get_item_by_name("My Item")
    patched = dict(item_effects.ITEM_EFFECTS.get("My Item", {}))
    patched["bonus_mana_to_ap_ratio"] = 0.10  # Different from real value
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "My Item", patched)
    stats = calculate_total_stats(champion_data, 18, [item])
    # Assert the patched value was used, not the real one
```

4. Run the test suite: `pytest`

## Common Pitfalls

- **Parser first**: Always check if values can be parsed from JSON before hardcoding. Only hardcode values that truly aren't in the data.
- **No hardcoded values in stats.py**: All item-specific numeric values in `stats.py` must come from `ITEM_EFFECTS.get()` lookups. This ensures values auto-update when wiki data is refreshed.
- **Penetration order**: Percent penetration applies before flat penetration
- **True damage**: Ignores all resistances — never pass through `apply_resistance()`
- **BoRK simulation**: Must be iterative (decreasing target HP per auto), not flat
- **Spellblade cooldown**: 1.5s internal cooldown shared across all spellblade items
- **AP multipliers**: Stack additively, not multiplicatively
- **Name aliases**: If the JSON uses a different name (e.g. "Luden's Echo" vs "Luden's Companion"), add an entry to `_NAME_ALIASES` in `passive_parser.py`
