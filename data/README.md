# data/

The calculator's champion/item data cache — the single source the app reads.

- `champions.json`, `items.json`, `runes.json` — patch-stamped wiki data,
  written only by `src/calculator/data_updater.py`, read only through
  `src/calculator/data_fetcher.py`. `runes.json` holds the 17 keystones,
  parsed from the wiki's `Template:Rune data <name>` pages by
  `src/calculator/rune_parser.py`.
- Tracked in git deliberately: patch-day diffs against HEAD are how
  `scripts/patch_update.py` audits what changed.
- Never hand-edit; refresh via the app's "Update to latest patch" button or
  `python scripts/patch_update.py run`.

(Not to be confused with `vendor/lolstaticdata/`'s scratch output of the same
names — that's the scraper's raw intermediate, not read at runtime.)
