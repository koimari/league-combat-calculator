# Surface-area campaign — results

Range `3465a1d..64494e9` (39 commits, 698 files, +7,422 / −76,360). Ten units plus a
blind-audit remediation wave, run one at a time by subagents; every unit's report was
reconciled against its diff before the next launched. Rule applied throughout: the more
complete path wins; a thing is wired in only when its purpose is uncovered and necessary,
otherwise cut.

| Unit | Landed | Decision |
|---|---|---|
| U01 closed-campaign instruments | `1b45e78` | Cut 4 scripts, 13 tests, 351 receipts (−69.6k). Kept `term_census`, `capture_coverage_classification`, `receipt_walk_schedule` — `src`/live gates read them. |
| U02 second payload builder | `4893244` | `feedback.js` DOM scrape gone; receipts carry the payload that produced the displayed total; `displayed_prediction` mirrors the UI's main-row rule. |
| U03 offline registry fallback | `5055dc5` | Three `except Exception → snapshot` arms and 7 per-key literal reads gone; registry fails closed naming item+key. Snapshot kept as `_REFERENCE_ITEM_EFFECTS` (schema source, static keys, 299-value parser pin). |
| U04 stat-derivation | `e037378` | Neither flip nor cut: `item_coverage` reads the declarations generically for target-lane coverage. `PRECEDENCE` mirror, `_RULE_CLAIMS`, 5 empty `UNMIGRATED_*` scaffolds, `stat_slots` cut (−1,651). |
| U05 declared gates | `72eb89c` | `coverage_census` wired (own CI job + patch day; 9-min run, uncovered by any other gate). `refresh_economics_data` wired into patch day with a drift test. |
| U05b census red cells | `0ff91c6` `b0f7252` `5c8390f` `1fb7dbc` | Trigger-gated item mechanics (Horizon Focus, Malignance, Zeke's) were **firing without their trigger** in `auto_only`; fixed. Forced attacks carry their slot's control marker. 16 Bloodsong rows acknowledged. Gate green: 117 cells, none unacknowledged. |
| U06 dead scanner, generic parser | `0f0e11e` `4fabdee` | `champion_coverage.py` and `generic.py` gone; `synthetic=` removed from `run_fight`; rule 7 text matches the code. `/api/champions` byte-identical. |
| U07 registry aliases, module footer | `5372d38` `89a05f4` | One dict, one accessor, one count. 173 `REVIEW_STATUS` lines and 84 derivable `MODULE_COVERAGE` maps derived by the contract; shared helpers in `module_helpers`. Contract dumps byte-identical. |
| U08 packet-module rebinds | `d99495d` `d40c608` | 65 modules stop discarding the compiled parser (`slot_parsers`/`slot_wrappers`/`slot_order`); the SHA pin is surveyed, disagreement raises. 173×3×7 parse dumps identical. |
| U09 defenses getattr | `5a260de` `a0ffa42` | 49 unreachable defaults gone; `Combatant.defenses: StartingDefenses` checked at build. Bench within noise. |
| U10 API/UI fallbacks | `53f778c`…`4e7e4de` (13) | Activation metric cut (its surface was deleted); utility reads the main's own ledger; trust chips render errors, not mocks; `/api/items` serves every display number from the typed accessor; 5 dead/duplicate routes cut (36→31); GET args through `request_parsing`. |
| U11a audit: moved numbers, MR double-home | `163214d` `fd537cc` `23af61b` `3f1490b` | Ruled from Fimbulwinter rev 3984419 (a melee slow arms Everlasting): the engine stands; 208 moved cells enumerated, 6 with served numbers, now covered by `everlasting_forced_swing_roster` in the coupled golden; ruling in `docs/item-source-reconciliation.md`. Served MR follows the rotation's accepted R; `_ultimate_scheduled` gone. |
| U11b audit: contract, tests, docs | `cfb8b5d` `94b6adb` `5f2ba18` `a66e938` `64494e9` | `single_hit_slots` refuses an entry that reaches no row; the contract refuses a restated `REVIEW_STATUS`/`PACKET_SPEC`/derivation-equal `MODULE_COVERAGE` (12 more maps gone); the inverted coverage test runs forward; `Agents.md` is a pointer; stale skill/prose/clamps fixed. |

## Gates (fresh, final tree)

| Gate | Result |
|---|---|
| `black --check src/ tests/ scripts/` | 774 files unchanged |
| `pylint src/ --fail-under=9` | 9.63/10 |
| `golden_snapshot.py compare` (pair and coupled) | identical |
| `coverage_census.py check docs/coverage-census.json` | passes: 117 cells, 41 acknowledged |
| `pytest` | 9,431 passed |

## Audit

A blind `elegant-design:code-reviewer` pass over `3465a1d..4e7e4de` returned *changes
requested*: one critical (b0f7252 moved coupled survival numbers under a "no number moves"
claim; the golden had no covering cell) and seven important items. All were remediated in
U11a/U11b above; category 1 (a deleted live reader/writer) came up empty after a real search.

## Findings the campaign overturned or widened

- U03: the snapshot's "dev convenience" purpose was 1 of 4; the others are live.
- U04: "26 unread rules" was a by-type-name grep; `payload.granted` reads made them live.
- U05b: the "inert" items were adding damage (26.0 on an Ahri who cast nothing) — a numbers bug, not a label.
- U10 item 4: `/api/items` stat values were all literal-zero fallbacks; the snapshot preference was masking it.

## Left on the table (asides worth a unit)

`/api/champions` publishes one registry fact in five fields · `feedback.js` still hand-rolls two POSTs · `economy.item_total` cache fallback is now dead for SR items and could raise · `static/data.json` has no generator and is one patch stale · `tests/test_migration_frontier.py` and `test_trigger_stream.py` still walk git history (the reason CI keeps a full-depth checkout) · Liandry's/Blackfire burns fire in `auto_only` without an ability hit (same family as U05b) · `pylint_ratchet.py` is a declared gate nothing runs.
