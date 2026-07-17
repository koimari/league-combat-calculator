# Architecture

Pipeline and module shape. One concept, one home — this file says which home.

## The pipeline

```
wiki (lolstaticdata, external)
  → data_updater.py      (network fetch, writes cache)      [writes]
  → data/*.json          (cache; patch-stamped)
  → data_fetcher.py      (all reads go through here)        [reads]
       ├→ passive_parser.py → item_effects.py   (item knowledge)
       └→ champions/                            (ability parsing)
  → stats.py + resistance.py                    (champion math)
  → pipeline.py → damage.py                     (full fight → fight engine)
       ├→ app.py → static/js/app.js             (web UI)
       └→ optimizer.py                          (build search)
```

## Module homes

**Data layer**
- `lolstaticdata/` — external wiki-scraper code. Don't refactor; minimal targeted fixes only.
- `src/calculator/data_updater.py` — the ONLY module with network calls. Fetches wiki data,
  writes the `data/` cache.
- `src/calculator/data_fetcher.py` — the ONLY read path for cached data. No network.
  Parsed JSON is cached by resolved path + file mtime, so optimizer requests reuse one
  in-memory version and automatically observe updater replacements.

**Item knowledge** — values and formulas compile before fight execution
- `src/calculator/passive_parser.py` — wiki passive/active text → effect dicts (`_parse_*`
  per item family). Parse-config keys use the exact cached JSON item names.
- `src/calculator/item_effects.py` — `_STATIC_ITEM_EFFECTS` owns schema/unparseable values;
  `_OFFLINE_ITEM_EFFECTS` is whole-parser recovery, never a per-key fallback. Parsed values
  compile per build through `resolve_damage_effects()` into immutable, phase-aligned specs.
  A missing required key raises with item+key context. `refresh_item_effects()` re-parses
  in place after a data update.

**Champion layer** — slot-archetype engine
- `src/calculator/champions/__init__.py` — dispatcher. Registered names → champion module;
  everyone else → `GENERIC_SLOTS` (auto-detect). Loaded champion objects enter through
  `parse_champion_abilities()`, which dispatches on their display name. Also serves champion
  OPTIONS/ASSUMPTIONS metadata to the frontend.
- `src/calculator/champions/engine.py` — phase-ordered slot-map evaluation
  (BUFF → DEBUFF → DAMAGE → ONHIT → AMP); buffs mutate the shared stats context before
  damage slots read it.
- `src/calculator/champions/slotlib.py` — the single JSON extraction core
  (`extract_named` / `extract_auto` / `extract_value` / `extract_cooldown` /
  `sum_modifiers` / `build_stats_context`), entry builders, and only genuinely
  shared factories (`simple_damage`, `stat_buff`, `by_option`, callback-based
  `proc_damage`, `on_hit_auto`). An archetype exists only with ≥2 real users.
- `src/calculator/champions/<name>.py` — one champion, one file: `SLOTS` map, `OPTIONS`,
  `ASSUMPTIONS`, custom slot fns for that champion's unique mechanics. Most champions have
  NO file (generic path). Adding one: see the `/add-champion` skill.
- `skill_orders.py`, `attribute_classifier.py`, `scaling.py` — rank schedules, damage-type
  classification, stat-scaling resolution (engine infrastructure).

**Champion math**
- `src/calculator/stats.py` — level scaling + item stat aggregation (via item_effects
  accessors only).
- `src/calculator/resistance.py` — resistance/penetration formulas. Dependency-free
  leaf; the CLAUDE.md domain formulas live here. (Lethality needs no formula:
  it is 1:1 flat armor pen, applied in stats.py.)

**Fight engine**
- `src/calculator/pipeline.py` — canonical stats → ability parsing → fight orchestration.
  Owns `FightParams`, request-mode resolution, and every fight/target default.
- `src/calculator/damage.py` — `calculate_fight_damage` is a pipeline of named
  step functions over `FightState`/`Resists` (the body reads as the fight model).
  `split_auto_vs_ability` owns breakdown-key attribution. It consumes compiled item specs,
  never registry dictionaries or item-name branches: item VALUES/formulas live in
  `item_effects`; timing, mitigation, falling HP, and stack cadence stay here.

**Consumers**
- `src/calculator/optimizer.py` — enumerates builds through `pipeline.run_fight`.
  Owns `_EXCLUSIVITY_GROUPS`
  (canonical; served to the frontend).
- `src/app.py` — thin Flask routes. `/api/config` bootstraps the frontend (exclusivity
  groups, fight/target defaults, champion options metadata). No calculation logic in routes.
- `static/js/app.js` — presentation only. Domain data (groups, defaults, options) arrives
  from `/api/config`; no formulas, no hand-maintained champion/item tables.

## Verification

- `pytest` — suite must be fully green; hand-validated expected values only change with
  documented patch-drift derivations.
- `scripts/golden_snapshot.py compare scripts/golden_baseline.json` — locks the numeric
  behavior of the whole pipeline (all champions, sustained + one-rotation fights,
  per-item sweep) to 2 decimals. Refactors must not move it; behavior fixes re-capture
  it with every changed scenario explained.
- Test layout mirrors source: `test_item_effects.py` (accessors) / `test_item_damage.py`
  (per-item fight behavior) / `test_resistance.py` / `test_damage.py` (engine core) /
  `test_<champion>.py` (only champions with custom modules) / `test_generic_path.py`
  (roster-wide generic coverage). `tests/conftest.py` owns the shared `attacker_stats`,
  `fight`, champion-data factory, and display-name-aware `parse_at` test front doors.

## Dependencies

- Root `requirements.txt` defines the calculator application, test, and lint environment.
- `lolstaticdata/requirements.txt` belongs to the vendored external project. Its overlap with
  the root manifest is intentional; it is not a second calculator environment definition.

## Known limits (deliberate)

- Multi-kit champions (Aphelios weapons, Hwei subspells, transformers) parse fine but the
  rotation engine and cast-order validation assume four castable slots — a future
  workstream.
- `Notes.txt` holds the user's feature backlog (not architecture).
