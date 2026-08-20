# Surface-area backlog

What the surface-area campaign (`docs/plans/2026-08-20-surface-area-campaign.md`) surfaced
but did not fix: asides from the eleven unit reports and the blind audit, de-duplicated and
re-verified against the tree at `0fa19e6`. Ordered by the cost paid today. Delete a row
when its fix lands; this file is the one home for the list.

## A. Engine numbers and semantics

| # | Where | What | Action |
|---|---|---|---|
| A6 | `damage.py:1403-1781` `_ordered_damage_events` (+ `_event_timeline_coverage` ~1782) | One row schema in six literal spellings (light tuple / lean dict / full dict × `add` / `add_declared_events`), kept in step by a comment. | One row factory the three shapes project; float-addition order is load-bearing (`survival/accumulate.py`), so golden must show zero diffs. |

## B. Fallbacks and single-home violations still standing

| # | Where | What | Action |
|---|---|---|---|
| B1 | `src/calculator/economy.py:55-73` `item_total()` | Falls back to the wiki-cache total when no sourced row exists. `refresh_economics_data.stale_reasons` now guarantees a row for every ordinary SR item, so the fallback is dead for them and silent for anything else. | Raise. |
| B2 | `item_effects.py` ~4811 `ITEM_EFFECTS[name].get("ultimate_haste", 0.0)` | Same uneven-sibling read the U03 sites had. | `_declared_effect_value`. |
| B3 | `item_effects.py` ~32 `ENERGIZED_SOURCE_RECEIPT["distance_units_per_stack"]` | No src reader (only `tests/test_issues_45_43.py:388`); a second home for the per-item static key's 24.0. | Delete; the static key is the owner. |
| B4 | `passive_parser.py:2742-2745` `parse_all_item_effects` | Silently drops an item whose `parse_item_effect` returns None/empty; surfaces only on read or via the parity test. | Raise naming the item. |
| B5 | `roster_composition.py:101,150-155`, `participant_timeline.py:965/975` (`Combatant.request: Any`); `survival/transitions.py:261,264` `getattr(self.ledger, "records_*", True)`; `program/compile.py:1569-1575` `getattr(payload, …)`; `item_coverage.py:~635-660`, `interpreters/stat_derivation.StatSlot.granted`, `gated_state_reason` `getattr(payload, name, None)` | The U09 family on other subjects: declared-absence reads across typed objects. | Type the field (Protocol/Union) and read directly, as 5a260de did for `defenses`. |
| B11 | `static/data.json` | Hand-committed, no generator in `scripts/`, one patch stale. **Measured:** of its champion keys only `key`, `title`, `tags`, `resource` and `abilities` are read (`app.js:731,2556,3480,2395,685`); every stat key and `id`, `abilityCoverage`, `source`, `patch`, `coverage` are dead — stats come from `/api/loadout-stats`. Every item key is dead or overwritten by `/api/items`/`/api/boots` (`mergeItemCoverage` spreads the backend over the snapshot and `renderPicker` filters through `backendItemReady`), so the stale cells are unreachable; only `passiveText` is unique, and nothing reads it. Inside `abilities` the UI reads only `slot`, `name`, `icon`, `maxRank`, `maxHits`, `variants[].name` and `variants.length` — never a ratio. | Shrink: drop `items`, `patch`, `coverage` and the champion stat keys. Needs the `app.js` owner (`DATA.items` must stay an array or `engine.itemCatalogReady` never sets) and a browser pass, so it did not land with the scripts slice. |

## C. API / UI

| # | Where | What | Action |
|---|---|---|---|

## D. Champion package

| # | Where | What | Action |
|---|---|---|---|
| D3 | ~40 custom parsers (`akshan.py:257`, `darius.py:215`, …) | `entry["event_order_certified"] = "single_hit"` hand-assigned — the fact, not a wrapper; fine, but `single_hit_slots` now exists for packet rows. | Opportunistic. |
| D11 | `survival/compile.py:69-70` `requires_holder_health_ratio` | Can no longer fire — Knight's Vow's packet also carries `redirect_fraction`, which refuses first. | Delete or reorder deliberately. |

## E. Tests and gates

| # | Where | What | Action |
|---|---|---|---|
| E3 | `tests/test_migration_frontier.py:150-170,305` (`REPORT_TIP="067c94c"`), `tests/test_trigger_stream.py` ~2711-2800 (`git archive <commit>` per test) | Closed-campaign git walks inside kept product tests; the reason CI keeps `fetch-depth: 0`. | Pin the artefacts, drop the history walk, shallow-fetch CI. |
| E12 | `tests/coverage_resolver.py` (1.8k) + `test_coverage_claims.py` (2.7k, subprocess pytest at `:654`) + `coverage_evidence.py` (1.1k) | 5.6k lines proving evidence strings name real symbols, run through `conftest.py` on every `pytest -k`. | Not deletable; worth knowing it is the largest non-domain cost per run. |
| E14 | `scripts/load_sanity.py` | Updated in 39d3794 for `checks.cache`; not run live (needs `DATABASE_URL`/`REDIS_URL`). | Run once against a deployed target. |

## F. Data and receipts

| # | Where | What | Action |
|---|---|---|---|
| F5 | `item_effects.py:2417` `everlasting_trigger_kind: "crowd_control"` | Not what the consumer keys on (it reads `CcClass` from the bus). | Delete the key. |

## G. Traps (informational — not fixes)

- Compiled slot order is Q,W,E,R,P while `REQUIRED_CHAMPION_SLOTS` is P,Q,W,E,R; the ledger replays insertion order for float sums, so any reorder is a numeric change.
- `interpreters._threshold_regeneration_thresholds` now stops the whole `uncompilable_item_receipt` call on one broken declaration (request-level, not per-item) — intended since 5055dc5.
- `sed -i` in Git-Bash strips CRLF; use byte-preserving scripts for bulk edits on this tree.
- Two Claude Code sessions in one worktree: a `git checkout -- <dir>` in one discards the other's uncommitted edits. Use a second worktree.
