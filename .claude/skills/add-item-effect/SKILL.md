---
name: add-item-effect
description: Guide for adding item passive/active effects to the LoL calculator. Use when implementing on-hit effects, spellblade, burn/DoT, ability amplifiers, or stat-granting passives.
---

# Add an Item Effect

## How Values Are Loaded

1. `passive_parser.py` reads item JSON from `data/items.json`
2. For each configured item, it extracts numeric values from the wiki markup in the `passives` or `active` arrays
3. `_STATIC_ITEM_EFFECTS` supplies structural fields and values the parser cannot obtain
4. `item_effects.py` compiles the build's live registry records into typed, immutable phase specs

`_REFERENCE_ITEM_EFFECTS` is the reviewed shape of every registered entry; the live registry never reads a parser-owned value from it. A missing cache or a failed parse raises at import; a partial parse leaves the key absent and `required_effect_value()` raises on the read.

When wiki data is re-pulled (the dev-only `/api/update-data` endpoint, or patch day), calling `refresh_item_effects()` re-parses and updates `ITEM_EFFECTS` in place.

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

### Step 3: Add schema and reference values in `item_effects.py`

Add the complete reviewed entry to `_REFERENCE_ITEM_EFFECTS`. Put schema fields in `_STRUCTURAL_EFFECT_KEYS`; add truly unparseable numeric keys to `_STATIC_VALUE_KEYS_BY_ITEM`:

```python
"My Item": {
    "type": "on_hit",       # Required: selects the compiler behavior
    "damage_type": "magic",
    # Only include values NOT available in JSON markup:
    "cooldown": 10.0,       # If cooldown isn't in JSON passive/active fields
},
```

The module derives `_STATIC_ITEM_EFFECTS` and `_PARSEABLE_ITEM_KEYS`. Cached parsing must agree with the reference table's parser-owned keys; the parity test tells you exactly what changed on a balance patch.

### Step 4: Compile the behavior and use an engine phase

If the item fits a compiled behavior, add its formula/model identifier and extend the matching `_compile_*` function only when the existing schema cannot express it. `resolve_damage_effects()` emits phase-aligned specs such as `PerHitEffect`, `CooldownProcEffect`, or `FirstAutoEffect`. A new `type` must also be registered in `_KNOWN_EFFECT_TYPES`; misspelled or unknown types fail loudly with the item and type in the error.

`damage.py` owns only generic scheduling, stack cadence, falling target HP, mitigation, and breakdown accumulation. Never add an item-name branch or an `ITEM_EFFECTS` read there. One item may emit multiple specs through `secondary_behavior` (Titanic Hydra and Muramana are the examples).

### Step 5: Test

1. Run the parser standalone to verify values match the wiki:
```python
from src.calculator.passive_parser import parse_item_effect
from src.calculator.data_fetcher import fetch_item_data
items = fetch_item_data()
print(parse_item_effect("My Item", items))
```

2. Keep parser/accessor tests and fight tests at their established altitudes:
```python
# tests/test_item_effects.py
class TestMyItemEffect:
    def test_parsed_values_match_expected(self) -> None:
        """Verify parser extracts correct values from JSON."""
        ...

    def test_compiled_formula(self) -> None:
        """Verify the typed build projection and raw formula."""
        ...

# tests/test_item_damage.py
class TestMyItemFightDamage:
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

**Important:** `stats.py` must **never hardcode** numeric item values — and neither `stats.py` nor the accessors use literal fallbacks in `.get()` calls. A missing key is a parser/schema bug that must fail loudly (see `required_effect_value()`), not silently borrow a stale literal.

### Where stat passives live

- **`item_effects.py` stat-passive accessors** (section "Stat-modifying passives") — own the lookup and numeric semantics: `ap_multiplier()` (Rabadon's, Blackfire — additive), `mana_to_ap_bonus()`, `dawncore_bonus_ap()`, `flowing_water_bonus_ap()`, `passive_attack_speed_bonus()`, `muramana_bonus_ad()`, `bloodmail_bonus_ad()`, `steraks_bonus_ad()`, `terminus_max_stack_bonuses()`, `basic_ability_haste()`.
- **`resolve_stat_effects()` in `item_effects.py`** — bundles every accessor into one `StatBonuses` record; `calculate_total_stats()` in `stats.py` consumes the bundle (orchestration only — no item names paired with magic numbers, and no new `stats.py` import per item).

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

Add the complete entry to `_REFERENCE_ITEM_EFFECTS`; classify its structural and unparseable keys through the same static-key policy:

```python
"My Item": {
    "type": "stat_conversion",
    "bonus_mana_to_ap_ratio": 0.02,  # Reference parity value
},
```

For items that already have damage entries (e.g. Muramana has on-hit damage AND a stat conversion), add the stat-conversion key to the **existing** entry rather than creating a new one.

#### Step 4: Add an accessor in `item_effects.py`, wire it into `resolve_stat_effects()`

Add (or extend) an accessor in the "Stat-modifying passives" section of `item_effects.py` using `required_effect_value()`, then fold it into the `StatBonuses` bundle inside `resolve_stat_effects()`:

```python
# item_effects.py
def my_item_bonus_ap(items: list[dict[str, Any]], bonus_mana: float) -> float:
    """My Item passive: bonus mana as AP."""
    if "My Item" not in _item_names(items):
        return 0.0
    return required_effect_value("My Item", "bonus_mana_to_ap_ratio") * bonus_mana

# resolve_stat_effects() — the ONLY item-side wiring; stats.py is untouched
permanent_bonus_ap += my_item_bonus_ap(items, bonus_mana)
```

For AP multipliers, extend `ap_multiplier()` instead.

**Key rules:**
- The accessor owns the `ITEM_EFFECTS` lookup and the numeric semantics; `stats.py` never touches `ITEM_EFFECTS` directly
- **No literal fallbacks** — `required_effect_value()` raises a KeyError naming the item and key if live parsing or static schema is incomplete. `_REFERENCE_ITEM_EFFECTS` is the parity reference, never a fallback
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

- **The census receipt is exact**: modelling an item moves `docs/coverage-census.json`, and CI's `coverage-census` job compares it dict-for-dict — regenerate it (`python scripts/coverage_census.py run --output docs/coverage-census.json`, ~1 min on 16 cores) in the same commit.
- **Parser first**: Always check if values can be parsed from JSON before hardcoding. Only hardcode values that truly aren't in the data.
- **No hardcoded values in stats.py**: All item-specific numeric values come from `ITEM_EFFECTS` via the stat-passive accessors, with no literal fallbacks anywhere. This ensures values auto-update when wiki data is refreshed and that parser failures surface loudly instead of silently using stale numbers (the Statikk Shiv bug class).
- **Penetration order**: Percent penetration applies before flat penetration
- **True damage**: Ignores all resistances — never pass through `apply_resistance()`
- **BoRK simulation**: Must be iterative (decreasing target HP per auto), not flat
- **Spellblade cooldown**: 1.5s internal cooldown shared across all spellblade items
- **AP multipliers**: Stack additively, not multiplicatively
- **Item names**: Use the exact name in `data/items.json` for `_ITEM_PARSE_CONFIG`, defaults, tests, and build scenarios. `_NAME_ALIASES` is only an extension hook for a proven code-name/cache-name mismatch; do not add an alias for a stale label.
- **Burn refresh windows are mode-dependent**: A `burn` effect is ONE base-duration application stretched by its refresh window. In one-rotation mode that window is the GCD combo spread (0.5s/cast); in time-based mode abilities recast on cooldown across the whole fight, so the window runs to `rotation.last_cast_time` (the fight's final recast) + the burn duration, capped at fight end. Liandry's bug class: using the combo spread in a 10s timed fight halved the burn (one 3s application + spread instead of ~fight-long 2%/s uptime).
- **Base-stat-converting items must react to base-stat buffs**: Items computed at build-stats time from a base stat (Sterak's: 45% base AD) miss champion base-stat grants (Mega Gnar) that land later. `_apply_stat_buff_ultimates` in `damage.py` re-applies the conversion on the buffed delta via the item's `item_effects` accessor — if you add an item that scales off base AD/base HP/base armor, wire its accessor into that hook too.
