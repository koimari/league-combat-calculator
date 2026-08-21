# Coverage-frontier campaign — close what `docs/coverage-frontier.md` lists as closable

Measured at `5af69843`. Frontier page: `docs/coverage-frontier.md`; machine truth:
`docs/coverage-census.json`, module contracts, `item_effects.ITEM_EFFECTS`, `data/runes.json`.

## Recon corrections (runtime-probed this session)

| Frontier claim | Probe result | Consequence |
|---|---|---|
| 34 effect-bearing items lack `ITEM_EFFECTS` | `item_coverage.optimizer_candidate_coverage` says *fully modelled* for all 34 (reviewed stats-only / state / support claims) | Only Imperial Mandate + Echoes of Helia carry unpriced damage |
| GW items: "engine cannot apply Grievous Wounds" | `healing_reduction.healing_reduction_profiles` returns 0.6×/3 s for Morello, Oblivion Orb, Chempunk, Executioner's | Verify it bites in the coupled walk; then correct the page |
| Samira Q/W/E, Yasuo R, Kindred Q, Kai'Sa P "worth a module update" | `parse_abilities` emits Q 240 / W 260 / E 110, R 650, Q 215 raw; Kai'Sa P rows ride W/Q | `MODULE_COVERAGE` misreports (since `b03bbad9`); fix the maps |
| Minor runes not cached | all 45 `Template:Rune_data_<name>` pages parse via `rune_payload`; Data Dragon `runesReforged.json` (already fetched for icons) carries the roster, path and row | Roster becomes data-driven; no new scraper |

## Decisions

1. **A rune page, not a keystone field.** Request gains `minor_runes: list[str]` (≤5) and
   `stat_shards: list[str]` (≤3); `keystone` is unchanged. `rune_effects` validates the page
   like `loadout_rules` validates inventory: every name compiled (unknown or unmodeled fails
   closed, as keystones do), no duplicates, one rune per (path, row), ≤3 from one path and
   ≤2 from a second, the keystone's path (when set) is the 3-rune path, shards one per row.
2. **One rune vocabulary.** Minor runes compile to the effect classes keystones already use
   (`KeystoneProcEffect`, window/proc amps, no-damage disclosure) plus the two kinds the
   keystones lack: a *stat grant* (flat, leveled, adaptive, or option-gated stacks) applied
   where item stats are applied, and a *conditional damage amp* (target-health, relative
   max-health, self-health) applied where item damage amps apply. The proc walker
   (`damage._add_keystone_damage`) walks a list of rune effects, keystone included. A new
   effect kind is added only when no existing kind can express the rune, and then once.
3. **Compilers live one file per path**: `src/calculator/rune_paths/{precision,domination,
   sorcery,resolve,inspiration}.py`, each exporting `COMPILERS`. `rune_effects.py` stays
   the public surface (resolve, validate, catalog, effect types). Keystone compilers stay
   where they are. Rule 5 holds: every number reads `data/runes.json` through typed
   accessors; missing keys raise naming the rune and key; grep-clean elsewhere.
4. **Roster from Data Dragon, text from the wiki.** `data_updater` derives the rune roster
   (name, path, row) from `runesReforged.json` and pulls each `Template:Rune_data` page as
   today; `KEYSTONE_NAMES` is retired. A rune whose template fails keeps its `error` entry.
   Stat shards come from the wiki's shard data the same way; no literal shard table.
5. **An input the request lacks becomes an explicit option with a disclosed default**
   (Gathering Storm's game minute, Legend stacks, Eyeball/Hunter stacks, Sudden Impact's
   dash) — never an inferred constant. Options follow the champion-option shape and reach
   `/api/config`.
6. **Coverage maps tell the truth.** A slot that emits a priced row is `modeled`; a slot
   that emits nothing and whose kit deals nothing there is `no_damage`; `out_of_scope`
   means the engine has no axis, and the module docstring names the axis. Each of the ten
   frontier slots is either priced or re-sourced with the reason in its docstring.
7. **Mandate and Helia price in the coupled roster** through `ally_effects` /
   `item_behavior_catalog`, the same layer that prices Bloodsong's Expose Weakness — not in
   `ITEM_EFFECTS`. Rylai's adds no damage and stays a reviewed state item.
8. **The utility axis is measured before it is built.** A read-only census classifies every
   `out_of_scope` slot by mechanism and names the engine home that already exists for it
   (healing rules, shield ledger, `MODULE_CC`, roster allies). Wave 2 is cut from that
   table; nothing is reclassified by relabeling.
9. **The Fimbulwinter residue stays acknowledged.** Its 100 cells need cadence the source
   does not state; `docs/coverage-residue.json` is the home and is not touched.
10. **Numbers move only with a receipt.** Default requests (no minor runes, no shards) are
    numerically identical to today; the golden gate proves it per unit. A unit that moves a
    golden number ships `docs/receipts/expected-golden-diff-<unit>.json` and the explanation
    in its commit. `docs/coverage-census.json` is regenerated once, at integration close.

## Shape (file ownership per unit; no two live units share a file)

| Unit | Owns | Lands |
|---|---|---|
| A1 rune page | `rune_effects.py`, `rune_parser.py`, `data_updater.py`, `data/runes.json`, `pipeline.py`, `damage.py` (rune walker), `stats.py` (rune stat grant), `app.py` `/api/config`, `app.js` rune picker, `rune_paths/__init__.py`, tests | request fields, validation, data roster, effect kinds, walker, four exemplar compilers (Absolute Focus, Coup de Grace, Scorch, Cosmic Insight) |
| B runes I | `rune_paths/precision.py`, `rune_paths/domination.py`, tests | 18 compilers |
| C runes II | `rune_paths/sorcery.py`, `rune_paths/resolve.py`, `rune_paths/inspiration.py`, tests | 27 compilers |
| D shards | shard parse + `stat_shards` compile, tests, picker row | 9 shard options across 3 rows |
| E champion maps | `champions/{samira,yasuo,kindred,kaisa,aurelion_sol,wukong,rumble,kogmaw,mel}.py`, their tests | ten slots priced or re-sourced |
| F Mandate/Helia | `ally_effects.py`, `item_behavior_catalog.py`, `participant_timeline.py`, `item_coverage.py`, tests | coupled ally packets priced |
| G GW proof | probe script under `scripts/` only if kept; otherwise no code | runtime receipt that anti-heal bites; fixes if it does not |
| H0 utility census | read-only; writes `docs/plans/utility-axis-census.md` | mechanism × engine-home table |

## Waves

- **Wave zero**: A1 · E · F · G · H0 (disjoint files).
- **Wave one**: B · C · D (on A1's shape).
- **Wave two**: utility mechanisms with an existing engine home, cut from H0's census by
  champion-module ownership (support scanner, stat buffs, damage riders, sustain, relabel);
  runs alongside wave zero since no files overlap.
- **Close**: census regenerated, frontier page rewritten from fresh probes, gate ladder once.

## Success criteria

1. `/api/calculate` with a legal full rune page (keystone + 5 minors + 3 shards) returns
   for every champion; every roster rune compiles (`rune_catalog()` all `implemented`);
   an illegal page (two runes one row, unknown name, 4 from one path) returns 400 naming
   the rule. Runtime probe per effect kind quoted in its test.
2. A default request's numbers are identical to `5af69843` (golden pair + coupled).
3. The ten frontier champion slots report `modeled` or carry a docstring reason; the
   champion probe in `docs/coverage-frontier.md` shows the new counts.
4. A coupled fight with Imperial Mandate / Echoes of Helia on a roster ally prices the
   ally packet, with numbers quoted against the wiki sentence.
5. A coupled probe shows enemy healing reduced by the GW factor with each of the four items.
6. Gate ladder, fresh at the merge head: `pytest`, `black --check src/ tests/ scripts/`,
   `pylint src/`, golden pair + coupled, `coverage_census.py check` on the regenerated
   receipt, `plan_audit.py`.
7. `docs/coverage-frontier.md` re-measured and rewritten; `docs/surface-area-backlog.md`
   gains any aside a unit surfaces.

## Results

Range `5af69843..` the merge head of `fc/integration`; sixteen Opus units, one worktree each,
file-ownership slices, every report reconciled against its branch before merging. Numbers
in this table are each unit's runtime probe.

| Unit | Landed | Decisive finding |
|---|---|---|
| H0 | utility-axis census (136 rows) | `out_of_scope` was the *default* for any slot absent from `SLOTS`; only 55 of 136 had no axis |
| G | GW proof; Lifeline heal wounded | all four items already bit (Morello on Ziggs: Mundo's healing 1465 → 941); a Protoplasm Lifeline heal escaped (400 → 240) |
| F | ally-ramp level subject | decision 7's premise was stale: Mandate already priced (×1.07), Helia has no damage row; ramps read the recipient's level where the wiki says `your level` (80 → 232.65) |
| E | nine maps, Rumble P, Mel P | `b03bbad9` rewrote three coverage sets; Rumble overheated autos 295 → 601 |
| RELABEL | `COVERAGE_CHANNELS` | a slot with no row can be `modeled` by naming the channel that pays it; six mislabels, thirty axis clauses |
| RIDERS | five passives, two steroids | Warwick 10 s total 762 → 1226 |
| SUSTAIN | six heal rules, Vi P, grey health, Trundle W | Trundle 1134 → 1422 |
| STATBUFF | nineteen stat grants | Tristana autos 4 → 8; 85 slots with zero `out_of_scope` |
| SUPPORT | scanner scopes rows by their sentence | four fabricated packets killed; 36/70 → 60/70 modeled |
| SCANNER | recipient from the sentence | six more fabricated ally packets gone (Bel'Veth R, Ekko W, Vladimir R, Zilean R, …) |
| A1 · B · C · D · A2 · A3 | the rune page | 62/62 runes compile, 31 price, 9 shards price; `/api/loadout-stats` and focused BIS carry the page |

Frontier moved: champion slots 693 / 23 / 150 → 762 / 38 / 65 (modeled / no_damage /
out_of_scope); runes 17 of 17 keystones → 62 of 62 compiled; items: no unpriced damage
packet remains. Decisions overturned by probe: 7 (Mandate/Helia) and the GW row; decision 6
gained the channel vocabulary. Left on the table: `docs/surface-area-backlog.md` CF1–CF17
and the rune refusals by axis on `docs/coverage-frontier.md`.

## Banned shortcuts

- No rune number outside `rune_effects.py` / `rune_paths/`; no `.get(key, literal)`.
- No `modeled` on a slot that prices nothing; no `no_damage` on a slot the kit damages.
- No regenerating `docs/coverage-census.json` inside a unit.
- No worker claims "pre-existing failure" without a detached checkout of the base commit.
