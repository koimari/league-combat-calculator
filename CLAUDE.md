# League of Legends Calculator

Module map and pipeline: see `architecture.md`.

## Important Rules

1. **vendor/lolstaticdata/ is external code** — Don't refactor or restructure it. Minimal, targeted bug fixes are OK when they block functionality (e.g., parser crashes on specific champions).
2. **Always use the caching layer** — `data_fetcher.py` reads from `data/`. Never bypass it or add network calls to it. Data updates go through `data_updater.py`.
3. **All calculation functions must have corresponding tests.**
4. **Run tests before considering any task complete.**
5. **No item numbers outside `item_effects.py`** — All numeric item values come from `item_effects` typed accessors, with NO literal fallbacks at call sites (a `.get(key, stale_literal)` silently wins when the parser breaks — that exact failure hid a 3× Statikk Shiv overstatement). Missing keys must raise, naming the item and key. Keystone runes follow the same rule through `rune_effects.py` over `data/runes.json`; only compiled keystones are selectable and everything else fails closed.
6. **Item availability comes from cached source data, never a name list** — `item_source.py` decides what an ordinary Summoner's Rift build may hold from the cached `modes` table, champion restriction, and acquisition note. An item whose sources are missing is withheld, not assumed available. Effect text lives in `passives[].branches` / `active[].branches` (every Wiki `description`, `description2`, … of one effect); read it through `item_source.effect_text`, never by indexing a single description.
7. **Named champion modules are the only runtime path** — every attacker must resolve to a validated `src/calculator/champions/<name>.py` contract. Unknown names fail closed. The generic parser exists only for explicit synthetic/development fixtures; never route production champions through it.

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

## Commands and gates

```bash
pytest                # Run all tests
pytest --cov=src      # Run tests with coverage
black src/ tests/ scripts/          # Format code
black --check src/ tests/ scripts/  # Formatting gate (CI runs this)
pylint src/           # Lint code
python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # Numeric regression gate
python scripts/coverage_census.py check docs/coverage-census.json        # Coverage frontier gate (own CI job, ~10 min)
python scripts/patch_update.py run    # Patch day: re-pull wiki data + economics, audit, gates (see /patch-update skill)
```

`pytest` gates every task; `pylint src/` and `black --check` gate any code change.
Formatter settings live in `pyproject.toml`, and the version is pinned in
`requirements.txt` — black's stable style shifts yearly, so an unpinned run reformats
files it shouldn't. `scripts/build_reviewed_modules.py` writes packet evidence only;
executable champion modules are named, reviewed source files.

**The golden gate is the one with non-obvious semantics** — run it whenever calculation
code changed: a pure refactor must show zero diffs, while a behavior fix re-captures the
baseline with every diff explained in the commit.

## Known Quirks

- **Windows filenames:** `data_updater.py` monkey-patches `lolstaticdata`'s `download_soup` to strip colons from cache filenames (illegal on Windows)
- **Three things are named "champions":** `src/calculator/champions/` (our champion code), `data/champions.json` (our tracked data cache), and `vendor/lolstaticdata/champions*` (the scraper's gitignored scratch output — not read at runtime). See `vendor/README.md` and `data/README.md`.
- **Wiki parser bugs:** Some champions (Heimerdinger, Sona, Karma, Nidalee) previously crashed the lolstaticdata parser due to `nvalues=None` — these were patched in the local copy
- **Known-degraded wiki parses (stable across patches, fix when implementing the champion):** gimmick scalings the modifier parser half-parses — values survive but `units` come back empty, so the generic path can't attribute them. Aurelion Sol Q (Stardust stacks), Bard P (Chimes), Heimerdinger W/E (multi-part rockets), K'Sante W (bonus resistances), Quinn P (crit chance), Vladimir E (charge time), Yasuo/Yone Q3 (crit conversion), Zeri P (execute range). These emit the `FAILURE TO PARSE MODIFIER` spam during data pulls; each needs a champion module (with options for its stack/charge mechanic) anyway, so parsing fixes belong to that work, not patch day. Gnar P (Rage Gene) is the worst case — its JSON `leveling` is entirely empty, so the Mega form stat bonuses live as tested constants in `src/calculator/champions/gnar.py` (implemented; on patch updates verify against the **game files** — Community Dragon `gnarbig.bin.json` CharacterRecords minus `gnar.bin.json`'s — NOT the wiki, whose Mega stat box has been stale before: it claimed 5.7 AD growth when the game had 5.5, and Mega's deltas are base stats, not bonus).
- **Item names:** Parser configuration and build scenarios use the exact names in `data/items.json`; verify the cached name before adding an item.
- **Campaign receipts pin tree shape, not just numbers:** `docs/receipts/escalated-defects-ledger-join.json` records source *line numbers* of raise sites in `survival/outcome_state.py`, and `docs/receipts/receipt-walk-retirement-schedule.json` is derived from a tree scan (`scripts/receipt_walk_schedule.py --write` regenerates it). A pure deletion above a pinned line turns these red with no behavior change — regenerate or re-pin, never hand-edit the derived one.
