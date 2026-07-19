# League of Legends Calculator

Module map and pipeline: see `architecture.md`.

## Important Rules

1. **lolstaticdata/ is external code** — Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer** — `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No item numbers outside `item_effects.py`** — All numeric item values come from `item_effects` typed accessors, with NO literal fallbacks at call sites (a `.get(key, stale_literal)` silently wins when the parser breaks — that exact failure hid a 3× Statikk Shiv overstatement). Missing keys must raise, naming the item and key.

## Domain Knowledge

These LoL-specific facts affect calculations and must be correct:

- **Critical strike base damage = 200%** (2.0 multiplier, not the old 175%)
- **Penetration order:** Percent penetration applies before flat penetration; result cannot go below 0
- **Lethality = flat armor pen, 1:1** — no level scaling (since V14.1; the old `0.6 + 0.4 × level/18` formula is retired). Like all penetration, it cannot reduce the target's armor below 0 for damage calculation (only armor *reduction* effects can go negative)
- **Level cap is 20** (top lane only, as of this season); the stat growth formula below applies unchanged through level 20
- **Stat growth formula:** `base + growth × (level - 1) × (0.7025 + 0.0175 × (level - 1))`
- **Attack speed:** `base_AS + AS_ratio × (bonus_percent / 100)` — AS_ratio is separate from base_AS
- **Ability haste → CDR:** `effective_cd = base_cd × 100 / (100 + ability_haste)`
- **Resistance math:** `actual_damage = raw × 100 / (100 + resistance)` — negative resistance amplifies damage
- **True damage** ignores all resistances entirely

## Common Commands

```bash
pytest                # Run all tests
pytest --cov=src      # Run tests with coverage
black src/ tests/     # Format code
pylint src/           # Lint code
python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # Numeric regression gate
python scripts/patch_update.py run    # Patch day: re-pull wiki data, audit, gates (see /patch-update skill)
```

## Verification Steps

After completing any task:
1. Run the test suite: `pytest`
2. Verify all tests pass
3. If calculation code changed, run the golden gate:
   `python scripts/golden_snapshot.py compare scripts/golden_baseline.json`
   — a pure refactor must show zero diffs; a behavior fix re-captures the baseline
   with every diff explained in the commit.
4. Run linter if code was modified: `pylint src/`
5. Show output of verification steps

## Known Quirks

- **Windows filenames:** `data_updater.py` monkey-patches `lolstaticdata`'s `download_soup` to strip colons from cache filenames (illegal on Windows)
- **Wiki parser bugs:** Some champions (Heimerdinger, Sona, Karma, Nidalee) previously crashed the lolstaticdata parser due to `nvalues=None` — these were patched in the local copy
- **Item names:** Parser configuration and build scenarios use the exact names in `data/items.json`; verify the cached name before adding an item.
