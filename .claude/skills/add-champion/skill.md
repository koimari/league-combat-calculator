---
name: add-champion
description: Step-by-step guide for adding a new LoL champion to the calculator (post-#136: registry-only, no generated scaffolding). Use when creating a champion module, registering it, or writing champion ability tests.
---

# Add a New Champion

The roster is **registry-only** (`src/calculator/champions/__init__.py` ->
`_CUSTOM_CHAMPION_MODULES`, the single manifest; `registered_champion_names()`
is the public view). There is no generated/ stubs lane, no `_GENERATED_*`
registry, and no literal champion count anywhere — counts derive from
`len(registry)` / `len(data/champions.json)`. `tests/test_roster_growth.py`
proves a 174th champion adapts with zero literal edits; keep it that way.

## Two implementation lanes

1. **Reviewed packet (fast lane).** Champions without a dedicated module run
   the packet path from `static/reviewed-packets.json` (86 batch champions
   today). Add the champion's slots there by rebuilding:
   `LCC_WIKI_DB=<scryglass wiki db> LCC_AXWORD_SOURCE=<meraki kit> \
   python scripts/build_reviewed_modules.py` — this writes packet rows with
   per-champion wiki revision receipts + source hashes into
   `static/reviewed-packets.json` (all 173 entries must stay byte-identical
   except the new champion, or the commit explains the diff).
2. **Dedicated module (slow lane).** `src/calculator/champions/<name>.py`
   exposing `parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS`,
   `MODULE_COVERAGE` (modeled/no_damage/out_of_scope per slot), and
   `REVIEW_STATUS = "reviewed_module"`, registered in `_CUSTOM_CHAMPION_MODULES`.

## Every new champion must also

- **Spellblade / on-hit contract**: if any ability applies item on-hits
  (wiki: "applies on-hit effects"), declare `applies_item_on_hits` with
  effectiveness/triggers and add the row to
  `tests/test_spellblade_on_hit_matrix.py`'s REVIEWED table (a missing
  declaration fails the matrix contract).
- **Rotation options**: every `OPTIONS` key must be classified in
  `_ROTATION_CLASSIFICATIONS` (setup/consume/self_state/execute/irrelevant/
  unsupported + slot/condition) or `get_champion_option_rotation()`
  contract test fails.
- **Atomizer**: run `python scripts/atomize.py abilities stats` and confirm
  the champion's numerical rows atomize (the unified Atomizer is the only
  allowed extractor).
- **Catalogues/gates**: `build_ability_catalog.py`, `build_bis_profiles.py`,
  `champion_optimizer_matrix.py`, `full_entry_audit.py` all derive counts
  from the registry — a new champion must pass `champion_optimizer_matrix.py`
  (173/173 certified) and the full pytest suite.

## Verify

```python
import json
from src.calculator.data_fetcher import get_champion
from src.calculator.champions import parse_champion_abilities
champ = get_champion("ChampionName")
stats = {"attack_damage": 150.0, "bonus_attack_damage": 50.0, "ability_power": 200.0}
print(json.dumps(parse_champion_abilities(champ, 13, 200.0,
    champion_stats=stats,
    target_stats={"target_max_health": 2500.0}), indent=2))
```

Cross-check `total_raw` / `damage_type` / `cooldown` per slot against the
wiki, then run: the focused champion tests, the spellblade matrix, the
rotation-semantics contract, the atomizer, and the full suite.

## Environment (patch-day prerequisites)

- `LCC_WIKI_DB=/Users/river/Projects/scryglass/data/lol/knowledge/league-wiki.sqlite3`
- `LCC_WIKI_QUERY=<repo>/vendor/league-wiki-query/scripts/query_league_wiki.py`
- `LCC_AXWORD_SOURCE=/Users/river/Projects/lol-strength-analysis/src/data/generated/merakiAbilityKits.ts`
