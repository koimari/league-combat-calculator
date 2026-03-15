# League of Legends Calculator

## Important Rules

1. **lolstaticdata/ is external code** — Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer** — `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No hardcoded item values in stats.py** — All numeric item values must come from `ITEM_EFFECTS.get()` lookups so they auto-update when wiki data refreshes.

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
pytest                # Run all tests
pytest --cov=src      # Run tests with coverage
black src/ tests/     # Format code
pylint src/           # Lint code
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
