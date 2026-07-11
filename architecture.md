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
  → damage.py                                   (fight engine)
       ├→ app.py → static/js/app.js             (web UI)
       └→ optimizer.py                          (build search)
```

## Module homes

**Data layer**
- `lolstaticdata/` — external wiki-scraper code. Don't refactor; minimal targeted fixes only.
- `src/calculator/data_updater.py` — the ONLY module with network calls. Fetches wiki data,
  writes the `data/` cache.
- `src/calculator/data_fetcher.py` — the ONLY read path for cached data. No network.

**Item knowledge** — one fact, one home: `ITEM_EFFECTS`
- `src/calculator/passive_parser.py` — wiki passive/active text → effect dicts (`_parse_*`
  per item family; `_NAME_ALIASES` for wiki-vs-JSON name drift).
- `src/calculator/item_effects.py` — `_DEFAULT_ITEM_EFFECTS` (fallback registry) merged
  under parsed values at import; typed accessors (`get_*`) are the only way other modules
  read item numbers. No literal fallbacks at call sites — a missing key raises, naming the
  item and key. `refresh_item_effects()` re-parses in place after a data update.

**Champion layer** — slot-archetype engine (see `docs/refactors/champion-layer-redesign.md`)
- `src/calculator/champions/__init__.py` — dispatcher. Registered names → champion module;
  everyone else → `GENERIC_SLOTS` (auto-detect). Also serves champion OPTIONS/ASSUMPTIONS
  metadata to the frontend.
- `src/calculator/champions/engine.py` — phase-ordered slot-map evaluation
  (BUFF → DEBUFF → DAMAGE → ONHIT → AMP); buffs mutate the shared stats context before
  damage slots read it.
- `src/calculator/champions/slotlib.py` — the single JSON extraction core
  (`extract_named` / `extract_auto` / `extract_value` / `extract_cooldown` /
  `build_stats_context`) plus archetype factories (`simple_damage`, `stat_buff`,
  `by_option`, `multi_hit_sum`, `on_hit_pct_health`, `toggle_dot`, `multi_cast`,
  `proc_damage`, `utility`, `on_hit_auto`). An archetype exists only with ≥2 users.
- `src/calculator/champions/<name>.py` — one champion, one file: `SLOTS` map, `OPTIONS`,
  `ASSUMPTIONS`, custom slot fns for that champion's unique mechanics. Most champions have
  NO file (generic path). Adding one: see the `/add-champion` skill.
- `skill_orders.py`, `attribute_classifier.py`, `scaling.py` — rank schedules, damage-type
  classification, stat-scaling resolution (engine infrastructure).

**Champion math**
- `src/calculator/stats.py` — level scaling + item stat aggregation (via item_effects
  accessors only).
- `src/calculator/resistance.py` — resistance/penetration/lethality formulas. Dependency-free
  leaf; the CLAUDE.md domain formulas live here.

**Fight engine**
- `src/calculator/damage.py` — `calculate_fight_damage` is an 11-step pipeline of named
  step functions over `FightState`/`Resists` (the body reads as the fight model).
  `split_auto_vs_ability` owns breakdown-key attribution. Item VALUES come from
  item_effects accessors; fight MODELING stays here.

**Consumers**
- `src/calculator/optimizer.py` — enumerates builds through the same
  stats → parse_abilities → calculate_fight_damage pipeline. Owns `_EXCLUSIVITY_GROUPS`
  (canonical; served to the frontend).
- `src/app.py` — thin Flask routes. `/api/config` bootstraps the frontend (exclusivity
  groups, default target, champion options metadata). No calculation logic in routes.
- `static/js/app.js` — presentation only. Domain data (groups, defaults, options) arrives
  from `/api/config`; no formulas, no hand-maintained champion/item tables.

## Verification

- `pytest` — suite must be fully green; hand-validated expected values only change with
  documented patch-drift derivations.
- `scripts/golden_snapshot.py compare scripts/golden_baseline.json` — locks the numeric
  behavior of the whole pipeline (all champions, sustained + one-rotation fights,
  per-item sweep) to 2 decimals. Refactors must not move it; behavior fixes re-capture
  it with a diff summary (see `docs/refactors/campaign-2026-07.md`).
- Test layout mirrors source: `test_item_effects.py` (accessors) / `test_item_damage.py`
  (per-item fight behavior) / `test_resistance.py` / `test_damage.py` (engine core) /
  `test_<champion>.py` (only champions with custom modules) / `test_generic_path.py`
  (roster-wide generic coverage). Strategy note in `tests/conftest.py`.

## Known limits (deliberate)

- Multi-kit champions (Aphelios weapons, Hwei subspells, transformers) parse fine but the
  rotation engine and cast-order validation assume four castable slots — a future
  workstream, documented in the redesign doc.
- `Notes.txt` holds the user's feature backlog (not architecture).
