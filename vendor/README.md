# vendor/

External code vendored into this repo. Nothing in here is ours — don't
refactor or restructure it (minimal, targeted bug fixes only; see CLAUDE.md).

## lolstaticdata/

[meraki-analytics/lolstaticdata](https://github.com/meraki-analytics/lolstaticdata) —
the wiki-scraper library `data_updater.py` drives to pull champion/item data.

Its layout is confusing at first glance; only `lolstaticdata/lolstaticdata/`
(the nested Python package) is real code. Everything else appearing at its
root is the scraper's own gitignored scratch output, written next to the
package by upstream design:

- `__cache__/`, `__wiki__/` — downloaded wiki/ddragon pages
- `champions/`, `items/`, `champions.json`, `items.json` — raw generator output

None of that scratch is read by the calculator at runtime. The calculator's
real data cache is `data/` at the repo root, written by `data_updater.py`
(which post-processes the scraper's output) and read via `data_fetcher.py`.
