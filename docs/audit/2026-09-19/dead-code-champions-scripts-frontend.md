# Dead code in champions, scripts, and the frontend

Scope: `src/calculator/champions/` at 207 modules and 57,976 lines, `scripts/` at 55
scripts and 45 assignment JSON files, and the frontend under `static/`, `templates/`,
and `ui/`. Read-only pass on a clean `main` at `1a58b1c4`.

## What the sweep found

Two of the three areas are near zero. The champion tree and the script tree hold no
unreferenced top-level name, no unused nested function, no unread OPTIONS key, no
identity slot override, and no repeated ASSUMPTIONS sentence. `module_contract.py`
already raises on a `MODULE_COVERAGE` that restates its derived default, so that
category cannot grow.

The removable weight sits in three places the gates do not look at:

1. 2.67 MB of unreferenced assets across 25 files under `ui/assets/league/`,
   `static/fonts/`, and `static/img/stat-icons/`.
2. A public facade with no importers. All 16 `__all__` entries of
   `src/calculator/__init__.py` are unread, which keeps one dead module and one dead
   accessor alive.
3. Two spent one-off scripts, plus about 3,300 lines of applied module-split records.

Total removable: about 3,700 lines of text and 2.67 MB across 25 asset files. Excluding
the assignments compaction, which is a judgement call: about 400 lines and 2.67 MB.

## Summary: champions and the facade that keeps it alive

| # | Finding | Path | Lines | Confidence | Proposal |
|---|---|---|---|---|---|
| A1 | The `src/calculator` re-export facade has zero importers | `src/calculator/__init__.py:1-37` | 35 | High | Cut to `publish_rune_compilers()`, then run both golden compares |
| A2 | `champions/common.py` is a dead module | `src/calculator/champions/common.py:1-16` | 16 plus 12 test | High | Cut the module and its test class |
| A3 | `is_champion_supported` has one reader, the dead facade | `src/calculator/champions/__init__.py:1077` | 4 | High | Cut |
| A4 | `_SKILL_ORDERS["Vayne"]` equals `DEFAULT_SKILL_ORDER` byte for byte | `champions/skill_orders.py` | 6 | High | Cut the row |
| A5 | 13 of 17 `_SKILL_ORDERS` rows repeat one of three shapes | `champions/skill_orders.py:27-131` | 55 | Medium | Name the three shapes once |
| A6 | Six modules spell out `("P","Q","W","E","R")` for `slot_order` | maokai, rengar, samira, sett, yorick, zyra | 0 net | Medium | Point them at `REQUIRED_CHAMPION_SLOTS` |
| A7 | Stale ignore rule for the closed `champions/generated/` lane | `.gitignore:63-66` | 4 | High | Cut the rule and the empty directory |

## Summary: scripts

| # | Finding | Path | Lines | Confidence | Proposal |
|---|---|---|---|---|---|
| B1 | `testing_flag_codemod.py` has no targets left and a gate holds the count at zero | `scripts/testing_flag_codemod.py` | 98 plus 14 test | High | Cut the script and its one test |
| B2 | `install_wiki_refresh.py` writes a macOS launchd plist, and its test skips on Windows | `scripts/install_wiki_refresh.py` | 118 plus 12 test plus 14 doc | Medium | Cut. `patch_update.py wiki-refresh --scheduled` is the portable path |
| B3 | `scripts/assignments/*.json` records 45 applied splits that cannot be replayed | `scripts/assignments/` | 3,300 of 4,093 | Low to medium | Keep the `decisions` prose, drop the mechanical arrays |

The other 53 scripts all resolve to a live consumer. See "Scripts that are wired" below.

## Summary: frontend

| # | Finding | Path | Removable | Confidence | Proposal |
|---|---|---|---|---|---|
| C1 | `ui/assets/league/` holds 11 CommunityDragon files that no consumer reads | `ui/assets/league/` | 2,626 KB, 11 files | High | Cut the 11. Keep `README.md` and `source-manifest.json` |
| C2 | `static/fonts/` holds a Godya face with no `@font-face` anywhere | `static/fonts/` | 96 KB, 2 files | High | Cut |
| C3 | `static/img/stat-icons/` has never been referenced | `static/img/stat-icons/` | 15 KB, 12 files | High | Cut |
| C4 | `.ability-casts` styles a retired per-ability cast stepper | `static/css/style.css:550,559,567,576,578` | 5 | High | Cut the five selector lines |
| C5 | `.wiki-popover` names a class the code renamed to `.item-tip` | `static/css/scryglass-theme.css:71` | 1 | High | Cut |
| C6 | `championByName` is exported and never imported | `ui/src/scenario-state.ts:154-156` | 3 | High | Cut |
| C7 | `runeAssetVersion` is exported and never imported | `ui/src/rune-assets.ts:7` | 1 | High | Cut |
| C8 | Four DOM ids in `index.html` have no selector | `templates/index.html:322,451,459,563` | 4 attributes | Medium | Cut the `id` attributes |
| C9 | `architecture.md` cites a script this repo does not hold | `architecture.md:210` | 1 | High | Say the script lives in the consuming repo |

## A1: the calculator facade has no importers

`src/calculator/__init__.py` holds 19 import lines, an 18-entry `__all__`, and one call.
I checked every `__all__` name for a facade-shaped read across the whole tree, matching
`from src.calculator import X`, `from calculator import X`, and `calculator.X`:

```
16 __all__ entries, facade_readers=0 for every one:
ITEM_EFFECTS, FightConfig, apply_armor_penetration, apply_magic_penetration,
apply_resistance, calculate_ability_damage, calculate_fight_damage,
calculate_total_stats, fetch_champion_data, fetch_item_data, get_ability_rank,
get_champion, get_item_by_name, growth_stat, is_champion_supported, parse_abilities

grep -rn "^from src\.calculator import" src tests scripts   ->  0 hits
```

Every consumer imports the owning module instead, for example
`from .item_effects import ITEM_EFFECTS` and
`from .champions.skill_orders import get_ability_rank`. That is what architecture.md
asks for under one owner per value. The facade was meant to be a public front door. The
front door the repo has today is the HTTP boundary in `src/app.py`, and
`tests/test_architecture.py`'s `FRONT_DOOR_FRONTIER` measures a front door by import,
not by a re-export list.

Cut the file down to this:

```python
"""The calculator package. Import from the owning module, not from here."""

from .rune_paths import publish_rune_compilers

publish_rune_compilers()
```

`publish_rune_compilers()` stays. CLAUDE.md names `src/calculator/__init__.py` as its
one call site.

Gate the change. Removing imports moves import order, and CLAUDE.md records that
compiled slot order and ledger insertion order are numeric. Run
`golden_snapshot.py compare` against both `scripts/golden_baseline.json` and
`scripts/golden_coupled_baseline.json`. A pure facade cut must show zero diffs.

## A2: champions/common.py is a dead 16-line module

```
src/calculator/champions/common.py:10
    def calculate_ability_damage(base_damage, scaling_ratio, scaling_stat)
        return base_damage + (scaling_ratio * scaling_stat)

grep -rn "calculate_ability_damage" src tests scripts docs static ui .claude
    src/calculator/champions/common.py:10          the definition
    src/calculator/__init__.py:2,27                the dead facade and its __all__
    tests/test_champion_primitives.py:16,50,53,57  its own test
```

No engine code calls it. The module docstring says it "only keeps the scalar helper that
`calculator.__init__` re-exports", and A1 shows that re-export has no reader. Cut the
module, the two facade lines, and the `calculate_ability_damage` block in
`tests/test_champion_primitives.py`. I ran that file: 75 passed in 0.20s, so the rest of
it survives the trim.

## A3: is_champion_supported has one reader and it is dead

```
grep -rn "is_champion_supported" src tests scripts docs static ui .claude
    src/calculator/champions/__init__.py:1077   the definition
    src/calculator/__init__.py:1,36             the dead facade and its __all__
```

Real call sites answer the same question through `get_champion_module_contract`,
`engine_registration_kind`, or membership in `_CHAMPION_MODULES`. Cut it with A1.

## A4 and A5: skill_orders holds a redundant row and three repeated shapes

Runtime probe against the imported module, all 17 rows:

```
SAME-AS-DEFAULT Vayne QWEQQRQWQWRWWEEREE
DEFAULT               QWEQQRQWQWRWWEEREE
```

The `Vayne` override matches the default byte for byte, so the row changes nothing.
Three more shapes repeat across 13 rows:

| Shape | Rows |
|---|---|
| `QWEQQRQEQEREEWWRWW` | Singed, Dr. Mundo, Aurelion Sol |
| `QEWQQRQEQEREEWWRWW` | Anivia, Aurora, Camille, Corki, Jarvan IV, Bel'Veth |
| `QWEWWRWQWQRQQEEREE` | Amumu, Brand, Briar, Kog'Maw |

Cut the `Vayne` row. Name the three shapes once and point the 13 rows at them.
Cassiopeia, Azir, and Jayce stay literal. Each of those three is its own shape.
`get_ability_rank` output does not move, so no golden re-capture is needed.

## A6: no slot_order override is an identity, but the literal repeats

I patched `packet_module._apply_slot_overrides` and reloaded every module that declares
`slot_order`, recording the key order before the override ran:

```
reorder  Aphelios pre=('Q','W','E','R','P') order=('P','W','Q','R','E')
reorder  Maokai   pre=('Q','W','E','R','P') order=('P','Q','W','E','R')
reorder  Rengar, Samira, Sett, Yasuo, Yorick, Zyra   all ('P','Q','W','E','R')
reorder  Yone     pre=('Q','W','E','R','P') order=('P','Q','W','R','E')
```

Every override changes the order, so none is removable. Six modules spell out
`("P","Q","W","E","R")`, which is already
`contract_vocabulary.REQUIRED_CHAMPION_SLOTS`. Pointing them at that constant costs no
lines and removes a hand-typed value that CLAUDE.md flags as numeric. Gate the edit with
both golden compares.

## A7: the closed generated lane left a stale ignore rule

```
.gitignore:63-66
  # Closed generated-modules lane: build_reviewed_modules.py emits regenerable
  # stubs here on patch-day runs, but the roster is registry-only (no generated/
  # lane, see .agents/skills/add-champion). The packet asset is static/reviewed-packets.json.
  src/calculator/champions/generated/
```

`src/calculator/champions/generated/` exists on disk and is empty. `git ls-files`
returns nothing for it. `scripts/build_reviewed_modules.py` has one writer,
`output.write_text` at line 565, and it targets `static/reviewed-packets.json`. The rule
describes an emitter that no longer runs. The comment also points at
`.agents/skills/add-champion`, which does not exist. `.agents/skills/` holds only a
two-line README saying skills live in `.claude/skills/`. Cut the four ignore lines, cut
the empty directory, and drop the `.agents/` pointer.

## Champions: what the sweep proved clean

| Check | Method | Result |
|---|---|---|
| Unreferenced top-level names across 207 modules | AST top-level definitions against a whole-tree word index, minus the names `module_survey`, `module_contract`, `cast_dependency`, and `healing` read through string literals | 0 |
| Unused nested functions | AST parent and child walk over `champions/` and `scripts/` | 0 |
| `vulture --min-confidence 60` over `src scripts tests static ui` | Whole-tree scope | 3 hits in champions, all `CAST_DEPENDENCIES`, which `module_survey.py:94` reads through a string literal. False positives |
| OPTIONS keys with no reader | 147 modules, extracting literal `"key"` entries and the first argument of every `*_option(...)` call, checked against the module body, sibling champion modules, `src/`, `tests/`, `static/js`, and `ui/` | 0. Twenty-six keys are read outside their own module by `aphelios_weapons`, `projectile_defense`, and `interaction_effects`, all legitimate |
| Identity `slot_order` or `slot_wrappers` | Runtime probe described under A6 | 0 |
| `MODULE_COVERAGE` restating its derived default | `module_contract.py:82-87` raises `ChampionModuleContractError` at import | Structurally impossible |
| Repeated ASSUMPTIONS sentences | AST `literal_eval` over every module | 502 sentences, 502 distinct, 0 repeats |
| Duplicated module-level constants | AST `literal_eval`, grouped by name and value | 10 groups, every one a coincidence of per-champion sourced facts such as `_Q_CAST_TIME = 0.25` for Galio, Karthus, and Taliyah. Each belongs to its champion |
| Helper-module symbols with no champion caller | Per-symbol reader map over `slotlib`, `module_helpers`, `shared_mechanics`, `stat_grants`, `stat_ramp`, `armed_procs`, `cast_arming`, `charge_cadence`, `pet_window`, `skill_orders`, `attribute_classifier`, `scaling`, `slot_extract`, `slot_entries`, `slot_control`, `slot_cc`, `slot_context`, `entry_shape`, `inputs`, `packet_module`, `packet_parsers`, `module_contract`, `module_survey`, `contract_vocabulary`, `source_receipts`, `engine`, `healing_contract`, `healing_helpers`, and `ability_prose` | Every symbol with no external reader has an in-module caller. Nothing dead |

## B1: testing_flag_codemod.py finished its job

The codemod deletes per-test `app.config["TESTING"] = True` lines. None remain, and
`tests/test_testing_flag_borrow.py::test_no_test_assigns_the_shared_testing_flag` holds
the count at zero:

```
grep -rn 'config\["TESTING"\]' tests/ src/
    the gate's own fixtures, prose in tests/process_state.py, and
    tests/app_config.py, which the gate lists as EXEMPT
```

Its one remaining reader is `tests/test_testing_flag_borrow.py:18`, feeding
`test_the_codemod_keeps_crlf_and_refuses_a_sole_statement`. That test exercises a tool
with nothing left to run on. Cut the 98-line script, the two import lines, and that one
test. The other three tests in the file are the live gate and stay.

## B2: install_wiki_refresh.py is a macOS-only convenience

The script is 118 lines and its whole output is a launchd property list. The scheduling
logic lives in `scripts/wiki_refresh.py::scheduled_refresh` and is reachable portably:

```
python scripts/patch_update.py wiki-refresh --scheduled --anchor-date 2026-09-09
    scripts/patch_update.py:1409-1449
```

Two facts say the launchd lane has never run on this tree:

```
tests/test_wiki_refresh.py:20  posix_lock = pytest.mark.skipif(os.name != "posix", ...)
data/wiki/wiki-schedule/       does not exist, though the doc promises receipts there
```

The primary machine is Windows 11 and the deploy target is Docker. Readers are the
"Deterministic macOS schedule" section of `docs/wiki-refresh.md`, about 14 lines, and
`tests/test_wiki_refresh.py:16` with
`test_launchd_command_round_trips_with_spaces`, about 12 lines. Cut all three. Keep
this at medium confidence: if a macOS box does run this fortnightly, keep the script and
record that fact in the doc.

## B3: scripts/assignments holds 4,093 lines of applied records

There are 45 JSON files. `damage.json` alone is 1,855 lines. The docstring of
`extract_modules.py` states the constraint: "A run may be followed by edits the mapping
does not carry, and those live in the file's `decisions`, so the record is reviewable
rather than replayable." Every `source` path still exists.
`tests/test_extract_modules.py::TestCheckedInAssignments` asserts only that each declared
`modules[].path` is a file on disk.

The `decisions` prose carries knowledge the tree does not. One example from
`damage.json`: "DEFAULT_CAST_ORDER moves to fight/cast_slots.py despite the brief's
residue list: setup/combat_state.py and ledger/pool_walk.py read it, and a moved module
may not import the residue." Keep that.

The mechanical half is different. The `modules[].defs` name arrays, `packages`,
`residue`, and `external_readers` record a state the tree now is, and no run can replay
them. That half is about 3,300 lines whose only consumer is a path-existence assertion.

Proposal, at low to medium confidence: compact each file to `source`, `decisions`, and
the `string_annotations` blocks, and have the test assert the `source` path. If the team
values the full record, leave it and say so in `CLAUDE.md`.

## Scripts that are wired

I mapped all 55 scripts against `.github/workflows/tests.yml`, `ci/*.sh`, `Makefile`,
`CLAUDE.md`, `.claude/skills/**`, `docs/**`, `tests/**`, and sibling scripts.

- CI gates, five: `golden_snapshot.py`, `acceptance_matrix.py`,
  `champion_optimizer_matrix.py`, `validate_receipt.py`, and `coverage_census.py`, at
  `tests.yml:56,63,65,84,151` and in `ci/fast.sh`, `ci/test.sh`, `ci/coverage_census.sh`.
- Tools that `CLAUDE.md` documents: `literal_defaults`, `swing_stream_audit`,
  `prose_lint`, `patch_update`, `bench_request`, `bench_optimize_build`,
  `build_icon_sprite`, `scoreboard_corpus`, `coverage_status`, `certify_damage_casts`,
  `receipt_walk_schedule`, `cast_dependency_audit`, `behavior_frontier`,
  `capture_coverage_classification`, `repin_corpus`, `item_umbrella_audit`,
  `extract_modules`, `rename_evidence`, and `fight_trace`.
- Patch-day chain that `patch_update.py` calls: `build_ability_catalog`,
  `build_bis_profiles`, `build_effect_catalog`, `build_onhit_matrix`, `build_receipts`,
  `build_reviewed_modules`, `build_static_data`, `refresh_economics_data`,
  `patch_mechanics`, `patch_regression`, `wiki_refresh`, `full_entry_audit`, and
  `decompose_wiki`.
- Libraries with two or more script consumers: `source_receipt`, `gate_receipt`,
  `generated_file`, `module_readers`, and `module_units`.
- Gates a test runs: `internal_row_census`, whose `check` runs in
  `tests/test_internal_row_census.py` and whose receipt `fight_receipts.py:95` and
  `public_response.py:159` cite, and `tail_site_triage`, which
  `tests/test_er5_tail_triage.py` runs and `docs/surface-area-backlog.md` cites.
- Operator tools with a runbook: `backup_db` in `docs/backup-runbook.md`, `load_sanity`
  and `beta_metrics` in `docs/monitoring.md` and `docs/beta-metrics.md`,
  `decompose_binaries` in `data/bin/README.md` and `binary_roots.py`, `reparse_runes` in
  `data/README.md`, and `atomize` with `extract_atoms` in the `atomizer` skill.

All three `scripts/golden_*.json` files are read. `ci/fast.sh:26-27`, `ci/test.sh:20-23`,
and `tests.yml:56` compare against `golden_baseline.json` and
`golden_coupled_baseline.json`. `tests/test_golden_snapshot.py` consumes
`golden_coupled_exact.json` through `rebuild_for`, exactly as `CLAUDE.md` records. No
orphan JSON sits under `scripts/`.

Dead top-level names across all 55 scripts: one.
`golden_snapshot.py:550 FINGERPRINT_COUNT_FIELDS` is read by
`tests/test_golden_snapshot.py`, so it is a legitimate test-facing constant.

## C1: ui/assets/league holds 2.6 MB that no consumer reads

Eleven files, 2,626 KB. The consumers that were meant to read them point at
CommunityDragon instead:

```
ui/src/champion-hud.css:412,426,431,436,471,497
  background-image: url("https://raw.communitydragon.org/16.17/game/assets/ux/lol/clarity_hudatlas.png");

ui/src/rune-assets.ts, all five paths
  background: "https://raw.communitydragon.org/16.17/plugins/rcp-fe-lol-collections/.../environment.jpg"

grep -rn "client-collections|playerframe|playerinventory|rune-keystone-border|assets/league" \
     ui/src ui/*.mjs tests scripts src .github ci    ->  0 hits

ui/build.mjs copies one asset: assets/favicon.svg
```

| File | KB | Why it is dead |
|---|---|---|
| `clarity_hudatlas.png` | 359 | `champion-hud.css` loads the remote copy |
| `clarity_hudatlasupdate.png` | 363 | Same |
| `client-collections.css` | 437 | The README calls it research evidence. One line, no importer |
| `playerframe-layout.json` | 375 | Its geometry is already transcribed into the README table |
| `playerinventory-layout.json` | 179 | Same |
| `rune-environment-8000.jpg` and four siblings | 911 | `rune-assets.ts` uses the remote URLs |
| `rune-keystone-border.svg` | 0.6 | No reader |

`ui/assets/league/README.md` states the design the code follows: "Components can instead
use the exact versioned remote URLs from the manifest." Its "Serving" section describes a
copy step into `static/calculator/league/` that `build.mjs` never implemented.
`source-manifest.json` records each file's URL, SHA-256, byte length, and dimensions, and
nothing reads it programmatically. There is no test and no `--check`, so nothing breaks.

Delete the 11 files. Keep `README.md`, whose geometry table is the distilled evidence,
and `source-manifest.json`, whose hashes make any file one `curl` away.

## C2: static/fonts is orphaned typography

```
grep -rni "godya|balinese" src tests templates static/css static/js ui/src docs  ->  0 hits
grep -rn "font-face" templates static/css static/js ui/src                       ->  0 hits
git log --oneline -- static/fonts/
    79826900 Polish UI panels with transparency and Godya typography (#185)
tests/test_redesign_frontend.py:566
    assert fonts and "Atkinson" in fonts[0]["href"]
```

The page loads Atkinson from Google Fonts. The Godya `.otf` and its OFL licence stayed
behind. The only other mention in the checkout is a stale `tests/__pycache__/*.pyc`. Cut
both files, 96 KB.

## C3: static/img/stat-icons has never been referenced

Twelve PNG files, 15 KB, present since commit `4c582085`.

```
grep -rn "stat-icons|stat_icon|statIcon" src tests templates static ui
    ui/src/champion-hud.css:561  .champion-hud-stat-icon   an unrelated CSS class
    static/calculator/calculator.css                       the minified build of that class

static/js/app.js builds every image path from ddragon, plus one literal:
    app.js:19  PRACTICE_DUMMY_IMAGE = "/static/img/practice-dummy-enemy.png"
```

Two of the twelve are byte-identical, `armor_penetration.png` and `lethality.png`, which
is itself a sign nobody wired them. The other four files under `static/img/` are live:
`practice-dummy-enemy.png` at `app.js:19`, `rift-background-user.webp` in `style.css`,
and `rift-illustration-4k.webp` with `summoners-rift-bg.png` at
`templates/index.html:176` and `:9`. Cut the twelve, 15 KB.

## C4: .ability-casts styles a control that no longer renders

```
grep -rn "ability-cast" static templates ui src tests
    static/css/style.css:550,559,567,576,578   five selector-group members
    nothing else. No JS emits the class and no template carries it.
```

Those five lines sit inside groups whose siblings `.ability-rank` and
`.ability-variants` do render from `app.js`. The per-ability cast-count stepper went away
when every fight-scoring path moved to the shared `engineFightPayload` with
`time_based`, which architecture.md describes as "the engine's shared cast schedule where
an ability recasts whenever its cooldown is up inside the configured window". Cut the
five `.ability-casts` lines from the groups.

## C5: .wiki-popover names a class the code renamed

```
static/css/scryglass-theme.css:71   .calculator-advanced .wiki-popover,
static/js/app.js:1560               tip.setAttribute("popover", "manual");
static/css/style.css:2278           .item-tip.no-popover { display: none; }
```

The item hover card is `.item-tip`. No element carries `.wiki-popover`. The dead selector
is one member of a four-selector group whose other three, `.verdict`, `.site-footer`, and
`.buy-band`, are live. Cut the line. Note the consequence: the advanced page's item
tooltip is not receiving the Scryglass cream-token override the rule intended, so a small
visual gap hides behind the dead selector.

## C6 and C7: two unused UI exports

```
ui/src/scenario-state.ts:154  export function championByName(champions, name)
    1 occurrence in ui/src, 0 elsewhere
ui/src/rune-assets.ts:7       export const runeAssetVersion = "16.17"
    1 occurrence in ui/src, 0 elsewhere
```

Method: I counted every `export (function|const|class|type|interface|enum) NAME` in
`ui/src/**` across the whole `ui/src` corpus plus `tests/`, `docs/`, and `ui/build.mjs`.
Those two are the only exports with no second occurrence. Every non-test file under
`ui/src` is imported. `runeAssetVersion` also duplicates the `16.17` embedded in every
URL in its own file, so it is a duplicated constant as well as a dead one.

## C8: four DOM ids have no selector

```
templates/index.html:322  id="constraintsLabel"   the section already has aria-label="Constraints"
templates/index.html:451  id="hpBand"             the section already has an aria-label
templates/index.html:459  id="timelineBand"       the section already has an aria-label
templates/index.html:563  id="onboardingCounter"  app.js reaches it by .onboarding-counter
```

I checked each id against all of `static/js/*.js`, `static/css/*.css`, `tests/*.py`, and
every `for`, `aria-labelledby`, `aria-controls`, `aria-describedby`, and `href` attribute
in the same template. Four attribute removals.

## C9: architecture.md cites a script this repo does not hold

`architecture.md:210` names `scripts/sync-calculator-ui.mjs`. No `.mjs` file exists under
`scripts/`. The script lives in the consuming Scryglass repo. Rewrite the sentence so the
path resolves, or name the owning repo.

## Frontend: what the sweep proved clean

| Check | Result |
|---|---|
| Top-level JS functions in `static/js/*.js` with no caller | 0, across 5 files and 8,225 lines |
| Top-level JS `const`, `let`, and `var` with no reader | 0 |
| Templates never rendered | 0. `src/app.py` serves all six: `/` renders `calculator.html`, `/advanced` renders `index.html`, and the other four are `beta_landing`, `privacy`, `terms`, and `riot_disclaimer` |
| `static/*.json` assets with no reader | 0. `src/service_auth.py` allowlists four, and `source_receipts.py`, `packet_parsers.py`, and `scoreboard.js` read the rest |
| Checked-in build artefacts | `static/calculator/` holds 452 KB that `ui/build.mjs` generates, and it is the deployable. `Dockerfile:21` copies only `static/`, no node build runs in the image, and `ci/shared_ui.sh` gates it with `node build.mjs --check`. Keep it. The `favicon.svg` copy between `static/calculator/` and `ui/assets/` is `build.mjs` doing its job |
| Duplicate asset bytes | 2 pairs: the intentional favicon copy, and `armor_penetration.png` matching `lethality.png` inside the already-dead C3 directory |

## Ranked by payoff

| Rank | Finding | Payoff | Risk |
|---|---|---|---|
| 1 | C1, `ui/assets/league/` | 2,626 KB across 11 files | None. No reader and no gate |
| 2 | B3, assignments compaction | About 3,300 lines | Low, but a judgement call on record-keeping |
| 3 | B1 and B2, two spent scripts | About 256 lines, 2 scripts, 2 tests | None to low |
| 4 | A1, A2, and A3, the facade cluster | About 67 lines, 1 module, 1 accessor | Import order moves. Gate with both golden compares |
| 5 | C2 and C3, orphan assets | 111 KB across 14 files | None |
| 6 | A4 and A5, skill-order tables | About 61 lines | None. `get_ability_rank` output does not move |
| 7 | C4 through C9, frontend cleanups | About 14 lines and 4 attributes | None. C5 also closes a live theme gap |
| 8 | A6 and A7 | 4 lines, an empty directory, 6 pointer edits | A6 touches a numeric value. Gate with both golden compares |
