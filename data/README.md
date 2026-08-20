# data/

The calculator's champion/item data cache — the single source the app reads.

- `champions.json`, `items.json`, `runes.json` — patch-stamped wiki data,
  written only by `src/calculator/data_updater.py`, read only through
  `src/calculator/data_fetcher.py`. `runes.json` holds all 62 runes —
  the roster Data Dragon's `runesReforged.json` states, parsed from the
  wiki's `Template:Rune data <name>` pages by `src/calculator/rune_parser.py`
  — plus two page-level blocks under reserved keys the runes do not own: the
  Rune page's stat-shard table (`shards`) and `Template:Adaptive`'s
  adaptive-force conversion (`adaptive_force`), each with the revision it was
  read at.
- Tracked in git deliberately: patch-day diffs against HEAD are how
  `scripts/patch_update.py` audits what changed.
- Never hand-edit; refresh via the app's "Update to latest patch" button or
  `python scripts/patch_update.py run`.

## Item source fields

`src/calculator/item_source.py` owns these; every item entry carries them.
They exist so nothing about an item is decided by a hand-maintained list.

| Field | Source | Used for |
| --- | --- | --- |
| `modes` | Wiki `modes` | Map/mode availability (`classic sr 5v5`, `aram`, `nb`, `ar`) |
| `championRestriction` | Wiki `champion` + Riot `requiredChampion`/`requiredAlly` | Champion-granted items (Black Spear) |
| `acquisitionNote` | Wiki `req` | Quest transforms that are never sold |
| `specialStats` | Wiki `stats.spec` | Stat lines with no numeric field (Cull's `+3 health on-hit`) |
| `riotDescription` | CommunityDragon `description` | Verifying the Wiki cache against Riot offline |
| `passives[].branches`, `active[].branches` | Wiki `description`, `description2`, … | The **complete** text of one effect; replaces the old single `effects` string, which truncated multi-branch passives |
| `sourceWarnings` | ingestion | Anything the merge could not match, named rather than dropped |

A rune-ingestion fix reaches this cache without a whole patch pull through
`python scripts/reparse_runes.py` (`--check` reports drift without writing);
item-ingestion fixes go through a full `data_updater` pull.

(Not to be confused with `vendor/lolstaticdata/`'s scratch output of the same
names — that's the scraper's raw intermediate, not read at runtime.)
