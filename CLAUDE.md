# League of Legends Calculator

## Project Overview

A web-based calculator that lets players select a champion, set their level, equip items, configure fight parameters, and see calculated damage breakdowns against a target with configurable resistances.

**Features:**
- Champion selection with correct per-level stats
- Item builds with stat stacking and passive/active effects
- Ability damage at each rank with scaling
- Fight duration modeling (cooldown-based ability casts, auto-attack uptime)
- Target resistance configuration (health, armor, MR)

**Tech stack:** Python 3.x, Flask, vanilla HTML/CSS/JS frontend, pytest

## Architecture

```
src/
├── app.py                         # Flask routes: /, /api/champions, /api/items,
│                                  #   /api/boots, /api/abilities/<name>,
│                                  #   /api/calculate (POST), /api/update-data (SSE)
└── calculator/
    ├── data_fetcher.py            # Cache-only reader for data/*.json (no network calls)
    ├── data_updater.py            # Updates data/ via lolstaticdata wiki scraping
    ├── stats.py                   # Champion stat growth, item stat stacking, stat conversions
    ├── resistance.py              # Armor/MR damage reduction, penetration application
    ├── damage.py                  # Fight engine: orchestrates all damage over fight duration
    ├── item_effects.py            # Item effect registry (ITEM_EFFECTS dict)
    ├── passive_parser.py          # Parses item wiki markup → numeric values
    └── champions/
        ├── __init__.py            # Registry + dispatcher (custom module or generic parser)
        ├── common.py              # Shared: calculate_ability_damage, effective_cooldown
        ├── generic_parser.py      # JSON-based parser — handles ~80% of champions
        ├── scaling.py             # Unit string → stat resolution ("% AP" → ability_power)
        ├── attribute_classifier.py # Detects damage vs utility attributes
        ├── skill_orders.py        # Default Q>W>E + per-champion overrides
        └── ahri.py                # Custom: multi-part W, multi-dash R

templates/index.html               # Main calculator UI
static/css/style.css               # LoL-themed styling
static/js/app.js                   # Frontend logic + API calls
data/champions.json                # Cached champion data (auto-updated)
data/items.json                    # Cached item data (auto-updated)
lolstaticdata/                     # Wiki scraping library (external, see rules)
```

### Data Flow

```
User interaction (frontend)
  → POST /api/calculate
    → data_fetcher.py (reads cached JSON)
    → stats.py (base stats + item stats → total stats)
    → champions/ (parse abilities at current ranks)
    → damage.py (simulate fight: abilities × casts + autos × uptime)
      → item_effects.py (on-hit, spellblade, burn, proc effects)
      → resistance.py (apply armor/MR after penetration)
    → JSON response → frontend renders breakdown
```

### Data Update Flow

Data comes from the `lolstaticdata` library which scrapes the LoL Wiki, Data Dragon, and Community Dragon. The frontend has an "Update to latest patch" button that triggers `/api/update-data` (SSE stream with progress). `data_updater.py` orchestrates a two-phase approach: bulk fetch first, then individual champion retry on crash. A Windows monkey-patch in `data_updater.py` sanitizes filenames (removes colons illegal on Windows).

`data_fetcher.py` is cache-only — it reads from `data/` and never makes network calls.

## Key Design Patterns

### Field-Based Dispatch (damage.py)
The fight engine checks ability **fields** (`initial_damage`, `damage_per_cast`, `on_hit`, `subsequent_damage`, `total_casts`) rather than ability keys (`== "Q"`). This makes it champion-agnostic — any champion whose parser outputs these fields works automatically.

### Generic-First Champion Parsing
Most champions (~80%+) need no custom code. `champions/__init__.py` checks a registry (`_CHAMPION_MODULES` dict); if the champion isn't registered, it falls through to `generic_parser.py` which reads abilities directly from JSON. Custom modules are only for unique mechanics (transforms, multi-part abilities, external stacking).

### Item Effect Pipeline
```
passive_parser.py (parse wiki markup from JSON)
  → merges over _DEFAULT_ITEM_EFFECTS (hardcoded fallbacks)
    → ITEM_EFFECTS dict (consumed by damage.py and stats.py)
```
Numeric values come from parsed JSON. Only structural flags and values absent from markup are hardcoded in defaults. `refresh_item_effects()` re-parses on patch update.

### Stat vs Damage Split
If an item **grants or modifies a stat** → handled in `stats.py`. If an item **deals damage** → handled in `item_effects.py` + `damage.py`. Some items (e.g., Muramana) appear in both.

## Important Rules

1. **lolstaticdata/ is external code** — Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer** — `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No hardcoded item values in stats.py** — All numeric item values must come from `ITEM_EFFECTS.get()` lookups so they auto-update when wiki data refreshes.

## Code Style

- Python: PEP 8
- Type hints for all function signatures
- Descriptive variable names (avoid abbreviations like `dmg`, `ad`)
- Docstrings on all public functions
- Functions max 20 lines when possible

## Domain Knowledge

These LoL-specific facts affect calculations and must be correct:

- **Critical strike base damage = 200%** (2.0 multiplier, not the old 175%)
- **Penetration order:** Percent penetration applies before flat penetration; result cannot go below 0
- **Lethality → flat armor pen:** `lethality × (0.6 + 0.4 × min(level, 18) / 18)`
- **Stat growth formula:** `base + growth × (level - 1) × (0.7025 + 0.0175 × (level - 1))`
- **Attack speed:** `base_AS + AS_ratio × (bonus_percent / 100)` — AS_ratio is separate from base_AS
- **Ability haste → CDR:** `effective_cd = base_cd × 100 / (100 + ability_haste)`
- **Resistance math:** `actual_damage = raw × 100 / (100 + resistance)` — negative resistance amplifies damage
- **True damage** ignores all resistances entirely

## Common Commands

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=src

# Format code
black src/ tests/

# Lint code
pylint src/
```

## Verification Steps

After completing any task:
1. Run the test suite: `pytest`
2. Verify all tests pass
3. Run linter if code was modified: `pylint src/`
4. Show output of verification steps

## Known Quirks

- **Windows filenames:** `data_updater.py` monkey-patches `lolstaticdata`'s `download_soup` to strip colons from cache filenames (illegal on Windows)
- **Wiki parser bugs:** Some champions (Heimerdinger, Sona, Karma, Nidalee) previously crashed the lolstaticdata parser due to `nvalues=None` — these were patched in the local copy
- **Item name mismatches:** Some JSON item names differ from wiki names (e.g., "Luden's Echo" vs "Luden's Companion") — `passive_parser.py` has `_NAME_ALIASES` to handle this
