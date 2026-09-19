# Slop audit

Audit of `main` at `1a58b1c4` on 2026-09-19. Eleven read-only auditors on Opus, one per dimension, each over the whole of its scope rather than a sample. Each auditor grep-confirmed every "unreferenced" claim, and the highest-payoff claims were re-verified independently before this file was written. Three auditor claims failed re-verification and are marked "Correction" where they appear.

The tree is clean on the classic axes. Measured tree-wide: 3 to-do markers, zero debug prints or `console.log` in shipped code, zero tracked build artefacts, zero conflict markers, clean line endings, zero mutable defaults, zero bare `except`, zero `== True`, and zero duplicated function bodies anywhere in `src/` or `scripts/` over 11,159 AST-normalized functions. The slop is somewhere else: in prose, in copy-pasted tests, in evidence corpora nothing reads, in a typed declaration layer that sits on an untyped engine payload, and in a handful of half-finished migrations.

## Headline

| Area | Removable | Where the weight is |
|---|---|---|
| Tracked data nothing reads | about 17 MB, about 1,500 files | `data/atoms/v2` at 9.3 MB and 166 files with one reader; `data/item-atoms` at 1.4 MB and 325 files, documented as retired; `docs/receipts/oracle-*.json` at 1.6 MB and 141 files with 2 read; 48 `docs/receipts/expected-golden-diff-*.json`, all vacuous; `ui/assets/league` at 2.6 MB with zero readers |
| Tests | about 13,000 lines deletable and about 4,000 relocatable, out of 262,000 | 354 copies of three champion contract tests; 2,731 lines of one inlined fixture in `test_item_damage.py`; about 1,900 lines of substring tests over JS, CSS and markdown; campaign closeout blocks that re-pin the golden |
| Docs | about 8,400 of 12,978 markdown lines | `HANDOVER.md` at 5,987 lines; 17 finished-campaign docs; `CLAUDE.md` carrying 4,845 words of traps with no `TRAPS.md` |
| Champion modules | about 4,100 of 49,000 lines | prose at 24.8% of the tree; one six-positional `derive_self_healing` signature copied 60 times with 55 pylint suppressions; four half-adopted helpers |
| Core `src/` dead code | about 2,100 lines | the `program/` event-compile island at about 1,150; a 432-line test fixture in `item_coverage.py` |
| Wrappers and indirection | about 290 lines, one module, 0.5 s of import | a 16-name package facade with zero importers that eagerly imports `champions` and `damage` |
| Structural, no line count | | 1,616 literal-default reads on engine rows while the typed row readers have 6 users; a 96-field `SurvivalAction` with 66 fields never set; 55 of 59 custom exceptions never caught; 2,233 campaign markers in 495 files |

Total: roughly 30,000 lines of Python and markdown plus about 17 MB of tracked data, with no behaviour change. Every deletion is gated by `pytest` and by both golden compares showing zero diffs.

## 1. Dead code

### 1.1 Core `src/`, excluding champions

Vulture finds nothing at confidence 80 and only Flask routes at 60, so the auditor built an AST census of 3,959 symbols against a reference index that separates code references from prose mentions. 510 of 519 modules are reachable from the runtime roots, so no module is dead. All dead code is symbol-level. About 2,110 lines, of which 1,680 are pure deletion.

| # | Finding | Location | Lines | Proposal |
|---|---|---|---|---|
| D1 | The logical `Program` event and compile island. `roster_program` returns `Program(events=())` by design, so no `PairEvent`, `RoutedEvent`, payload family or rider is ever constructed on the request path. `compile_program` raises on any event that carries an Execute or Wound rider because `_STAGED_RIDERS` is an empty frozenset, so it cannot be wired without finishing the rider axis. | `program/events.py` (479 lines), `program/caches.py` (299), `program/build.py:41-304`, `program/compile.py:2185-2386` | about 1,150 | Cut. Correction: `scripts/receipt_walk_schedule.py:148,642` imports `program.events` and reads `RIDER_KINDS` to build the mechanism table in `docs/receipts/receipt-walk-retirement-schedule.json`. Keep the five rider classes and `RIDER_KINDS`, or move them to a small leaf, and cut the rest. Move `every_declaration`'s union with `GOVERNED_MEMOS`, 8 lines, into `data_registry.py`, which owns that set. The cut retires `tests/test_program_events.py`, `test_program_caches.py`, most of `test_program_compile.py`, `test_program_build.py` and `test_program_amp.py`. |
| D2 | `_STATS_ONLY_CERTIFIED_EFFECT_TEXT` and `stats_only_effect_fingerprint`, a golden fixture that pins the wiki text of every stats-only item, read only by `tests/test_stats_only_items.py` | `item_coverage.py:314`, `:732` | 432 | Move to `tests/fixtures/`. `item_coverage.py` stops being the largest text blob in `src/`. |
| D3 | `Provenance`, `AppliesTo`, `Provenance.skips`: an authoring invariant nothing authors. The live typed path is `LiveAmpRider` in `survival/typed_action.py`, where the emptiness this refuses is impossible by construction | `program/amp.py:68`, `:83` | 62 | Cut. If the double-count invariant matters, put a `__post_init__` on `LiveAmpRider`. |
| D4 | Three context-resolving interpreter siblings plus `compile_rule`. The runtime uses the flat form in every case | `interpreters/sustain.py:175`, `crit_profile.py:229`, `damage_routing.py:270`, `interpreters/__init__.py:370` | 89 | Cut. Correctness tail: `item_coverage._TARGET_MODELED_IMPLS` at `:1789,1794,1795` names the dead `sustain_slot` as the pricing home for Catalyst of Aeons, Doran's Blade and Doran's Ring. Repoint to `declared_sustain`. That repoint is the actual fix. |
| D5 | `FightConfig.for_minion`, a second constructor for a fact `fight.config.sourced_minion_target` owns | `fight/config.py:224` | 40 | Cut, and update the two error messages at `:250` and `:320`. |
| D6 | `precision.ROUNDING_BY_VIEW`, `CutoffPolicy`, a one-member enum, `damage_cutoff`, `ROUNDING` | `program/precision.py:277,311,343,363` | 46 | Cut. |
| D7 | Strict-API siblings of two receipt-form eligibility decisions: `required_delivery_class`, `required_control_class`, `DeliveryProfile.has` | `delivery_classes.py:214,160`, `crowd_control_eligibility.py:156` | 42 | Cut. |
| D8 | `TimedStackState.note_activity`, a duplicate of the freeze that `record_trigger` applies | `timed_stacks.py:380` | 25 | Cut after a sourced check. The modelled Ferocity freeze re-arms on stack gain, not on any damage event. If those differ in game, this is the modelling gap the dead method was meant to close. |
| D9 | `owners_for`, `declared_tags`: migration counters | `item_behavior_catalog.py:5003,6170` | 34 | Cut. |
| D10 | The `ledger_projection` receipt trio `unserved_conditions`, `ledger_demands`, `shield_outcome_demands` | `ledger_projection.py:158,190,195` | 13 | Cut, then inline `_demands`'s `stop_at_first`, which has one value at every remaining call site. |
| D11 | Write-only state: `TimedStackState._last_gain_time`, `StateTimeline._order`, `LeafBlock._prefix`, `ResourceAccount._regen_per_second`, `AllyStatEffect.assumption` | 5 sites | 26 | Cut four. `AllyStatEffect.assumption` is the one wire-not-cut: it holds a real disclosure sentence and the response has a disclosure channel. See aside A3 on `_order`. |
| D12 to D24 | Thirteen test-only symbols: `rearms_within`, `defense_source`, `SumPlan.ids`, `_PER_CALL_FIELDS`, `same_hit_ordering` with its error, `item_behavior.TRIGGER_STREAM` (a second spelling of the stream vocabulary CLAUDE.md forbids), `OutcomeLedger.quantities`, `CastEventRow` with `cast_row`, `_navori_effective_cd`, `FightTrace.refusals_by_source`, `CapabilityView.compilable`, `atomizer.hash_domain_file`, `policy_values`, `LivePredicate.requires_live_pool`, a property that always returns `True` | see the auditor report | about 180 | Cut. |
| D25 | Test-only constants: `SHARED_ROW_FIELDS`, `TOOLTIP_ONLY_CONTROL_KINDS`, `MINION_TEAMS`, `damage_event_row.event_damage_type`, `REQUIRED_FIELDS`, `HEAL_REQUIRED_FIELDS` | 6 sites | 14 | Cut all but `HEALING_RULE_CHAMPIONS`, which architecture.md names as public. |
| D26 | `db.CacheCounter.updated_at`, populated on insert and never written or read again, so it holds creation time under a name that promises otherwise | `src/db.py:222` | 3 | Stamp it where `hits` and `misses` increment, or cut it with a migration. |
| D27 | `rune_parser._percent_ratio` defined twice with identical bodies, both dead. CLAUDE.md cites the pair at 982 and 1544; it sits at 1088 and 1650 | `rune_parser.py:1088`, `:1650` | 20 | Cut both. This is the one real `E0102` the pylint gate is widened around, so `--fail-on` can include it after the cut. |

Clean: `rune_paths/` has zero dead symbols, `survival/` has two findings only, `src/*.py` has Flask routes only, every exception class is raised somewhere, and every `__all__` entry resolves.

### 1.2 Champions, scripts, frontend

The champion tree of 207 modules and the 55 scripts are clean: zero unreferenced top-level names, zero unused nested functions, zero unread OPTIONS keys, zero identity slot overrides, zero repeated ASSUMPTIONS sentences. Every script resolves to CI, CLAUDE.md, a skill, a doc, a test or another script. The dead weight is assets and one facade.

| # | Finding | Location | Size | Proposal |
|---|---|---|---|---|
| D28 | `ui/assets/league/` holds 11 CommunityDragon files with zero readers. `champion-hud.css` and `rune-assets.ts` load the remote `raw.communitydragon.org` URLs, `build.mjs` copies only `favicon.svg`, and nothing reads `source-manifest.json` | `ui/assets/league/` | 2,626 KB, 11 files | Cut the 11. Keep `README.md` for the geometry table and `source-manifest.json` for the hashes. |
| D29 | `src/calculator/__init__.py` re-exports 16 names that zero files import. All 182 `from src.calculator import` statements name a submodule. Measured cost: importing the leaf `quantity` takes 538 ms, and 535 ms of that is the facade's eager `champions` at 360 ms and `damage` at 175 ms | `src/calculator/__init__.py:1-38` | 37 lines, 0.5 s per process | Cut to the docstring plus `publish_rune_compilers()`. Gate with both golden compares, because import order is numeric here. |
| D30 | `champions/common.py`, a 16-line module for `base + ratio * stat`, alive only through D29 | `champions/common.py` | 16 plus 12 test | Cut with its test block. |
| D31 | `is_champion_supported`, whose one reader is the dead facade | `champions/__init__.py:1077` | 4 | Cut. |
| D32 | `_SKILL_ORDERS["Vayne"]` equals `DEFAULT_SKILL_ORDER` byte for byte, and 13 of 17 rows repeat one of three shapes | `champions/skill_orders.py:27-131` | 61 | Cut the Vayne row. Name the three shapes once. |
| D33 | Six modules spell `("P","Q","W","E","R")` for `slot_order` where `REQUIRED_CHAMPION_SLOTS` exists | maokai, rengar, samira, sett, yorick, zyra | 0 net | Point at the constant. Numeric, so gate with the goldens. |
| D34 | A stale `.gitignore` rule for the closed `champions/generated/` lane. It points at `.agents/skills/add-champion`, which does not exist, and the directory is empty on disk | `.gitignore:63-66` | 4 | Cut the rule, the empty directory, and the `.agents/` pointer. |
| D35 | `scripts/testing_flag_codemod.py`, a one-shot codemod with zero targets left. A gate holds the count at zero | `scripts/testing_flag_codemod.py` | 98 plus 14 test | Cut with its one test. |
| D36 | `scripts/install_wiki_refresh.py` writes a macOS launchd plist. Its test is `skipif(os.name != "posix")`, and `data/wiki/wiki-schedule/`, the promised receipt directory, does not exist. The portable path is `patch_update.py wiki-refresh --scheduled` | `scripts/install_wiki_refresh.py` | 118 plus 12 test plus 14 doc | Cut, unless a macOS box runs it. In that case say so in `docs/wiki-refresh.md`. |
| D37 | `scripts/assignments/*.json` records 45 applied module splits in 4,093 lines. About 3,300 lines are mechanical `defs`, `residue` and `external_readers` arrays that no run can replay, and only a path-existence test reads them | `scripts/assignments/` | 3,300 | Compact each to `source`, `decisions` and `string_annotations`. Judgement call: the `decisions` prose is real knowledge. |
| D38 | `static/fonts/` holds a Godya face with no `@font-face` anywhere. The page uses Atkinson. `static/img/stat-icons/` holds 12 PNGs untouched since the initial commit, two of them byte-identical | `static/fonts/`, `static/img/stat-icons/` | 111 KB, 14 files | Cut. |
| D39 | Dead CSS. `.ability-casts` styles a retired stepper in 5 selector lines. `.wiki-popover` names a class the code renamed to `.item-tip`, so the advanced page's tooltip silently misses its Scryglass override | `static/css/style.css:550-578`, `scryglass-theme.css:71` | 6 | Cut the first, rename the second. The rename also closes a live theme gap. |
| D40 | Two unused UI exports, `championByName` and `runeAssetVersion`, the second of which also duplicates the `16.17` in every URL of its own file. Four DOM ids with no selector | `ui/src/scenario-state.ts:154`, `rune-assets.ts:7`, `templates/index.html:322,451,459,563` | 8 | Cut. |
| D41 | `architecture.md:210` cites `scripts/sync-calculator-ui.mjs`, which this repo does not hold. It is the only broken path in the repo's most-trusted doc | `architecture.md:210` | 1 | Name the owning repo. |

## 2. Low-value tests

624 files, 262,000 lines, about 11,000 tests. Four auditors, one per alphabetic slice. About 13,000 lines are removable and about 4,000 more are in the wrong home. Ranked by payoff.

### 2.1 The three copy-pasted champion contract tests

Verified tree-wide: `test_a_timed_fimbulwinter_fight_is_fully_certified` sits in 131 files, `test_declared_kinds_are_the_ones_the_cached_kit_gives` in 118, and `test_every_ability_event_carries_the_review` in 105. Add `assert X.parse_abilities.cc_kinds == X.MODULE_CC` in 76 files, which holds by construction because `packet_module.compile` stamps it, and one six-line docstring copied word for word into 69 files. Each copy differs only in the champion string, and each Fimbulwinter copy runs two full fights, about 262 fights per suite run.

`tests/test_module_cc_census.py` exists for this shape and parametrizes four sibling checks over `registered_champion_names()`. Its docstring states the principle: the census is the test, because the failures it guards are counts.

Proposal: one codemod. Three parametrized tests in `test_module_cc_census.py`, then delete the 354 bodies and the 69 docstrings. A new champion is then covered the moment it registers. Today it is covered only if its author pastes the block. Keep the per-champion `MODULE_CC == {...}` literal and the `cc_review.slot_text` and `control_words` derivation, which are per champion. About 1,250 lines.

### 2.2 `tests/test_item_damage.py` inlines one dict 44 times

The file is 6,970 lines, the largest in the tree. `conftest.py` ships the `attacker_stats` fixture, and the file installs it through `_FightHarness` at line 267, but the migration stopped halfway. 44 test bodies still inline the same 25-key dict and differ in two or three values, 2,731 lines measured. Two parametrize families sit inside: the four `test_ahri_level_18_fiendhunter_*_crits` at 60 lines each, and the three Rageblade proc tests. Six sites patch `random.random` with `unittest.mock` instead of the house `deterministic=True`.

Proposal: codemod to the fixture, parametrize the two families, swap the six mocks. About 2,400 lines.

### 2.3 Substring tests over JS, CSS and markdown

These tests read `static/js/app.js`, `style.css` or a `docs/*.md` as text and assert substrings. The JavaScript never runs. A rename or a formatter pass turns them red, and a broken widget stays green.

| File | Substring tests | Lines | Worst example |
|---|---|---|---|
| `test_app.py:1027-2302` | 26 pure plus 34 asserts in 8 mixed tests | about 390 | line 1052 pins a 140-character JS expression verbatim |
| `test_frontend_qa_147_157.py` | 37 of 65 | 264 | `re.search(r"--panel-alpha:\s*\.67", tokens)` |
| `test_redesign_frontend.py` | 31 of 49 | 310 | `assert "DATA.items = catalog.map((entry) => ({" in body` |
| `test_p5_ux.py`, `test_p1a_onboarding.py` | most | about 350 | `p1a:190` asserts a JS comment string; absence loops freeze the Quick-mode removal |
| `test_f0_frontend.py` | 16 of 38 | 162 | `test_dead_renderers_are_removed` runs 18 `not in source` checks |
| `test_frontend_crit_contract.py` | whole file | 124 | 54 parametrize rows assert that deleted identifiers stay deleted. The literal rows are bare digit strings such as `"3089"` and `"1.08"` that match any number containing them |
| `test_program_views.py:645-755` | 7 | 110 | asserts a CSS selector string is present, inside the file that owns the Python view layer |
| `test_p0d_runbook.py`, `test_p0a_deploy.py:465`, `test_p0b_ops.py:423,437`, `test_p1b_metrics.py:681` | all | about 160 | markdown word bingo: `docs/deploy-runbook.md` contains "Neon", "Upstash" and "Rollback" |
| `test_issue_158.py` | 8 of 13 | 90 | asserts `def _name(` strings are absent from `src/app.py`, including the Flask idiom `response.get_json()` |
| `test_frontend_level_controls_contract.py`, `test_f1_bis_metrics.py` | 6 | 107 | |

Keep: `test_stylesheet_braces_balance`, which caught a real bug in an unclosed `@media` block; the `run_timeline_renderer` node driver at `qa_147_157.py:575-710` and its 10 tests, which execute the shipped renderer; every `soup.select_one` DOM test; `test_frontend_crit_backend_200.py`, which drives the API and makes `crit_contract` redundant; and exactly one `node --check`, which exists twice today because `p1a:317` and `p5_ux:437` are byte-identical.

Proposal: delete the substring tests. If "no engine formula in the browser" deserves a standing gate, it is one lint in `scripts/` that checks `0.7025` and `crit / 100` are absent from `app.js`, not 600 lines of pytest. Real frontend behaviour belongs in the browser test that `test_scoreboard_vision.py` already runs. About 1,900 lines.

### 2.4 Campaign closeout blocks that re-pin the golden

| File | Block | Lines | Why it brings nothing |
|---|---|---|---|
| `test_jayce_form_transition.py` | `TestP4JParseParity`, `TestP4JScoreParity`, `TestP4JUnchangedBoundaries`, `TestP4JRegressionSurface` | 222 | The Unchanged halves re-pin per-slot damage for one champion that `golden_baseline.json` pins for all 173. One docstring reads "Mirrors test_participant_timeline.py ~3512". |
| `test_olaf_r_cleanse.py`, `test_milio_r_cleanse.py` | `TestModeParity`, `TestUnchangedBoundaries`, four `_today` pins, a 25-line pytest-command comment, 150- and 130-line campaign docstrings | 346 plus 280 prose | The `_today` tests freeze a behaviour the docstring calls a completion gap, so the next honest fix must delete a green test to land. |
| `test_ksante_w_resistance.py`, `test_mundo_e_reset.py`, `test_muramana_packet.py` | `TestUnchangedBoundaries`, `TestScoreReceiptParity` | 311 | architecture.md gives score-only versus full-walk parity to `test_participant_timeline.py` and `test_optimizer.py`. |
| `test_maw_compiled_parity.py`, `test_knights_vow_compiled_parity.py`, `test_jaksho_compiled_parity.py`, `test_jayce_w_mana_restore.py` | 13 `test_regression_surface_*` functions | 293 | Same. `knights_vow:1486,1500` are byte-identical to `:737,849` in the same file. |
| `test_verdant_barrier_compiled_parity.py:1209-1412` | section 9, headed "mirrors the originals" | 181 | Every docstring opens "Mirrors `test_<other file>.py`". `test_spell_shield_eligibility.py` parametrizes all three Annul items already. |
| `test_gluttonous_greaves.py`, `test_gunmetal_greaves_riot_branch.py` and 9 siblings tree-wide | `test_compiled_walk_equals_receipt_walk_<item>`, `test_score_only_fight_parity_<item>`, `test_identical_fights_produce_identical_receipts` | 240 in slice | `test_survival_kernel.py` owns the parity invariant in 10 parametrized rows. |
| `test_coupled_golden_allowlist.py` | whole file | 235 | Measured: 0 standing coupled diffs and 0 pair diffs, so every assertion is `() == ()`. Its 2,992-path allowlist is checked as a subset, never as equality, so it is strictly weaker than the compare gate it wraps. It costs about 6 s per run. |
| `test_syndra.py::_allowlisted_moves` and six pinned rows | | 90 | Unions 48 `expected-golden-diff-*.json` into 3,063 admitted leaf paths with 75 value-checked. It re-implements `golden_snapshot.py compare`. Its own docstring names the end state, "both clauses hold trivially", which is now. |
| `test_declared_zero_dispositions.py` | 2 tests | 49 | Pins a per-reason `Counter` for one scenario the coupled golden holds leaf by leaf. Its comment records one re-measurement already forced by an unrelated change. |

Proposal: delete. `python scripts/golden_snapshot.py compare` on both baselines is the gate, and it is total. About 1,900 lines.

### 2.5 Tests that freeze a deletion

A test whose green state is "the thing we removed is still absent" breaks the next honest refactor or rename and guards nothing.

| File | Test | Shape |
|---|---|---|
| `test_trigger_stream.py:1086-1315` | `test_a2_*`, `test_a4_*`, `test_no_retired_symbol_is_named_anywhere_in_src_not_even_in_prose`, three seams | `RETIRED_SYMBOL_HOMES` holds 15 symbols with every value `[]`. The prose scan forbids a name from appearing in any comment. Six full-tree AST walks per run. |
| `test_coverage_claims.py:1364-1471` | `test_the_eight_retired_registries_*` and two tests of the scanning helper | `assert len(RETIRED_REGISTRIES) == 8`, then tests of a test. |
| `test_deletion_frontier.py` | whole file | An AST ladder detector pinned to `{"transitions.py:run_survival_walk"}`, and a `"UTILITY_KINDS = "` grep over `src/`. |
| `test_issue_160_boundaries.py` | whole file | `assert not Path("src/calculator/healing_legacy.py").exists()` four times, plus `len(HEALING_RULE_CHAMPIONS) == 62`. |
| `test_issue_159.py:53` | `test_the_retired_duplicate_walks_are_gone` | rglobs `src/` for 4 deleted identifiers, including the generic `expire_timed_shields`. |
| `test_transition_rank.py:505` | `test_the_float_projection_is_deleted_from_the_tree` | A full-tree walk for `legacy_phase`. |
| `test_immobilize_predicate.py:222` | `test_the_widening_is_ten_kinds_and_the_retired_five_are_a_subset` | `RETIRED_WALK_LITERAL` is defined only in the test. The `== 15` duplicates `test_cc_kind_vocabulary.py`. |
| `test_rengar_w_cleanse.py:1115-1386` | four absence pins, plus nine tests that drive the shared cleanse kernel, some with Gangplank | `test_cleanse_eligibility.py` owns every one. 391 lines. |
| `test_milio_fired_up_blocker.py` | 180 of 234 lines | Asserts phrases are absent from three JSON dumps, and that two English sentences appear in ASSUMPTIONS. |
| `test_tag_dispatch_parity.py:140-307` | six `not hasattr(_ladder(owner), "<retired>")` tails | Strip the tails, keep the catalog assertions. |
| `test_champion_module_contract.py:272,295`, `test_custom_cast_order.py:113,145,359`, `test_static_data.py:77,78,92`, `test_coverage_evidence.py:666`, `test_cp20_items.py:142`, `test_samira.py:59`, `test_rengar_ferocity_ledger.py:469`, `test_program_identity.py:155`, `test_pair_preview.py:292,326`, `test_e9_corpus.py:385` | one to three lines each | `not hasattr`, `not in source`, and one test that asserts its own file does not import `subprocess`. |

About 700 lines.

### 2.6 Tests whose green state is "the bug is still there"

| File | What green means |
|---|---|
| `test_champion_inputs.py:234-278 TestTheEscalatedDefectIsStillTracked` | Akshan's E per-shot damage does not scale with attack speed. See aside A1. |
| `test_escalated_defects_cached_data.py`, 175 lines | Imperial Mandate's cached `simpleDescription` is wrong, and one phrase atomizes to three atoms. Its docstring says "Red means the defect closed". It also writes a scratch file into tracked `docs/receipts/` mid-test, which races xdist workers. |

Proposal: fix Akshan. Move the two cache defects to `TRAPS.md` and to the patch-day audit output. Delete both tests.

### 2.7 Process-state violations of a documented trap

CLAUDE.md says never to `.clear()` a process-wide cache in a test. The suite does it at more than 40 sites:

`test_f3_rotation_all.py` clears `_DERIVED_RULE_CACHE`, the memo for about 170 champions, 26 times. `test_rotation_semantics.py:38` clears it in an autouse fixture after every test. Also `test_rotation_resolver.py:232,241`, `test_briar_e.py:303,305` in an autouse fixture, `test_data_version_memos.py:532`, `test_behavior_declaration_acceptance.py:316-328`, `test_behavior_frontier.py:1231,1241`, `test_interp_threshold_defense.py:288,291`, `test_program_views.py:1034,1041` with `cache_clear` on a production `lru_cache`, `test_live_amp.py:442,447`, and `tests/support_effect_fixtures.py:53,58`. `test_ledger_projection.py:131` and `test_program_walk.py:276` rebind module attributes by hand in try/finally.

Proposal: `monkeypatch.setattr(module, "_CACHE", {})` in every case. One codemod. No lines saved, real cost removed.

### 2.8 Tautologies and determinism theatre

- Enum echoes: `test_ability_spec.py:73-179` has four tests that assert an enum's member list equals its member list. Also `test_engine.py:215` with `PHASE_ORDER == ("buff", ...)`, `test_rotation_resolver.py:333`, `test_transition_rank.py:783`, and `test_capabilities.py:98` with `test_aura_arming.py:194`, both `CAPABILITY_SCHEMA_VERSION == 9` under 12 lines of version-history docstring.
- `assert run() == run()`: `test_eclipse_timing_packet.py:979,992`, `test_f3_rotation_all.py:547` on a memoized function so it cannot fail, `test_gluttonous_greaves.py:844`, `test_ionian_boots_summoner_haste.py:464,486`. None sits on a crit build, which is the one case where determinism is a real claim.
- `assert reason.strip()` over a hand-written literal dict at 12 sites across `test_architecture.py`, `test_behavior_frontier.py`, `test_behavior_catalog.py:200`, `test_cast_dependency_audit.py`, `test_champion_inputs.py:192`, `test_data_version_memos.py:240`.
- `test_ionian_boots_summoner_haste.py` spends 689 lines on +10 ability haste, including `assert pytest.approx(0.0909090909) == 1.0 - 100.0 / 110.0` with no repo code involved, and four tests that assert the item does nothing, four ways. Cut to about 240.
- `test_known_good.py` has five test functions per case, each re-running one `calculate_total_stats` call for one key. 15 calls where 3 would do.
- `test_coverage_claims.py:2430` counts the `test_M1..M9` functions in its own module.
- `test_patch_update.py:370` reads `Path(__file__)` and asserts two strings are absent from itself.
- `test_yuumi.py:273` re-implements the production fold inside the test, asserts a pure function of the result, then checks an `inspect.getsource` substring.
- `test_behavior_frontier.py:322-1250`: 17 tests over 383 lines gate `COUNTER_4_DEFERRALS`, probed this session as empty. The reds fabricate a row through `_FABRICATED_DEFERRAL` so they have a subject. Delete with the stage and deferral machinery in `scripts/behavior_frontier.py` and with `docs/receipts/campaign-stages.json` and `campaign-slice-tags.json`.
- `test_coverage_reason_source_assertion.py`, 374 lines, binds one published sentence to its predicate through the AST. Replace with one parametrized behavioural test on the payload.

About 1,300 lines.

### 2.9 Copy-paste that should be parametrize rows

18 byte-identical interpreter refusal clones across `test_interp_*.py`, where one parametrize off `interpreters.INTERPRETERS` also closes the "new interpreter gets no test" hole. `test_event_order_certification.py:242-365` runs 4 identical `/api/optimize` searches. `test_rune_effects.py` writes one fail-closed path four times. `test_mikael_packet.py:429,452` and `test_muramana_shock_lockout.py:238,260` have identical bodies over different rows. `test_vayne.py` has groups of 5, 4 and 2, and `test_state_lifecycle.py`, `test_zeri_p_execute_range.py`, `test_vladimir_e_charge_time.py` and `test_redemption_packet.py` have groups of 3, plus four `test_rune_paths_*` groups. `_resolve` is duplicated between `test_e2_dot_2.py:96` and `test_e4_summon_3.py:96`, and between the two Aurelion Sol stardust files. Byte-identical pairs: `test_amumu.py:50/87`, `test_orianna.py:108/128`, `test_jaksho_compiled_parity.py:868/883`, and the two Ashe files. About 1,100 lines.

### 2.10 Right content, wrong home

- `tests/test_literal_defaults.py`: 2,330 of 2,442 lines are a frozen data matrix, `ROW_READS` and its siblings. The limit that only tightens is real value. The home is wrong. `.sightline-baseline` is the pattern: a data file beside its tool, merged by union. `ER5_TAIL` with 89 entries is derivable as every `src/calculator` module minus those `ROOTS` covers, verified 89 of 89, and should be a pinned count rather than a hand list.
- `test_p1_review_{1,2,3}.py`, 1,742 lines, hold about 30 champions' tests under campaign batch names. Nasus' Soul Eater tests live at `test_p1_review_1.py:372`, not in `test_nasus.py`. Move each champion into its own file.
- 69 test files are named after a campaign rather than a subject, such as `test_e2_dot_2.py`, `test_batch46_binary_roots.py`, `test_p0a_deploy.py`, `test_wave2_stat_buffs.py` and `test_issue_137.py`. Rename by subject.
- About 600 lines of tree scanning that belong in `scripts/` beside `literal_defaults.py`: the two big scans in `test_architecture.py`, the scanner in `test_ci_evidence_parity.py`, the formula scans in `test_import_namespace.py` that CLAUDE.md names as a phantom-failure source under concurrent edits, `test_item_support_effects.py::_damage_modifier_call_sites`, `test_event_slots.py::test_src_constructs_no_second_registry`, `test_issue_159.py::test_no_other_module_consumes_or_grants_a_shield_pool`, and `test_transition_rank.py:886`.

### 2.11 Doc rot inside tests

12 files in the e-i slice and 3 in j-p describe themselves as carrying `pytest.mark.xfail` rows. Zero live xfail markers exist in either slice, and `tests/coverage_resolver.py:610` treats an xfail as a failed evidence claim. Dead `_AWAIT` and `XFAIL` bindings sit at `test_ashe_q_active_window.py:108` and `test_olaf_r_cleanse.py:218`. Module docstrings run to 193, 183, 174, 169 and 154 lines in `test_vladimir_e_charge_time`, `test_zeri_p_execute_range`, `test_cleanse_eligibility`, `test_olaf_r_cleanse` and `test_verdant_barrier_compiled_parity`. `pyproject.toml` exempts test docstrings from the length rule on purpose, and that exemption is where the campaign narrative collected: 945 of the 1,421 docstring campaign markers are in `tests/`.

### 2.12 Skips that hide suites

`test_gnar_mega_gamefile.py`, 1,025 lines and 41 tests, and 21 other sites call `pytest.skip` when a tracked `data/bin/characters/*.bin.json` is unreadable. Four sites skip when `node` is absent, so on a CI runner without node the node tests never run. `conftest.py:34` already argues deselection with a report over skip, the D-22 ruling. Apply that ruling.

Clean: all 20 helper modules under `tests/` are used and none duplicates `src/`. `conftest.py`'s `_process_state_is_given_back` and the deselect hook are the best test infrastructure in the tree. `test_binary_roots.py`, `test_survival_kernel.py`, `test_module_cc_census.py`, `test_process_state_guard.py`, `test_program_structure.py::TestViewPurity`, the M1 to M9 mutation suite, and the `test_e1_*` to `test_e9_*` files are keepers. Despite their names, every test in the `test_e*` files drives a real fight.

## 3. Wrappers, stubs, indirection

Measured over 346 modules and 5,099 definitions. 443 of 2,252 top-level functions hold a single statement, and most bind a constant into a shared resolver with tens to hundreds of call sites: `champion_stat` 68, `bool_option` 106, `int_option` 163. The leaf style is mostly honest. Decay is concentrated:

| # | Finding | Location | Proposal |
|---|---|---|---|
| W1 | The dead facade, D29, with its 0.5 s import cost | `src/calculator/__init__.py` | Cut. |
| W2 | Twelve `*_rules(owners)` clones in `interpreters/`. Eight are identical apart from one `RuleFamily` member, four add one `isinstance`, and none is imported outside its own file | `active_cast.py:92`, `cast_proc.py:249`, `charged_strike.py:300`, `crit_profile.py:179`, `damage_routing.py:327`, `on_hit_strike.py:219`, `periodic.py:123`, `spellblade.py:75`, `resistance_shred.py:216`, `stat_derivation.py:142`, `sustain.py:163`, `delta_amp.py:336` | One `rules_of(owners, family, payload_type=None)`. 96 lines become 24, and 12 names become 1. |
| W3 | Four `_compile_*` wrappers, byte-identical apart from the docstring, all forwarding to `_compile_defense`. Their only use is four adjacent `_FAMILY_COMPILERS` rows | `item_behavior_catalog.py:5215-5248` | Map the four `RuleFamily` keys to `_compile_defense` and move the docstrings onto the enum members. If D-52 must hold literally, say in its comment that four keys share one compiler. |
| W4 | Nine closed vocabularies written twice, as a `Literal` and as a parallel `frozenset`, in the two modules meant to be the one home | `reference_vocabulary.py:8-59` holds 4, `coverage_evidence.py` holds 5 | `frozenset(get_args(TheLiteral))`. 43 member strings stop being duplicated. |
| W5 | Five byte-identical `def field(name, value) -> KernelField` closures | `interpreters/amp_magnitude.py:198`, `damage_routing.py:96,141`, `resistance_shred.py:116`, `secondary_target.py:66` | `partial(KernelField, lane=lane, rule_id=rule.mechanic_id)`, the move CLAUDE.md already records for this shape. |
| W6 | Eleven single-call renames: `_navori_effective_cd`, `input_option_stat_bonuses` over `_input_option_stat_bonuses`, `_interaction_event_key` over `stable_event_key`, `role_scoped_bis_candidates`, `item_sell_value`, `_rune_plating`, `_rune_regeneration`, `keystone_compilers`, `shard_compilers`, `get_skill_order` (a public name with no external caller), `_json_name` | see the auditor report | Inline. About 55 lines. |
| W7 | `public_patch` and `client_patch` have no production caller. `data_registry.py:387` reads the fields off `canonical_patch()` directly, which is the better API | `patch_identity.py:42-47` | Cut. |
| W8 | 37 imports renamed to a leading underscore, 18 in `participant_timeline.py` and 12 in `app.py`. The rename adds no meaning, hides the real name from grep, and made four live functions look dead on the audit's first pass | 6 files | Import each name as spelled. |
| W9 | `survival/__init__.py` re-exports 38 names for one production importer, while its sibling `program/__init__.py` states that it "deliberately re-exports nothing" | `survival/__init__.py:46-124` | Pick one policy and record it in architecture.md. |
| W10 | Three plain aliases that are a second name for one fact: `AMP_COMPILABILITY = COMPILED_KERNEL_CAN_AMP`, `TOP_LEVEL_CAP = TOP_QUEST_LEVEL_CAP`, `ArmKey = tuple` | `item_behavior_catalog.py:1314`, `role_quests.py:54`, `program/amp.py:135` | Use one name. Give `ArmKey` members or cut it. |
| W11 | `FormulaPayload`, a Protocol with no external reference, used as a local type alias | `interpreters/damage_formula.py:233` | Inline. |
| W12 | `input_option_stat_bonuses` returns a bare 4-tuple, read positionally at `stats.py:114` and as `input_bonus_ap, _, _, _` at `item_effects.py:6115`. The triple discard is the shape that silently swaps two floats on a future edit | `item_effects.py:1026` | A 4-field record, which is the tree's own style everywhere else. |
| W13 | Three of the five view front doors, `score`, `survival` and `tdd`, have no production caller. Production calls the `*_leaves` functions directly. Only `test_program_structure.py:275 FRONT_DOORS` pins them | `program/views/` | Keep, and know that three of five exist for the contract test. |

Judged keep, with the reasons recorded so nobody re-audits them: all 22 module-level `partial` aliases, each of which binds a real constant with 5 to 36 uses; all 80 `MappingProxyType` freezes, which are declaration tables and rune snapshots that CLAUDE.md names as load-bearing; the five single-member enums, each with a paragraph defending the choice; the 59 functions with 8 or more parameters, where every member of the tail states a reason and `compiled_damage_action`'s 29 is a documented hot-path bypass; the 23 modules under 40 lines, 13 of which are package `__init__` files and the rest one-idea homes named in architecture.md; and `participant_timeline.py:5037 compose`, a closure over values the loop rebinds, so a `partial` before the loop would freeze stale ones. Put that reason in its docstring.

## 4. Code patterns in core `src/`

Scope: 312 files, 121,427 lines. The beginner tells are absent. Measured zero: `== True`, `.keys()` membership, mutable defaults, bare except, docstrings longer than their body, `Generic[]`. Two `len(x)==0`, one `TYPE_CHECKING`. The cost is one contradiction. The declaration layer is over-typed, with 415 frozen records, 69 enums and 59 exception classes, while the engine payload is `dict[str, Any]`, re-defaulted and re-shape-checked at every hop.

| # | Pattern | Count | Proposal |
|---|---|---|---|
| P1 | Untyped engine rows: `.get(key, literal)` on a fight, event or breakdown dict. 51 modules spell `"total_damage"` by string. `participant_timeline.py` has 339 sites, `program/compile.py` 100, `survival/transitions.py` 74. The typed row readers `damage_event_row.py`, `cast_event_row.py` and `heal_event_row.py` exist and have 6 users against about 146 modules that hand-default. `tests/test_literal_defaults.py` at 2,442 lines exists to freeze 632 of them, and its own comment names the fix: "one row dataclass retires the whole list at once". The repo has been bitten already, when 172 golden raw leaves were literal zeros. | 1,616 sites in scope, 1,947 tree-wide | Finish the row readers. Mechanical, and the highest value in the tree. Example at `participant_timeline.py:1063`: three defences on one field, a literal default, an `or` default and a coercion, on a row whose producer stamps all three keys. |
| P2 | `SurvivalAction` is one 96-field NamedTuple for every action kind. Probed live: a median of 19 fields set and 66 never set. The width forced a 29-parameter constructor, 29 `_I_*` index constants, a default-row copy shim, and a 4,367-line dispatch in `survival/transitions.py`. The comment that justifies it, "1.5 us per construction", has no `benchmarks.md` row. | 96 fields | Split per `ActionKind` group: damage, heal, shield, buff, utility. Land a bench row first so the claim is measured. Do this last. It is the riskiest change here. |
| P3 | Long functions. `derive_item_support_effects` is 1,256 lines, 817 of them 16 independent `if <producer> is not None:` blocks with `everlasting` alone at 254, plus one `"Umbral Glaive" in names` branch that never got a declaration. CLAUDE.md already says no honest move set reaches nine imports without splitting it. Runners-up: `_compose_pass` at 864 lines with 16 parameters and 3 booleans, `_compute_ability_rotation` 784, `_layer_on_hit_effects` 686, `item_state_receipts` 682, and `add_engine_result` at 616 with 15 parameters, a 48-line docstring, and a `view: X \| None` read as `staging = view is None`, a mode flag dressed as an Optional. | 151 over 80 lines | A dispatch table keyed by `AllyProducer`, the shape `_FAMILY_COMPILERS` uses one file over. Split through `scripts/extract_modules.py` assignment files. |
| P4 | An exception hierarchy nobody catches. 59 custom classes, and 55 are never named in an `except` in `src/`. 16 are one-per-interpreter `...InterpretationError(ValueError)` that differ only in name. `ActiveCastInterpretationError` and `SpellbladeInterpretationError` are raised zero times. `ProjectionRegistryError` is raised 6 times and referenced by nothing, tests included. | 59 classes | Keep the 6 that are caught: `ApplicationError`, `CacheUnavailable`, `PatchIdentityError`, `StarvedSignal`, `UncompilableActionError`, `ValueRefError`. One `InterpretationError` replaces the 16. Tests move from a class to `ValueError` plus a message match. |
| P5 | Belt-and-braces re-validation. `validate_rule` proves `PAYLOAD_FAMILY[type(payload)] is rule.family` at declaration time. `typed_payload` re-checks it with `isinstance` on every interpreter call, on the hot path, through 12 sites and 16 exception classes. `item_behavior._validate_payload` at line 2833 is a 22-arm sequential `isinstance` ladder beside `PAYLOAD_FAMILY`, a dict keyed by exactly those types. | | Delete the isinstance. The registry key is the proof. Turn the ladder into `dict[type, Callable]` so a new payload type fails closed by omission. |
| P6 | History narrated in runtime source: 61 `Phase N` and 65 `campaign` references across about 60 files, with `trigger_stream.py` alone at 18. `phase` is also a live domain word in `survival/phases.py`, so a reader cannot grep one without the other. | 126 sites | Delete. Mechanical. |
| P7 | Record discipline inverted. 415 records and 69 enums, yet 49 functions return an anonymous 3- to 9-member tuple: `_grey_health_receipts`, `_simulate_ordered_damage`, `_evaluate_cast_parts`, `_lethal_tempo_attack_schedule`. `survival/pricing.py`, at 52% prose, holds `AuthoredDeclaration` with `swing: tuple` and `routing: tuple` "for the wire", packed and unpacked per packet on the hot path, beside `DeclaredPacket` carrying the same fields typed. A NamedTuple is already a tuple, so the round trip cancels. `program/route.py` declares 10 routing policies as frozen dataclasses, 6 with no fields. | | Records where the tuple is. Enum members where the fieldless record is. Type `swing` and `routing`, and delete the pack, the unpack and the 40 lines of docstring explaining them. |
| P8 | String dispatch beside a real enum. `DamageClass` is used 28 times and the bare literal `"physical"` 94 times in about 40 modules. `public_response.aggregate_public_results` at line 400 is an 8-arm `elif policy ==` ladder at nesting depth 10 with per-key special cases inside two arms. | | `_PUBLIC_FIELD_POLICIES: dict[str, Callable]`. Depth 10 becomes 2. |
| P9 | `cast_edge_inference.detect_setup_consume_edges` is 462 lines at nesting depth 11. CLAUDE.md baselines it under sightline #27 as "one function over one champion's rows through six shared closures", which describes the problem rather than excuses it. | 32 functions deeper than 4 | Extract the inner loops. |
| P10 | `binary_roots.py` has 36 raises in 350 lines, a defensive `isinstance` on every JSON hop, 29 in total, and two finite checks that cannot fire because `float(f"{x:.6g}")` of a finite float is finite, marked `# pragma: no cover - defensive` at 97 and 332. It reads like hand-written Java. | | One 8-line `dig(obj, *keys, want=type)` helper. About 15 raise sites collapse into it. |
| P11 | 94 `pylint: disable` in scope. About 60 are size suppressions that sit on the functions named in P2, P3 and P8, and they retire themselves when those land. Tree-wide there are 163 arity and locals disables while `pyproject.toml` already cedes arity to sightline #23 and #55 under "one owner per fact". | 243 tree-wide | Pick one owner for arity. |
| P12 | 35 manual loops that are a comprehension or a `sum`, in `survival/accumulate.py:33-37`, `mana_walk.py` and `participant_timeline.py`. | 35 | One codemod pass. |
| P13 | 53 `type: ignore[arg-type]` in six `test_interp_*` files with one cause: `ITEM_EFFECTS: dict[str, dict[str, Any]]` at `item_effects.py:4053`, where rule 5 promises typed accessors. | 53 markers | One typed accessor. |

Indirection budget, probed on a real request for Ahri at level 11 with 3 items over 10 s: 211 modules entered, 21,374 intra-`src` calls, a call stack only 5 module hops deep with no pass-through hop. Three publication leaves take 52% of the calls, `program/views/leaf.py` 8,199, `quantity.py` 1,974 and `precision.py` 898, because every published number becomes a `Quantity`, a `LeafOut` and a dispositions entry. That is not dead machinery: `app.js` reads `combat.dispositions` in 12 places. If latency matters, the win is the per-leaf allocation, not the feature.

## 5. Champion module drift

174 champion modules, 49,001 lines. The contract itself is healthy: `SOURCES` has one spelling in 97 of 97 modules, `MODULE_COVERAGE` goes through `coverage()` in 74 of 74, zero options go unread, there are 3 `sightline-ok` and 0 `noqa` in 58k lines, and only 13 cross-file AST clone groups exist. Four real problems, about 4,100 lines.

| # | Finding | Count | Proposal |
|---|---|---|---|
| C1 | `derive_self_healing` repeats one six-positional signature in 60 modules, leaves 113 of 360 parameters unread, and carries 55 `too-many-arguments` disables, verified 55 of 60. One call site exists, `healing_contract.py:38`. Five of the tree's fifteen longest champion functions are this one. The receipts are also sorted twice, at `healing_contract.py:78` and `healing.py:98`, so one sort is dead. | 60 modules, 2,490 lines | A frozen `SelfHealCtx` with the six fields. 60 eight-line signatures become one-liners and 55 pylint comments go. Codemod: rewrite the args and prefix six names in the body. About 420 lines. |
| C2 | Prose is 24.8% of the tree, 12,151 lines. 69 module docstrings exceed 30 lines: `naafiri.py` 125, `rumble.py` 100, `sylas.py` 99. They double as changelogs, with 101 campaign-id lines such as "E2 DoT fix:" and 45 history-word lines, and as trap registers. Naafiri's 60 lines on the game-file W and R slot swap belong in `TRAPS.md`. 84 modules carry a `CP10.x` review stamp on line 1, spanning nine values from CP10.3 to CP10.11, a fact `SOURCES` owns through the reviewed revision. | 3,062 docstring lines | Cap at 20 lines. Traps go to `TRAPS.md`, patch labels to `SOURCES`, campaign ids out. About 1,680 lines. Per file, not a codemod. |
| C3 | `ASSUMPTIONS` strings average 252 characters: 194,041 characters over 769 strings, and `sivir.py`'s block is 93 lines. The API publishes these. | 3,606 lines | A 120-character cap in `scripts/prose_lint.py`. About 900 lines. |
| C4 | Half-adopted helpers, each a stalled migration. `CachedSentence` is used in 12 of 37 modules, and 7 of the 25 hold-outs degrade silently, see A2. `no_damage_slot` is used in 13 of 30, and 17 modules keep a trivial `no_damage(...)` wrapper over 193 lines. `at_level` is used in 11 of 17, and `jayce.py:147`, `miss_fortune.py:72`, `sett.py:297`, `xayah.py:118`, `graves.py:22` and `akshan.py:169` re-implement a 5-line helper. `damage_entry` competes with 82 hand-built dict literals, 27 of them core-expressible. The three typed event-row readers have 0 champion consumers against 69 `event.get("damage", 0.0)` sites in 41 modules that `behavior_frontier` holds at a fixed count. | | Finish each migration, the 7 silent readers first. Give `no_damage_slot` `name=` and `phase=`, and `damage_entry` `parts=` and `detail=`, so the hold-outs collapse. |
| C5 | Guard idioms typed out 146 times. `x = ctx.ability(...)` followed by `if x is None: return None` appears 110 times in 95 files, 71 of them on the parser's own slot. The `ctx.ranked` form appears 36 times. `@ranked_slot` proves the shape absorbs, with 215 decorations in 124 files. There is no `@ability_slot`. | 146 sites | Add `@ability_slot(slot=None, index=0)`. About 160 lines. Codemod. Numeric: a decorator that changes when a slot parser binds moves the ledger's insertion order, so gate each step with the goldens. |
| C6 | Ten single-use rule classes over 474 lines, each instantiated once at module level with one `public_receipt()` reader. Two have no state at all, and `zeri._LivingBatteryExecuteRule` returns a constant dict literal. `public_receipt()` is a real house convention elsewhere, on frozen dataclasses with several readers. Here it is ceremony. | `aurelion_sol_stardust.py:42`, `gangplank.py:106`, `ksante.py:108`, `vladimir.py:74,116`, `heimerdinger.py:90,141`, `zeri.py:42`, `bard.py:91`, `senna.py:65` | A module-level frozen mapping for the stateless four. A NamedTuple plus one shared `state_receipt(name, rule)` for the rest. About 250 lines. |
| C7 | Two homes for one fact. `_ROTATION_CLASSIFICATIONS` at `champions/__init__.py:579` is 385 lines and 253 rows, and an OPTIONS row already accepts an inline `rotation=`, which 37 options in 31 modules use. The table key is not unique: 29 option keys are shared across modules over 86 declarations, with a `"slot": {champion: ...}` escape hatch. Four rows match no declared option: `overheat_autos`, `p_backstab`, `p_notes_fired`, `r_variant`. | 385 lines | Codemod every row onto its declaring OPTIONS entry, then delete the table and the fallback. The `add-champion` step "classify every option in the table" becomes "declare it on the option". |
| C8 | Nine module constants restate a cached `castTime` exactly, where `slot_extract.extract_cast_time` reads it: `galio.py:23,31`, `karthus.py:31,32,43`, `taliyah.py:49,55`, `vi.py:68`, `ambessa.py:274`. Six more deliberately differ as composites, and none says so beside the number. 122 of 326 module-level numeric literals carry no provenance note. | 9 proven | Read through the extractor. Note the composites. Lint the rest. |
| C9 | `MODULE_CC` spelling drift: 10 modules write an all-`"none"` dict literal and one writes `dict.fromkeys(SLOTS, "none")`. | 11 | One spelling. |
| C10 | Options read across modules by string convention with no type. `projectile_defense.py:128` reads `f"{key}_active_from"`, `interaction_atoms.py:97-135` hard-codes `"w_blocked_skillshots"`, and `aphelios_weapons.py` reads four `aphelios_*_points` keys. Renaming an option fails at runtime rather than at import. | 26 keys | A `declared_by` field on the row, or a module-side constant the reader imports. |
| C11 | Two functions named `event_source` read different keys. `healing_helpers.py:98` reads `source_key` with a silent default and no docstring. `damage_event_row.py:71` reads `source` and raises. Not a bug today, because the rows differ, but one name has two homes and two failure modes. | | Rename the healing one `ledger_source_key`. |
| C12 | Boilerplate share, measured on the ten median modules: 27% to 45% of each file is docstring, imports and declarations. Tree-wide, 30.9% boilerplate plus 24.8% prose leaves about 44% champion formula. | | C1, C2, C3 and C5 recover most of it. `PACKET_SHA256`, `MODULE_CC`, `SOURCES` and `MODULE_COVERAGE` carry their weight and stay. |

Beginner-grade census over the 174 modules: 2 `range(len())`, 2 chained `.get().get()`, 4 string `+=` in loops, 2 appends in a loop, 1 boolean-flag parameter, and 0 of everything else.

## 6. Documentation and receipts

65 markdown files, 12,978 lines. 209 JSON receipts under `docs/`, 7.0 MB. About 8,400 lines and 186 receipts can go. 16 docs are referenced by nothing, and 17 describe finished work. No `TRAPS.md` exists.

### 6.1 Cut: finished work

| File | Lines | Evidence |
|---|---|---|
| `HANDOVER.md` | 5,987 | 70 dated work-package logs are 91% of it. Section 5 describes an uncommitted worktree from 2026-08-09 and asks the reader to preserve it, while `main` is clean. Section 6 pins 5,533 passing tests, and the suite runs about 16,420. It gives the repo path as `/Users/river/Projects/...` and holds 754 of the tree's 1,183 em-dash lines. Correction: 14 code and test files cite it by section, not 2. Section 8.5: `yuumi.py:10`, `support_effects.py:39,290`, `test_ally_support_wave2.py:1`. Section 11, the "Design rules" block: `cleanse_eligibility.py:64`, `crowd_control_eligibility.py:51`, `resource_ledger.py:16`, `spatial.py:7`, `spell_shield_eligibility.py:43`. Section 4.26 and a line number: `test_eclipse_shield_selection.py:3,18,336`. Section 9: `test_gangplank_w_cleanse.py:53`. Section 8.3: `test_keystone_audit.py:1`. Sections 8.6 and 8.7: `test_mechanics_packets.py:3`. Section 4.64: `test_senna_relic_cannon.py:546`. Section 4.12: `test_vladimir_e_charge_time.py:40,176,183,712`. The cut needs section 11 lifted into `architecture.md` with the five docstrings repointed, the Eclipse 4.26 numbers quoted inside the test, and the other citations replaced with the fact each cites. |
| `GOAL-0fails.md` | 87 | Records its own completion with "goal condition met", keeps a "Round 1, Round 2 (in progress), Round 3" progress log, and dates its baseline 2026-08-12. |
| `docs/plans/2026-09-09-fight-navigability-modules.md` | 303 | 147 of 300 backticked paths do not resolve. It cites `sl_scratch/phase-27/`, which is not in the tree. No reader. |
| `docs/roadmap-100.md` | 512 | Section 2.1 claims 149 `out_of_scope` slots and 82.8% coverage. The gated `coverage-status.md` reads 5 and 89.1%. All three citations point at section 1.3, the stats-only certification, a fact with four prose homes and two values: 90 in the roadmap, 92 in `item_coverage.py:280`, "91-plus" and "90, not 92" in `test_stats_only_items.py`. Keep a 5-line pointer at the test. |
| `docs/zero-residue-ledger.md` | 32 lines, 2,685 words | Opens "appended never rewritten". Its four probes fit as four rows in `coverage-status.md`. |
| `docs/sightline-zero-campaign.md`, `docs/surface-area-resolution-results.md` | 62 | Phase tables of closed campaigns. The second is a pointer to two other files and names a branch that is gone. |
| `docs/plans/2026-08-21-merge-202-followups.md`, `docs/plans/2026-09-02-issue-closeout-campaign.md` | 124 | The first states its own retirement rule, "delete a row when it lands", and ten of fourteen rows landed. It holds a two-way "Coordination note / Reply" chat log. The second is PR numbers and merge SHAs. |
| `docs/receipts/roadmap-closeout-verification-2026-08-21.md` and four `golden-recapture-2026-08-21-slots*.md` | 252 | Each recapture receipt closes with "Recapture executed after this attribution". An attribution's job ends at capture. |
| `docs/monetization-design.md` | 209 | Unbuilt product with no reader. It cites `docs/riot-compliance.md`, which does not exist. It is a plan, and plans are 150 lines and live in issues. |
| `DESIGN.md` | 37 | A second design system that contradicts `docs/redesign/design-language.md` on type scale, 15px body against "11 to 13px, dense on purpose". `PRODUCT.md` settles it for `design-language.md`. |
| `Project Design.tldraw` | 33 KB binary | A zipped sqlite tldraw board, untouched since 2026-08-04, referenced by nothing, not diffable. |
| `docs/coverage-frontier.md` | 124 | Its first line says not to trust its numbers: 65 out-of-scope slots against a live 5, 31 runes priced against a live 49. Move the two axis taxonomies into `coverage-status.md` without counts, then delete. |
| `docs/rotation-verification-gaps.md` | 66 | "queued for the F4 verification swarm", which does not exist. The eight open rows are real backlog. Move them to `surface-area-backlog.md`. |
| `docs/source-admission-issue-307-2026-09-08.md` | 74 | Reads as a source artifact, but its findings are open defects: Gwen healing at 50% where the wiki says 67%, Gwen E reading attack speed as AP, Azir W flattening axes. No reader, so nobody will find them. Move them to the backlog or to issues. |

### 6.2 Merge: one fact, one home

- `docs/deploy.md` at 56 lines and `docs/deploy-runbook.md` at 169 both carry the `SCRYGLASS_AUTH_*` env block, and the runbook deploys from `codex/p0a-deploy`, a branch from an earlier era. One home, `deploy.md`. About 70 lines.
- `docs/beta-operations.md` item 3 points at "deploy-runbook.md sections 1 to 2" for restore. Restore lives in `docs/backup-runbook.md`, and the pointer has been wrong since it was written. Fold `docs/monitoring.md` into `beta-operations.md`.
- `docs/patch-day-runbook.md` at 423 lines restates the `patch-update` skill in steps 1 to 4. Keep the SLA, roles, exit codes and escalation. About 120 lines.
- `docs/surface-area-backlog.md` states its rule, "delete a row when its fix lands", and 9 of 11 rows read "CLOSED ... Nothing." Each row is a paragraph essay, and SR2 and SR4 exceed 400 words. `scripts/coverage_status.py:357` counts the rows, so regenerate after the trim.
- Node version: `README.md`, `docs/ci-local.md` and `tests.yml` say 24, `ui/README.md` says 22.18, and `ui/package.json` has no `engines` field. Add the machine home.
- `docs/math-foundations.md` at 532 lines keeps its body, because 150 files cite it. Cut the branch and date letterhead at lines 3 to 8. Section 5 cites `damage.py` function names that moved into `fight/`. Write the rule down: CLAUDE.md states each formula, math-foundations states each derivation, and neither holds the other. Today 5 of the 8 Domain Knowledge facts are restated in section 5, including the level cap of 20 that CLAUDE.md itself flags as seasonal.
- `docs/onboarding-guide.md:4` points at itself and describes the pre-redesign interface.
- `docs/receipts/self-shield-carrier-rebind-2026-08-21.md` is a live rule in a receipt's clothes, cited by `participant_timeline.py:4887`. Drop the date and status lines and move it to `docs/self-shield-rebinding.md`, or fold it beside `shield_ledger.py` in architecture.md.
- `.claude/skills/analyze-champion/bug-history.md`, 208 lines and 6,104 words, is the repo's champion traps file under another name. Move it to a champion section of `TRAPS.md`.

### 6.3 JSON receipts: 186 of 209 files can go

Measured this session through the tests' own functions: standing coupled diffs 0 and standing pair diffs 0, while the 48 `expected-golden-diff-*.json` claim 5,456 paths. Every claim is against an empty set, and the three tests that read them pass by emptiness. Two carry live content. `expected-golden-diff-C6.json` holds two `coupled_exact` keys that `test_golden_snapshot.py:1486` asserts directly, and `expected-golden-diff-slots18-alistar-r.json` holds 11 of the 13 keys `declared_exact_moves()` returns. Cut 46, keep 2.

`docs/receipts/oracle-*.json` is 141 files and 1.6 MB. The only programmatic read, `test_golden_snapshot.py:1378`, globs them and filters to `leaf_path == "fights/manual_target/breakdown/Q2"`, and exactly `oracle-C6-leaf5.json` and `leaf74.json` match. The other 139 are opened and discarded on every run. They also hold all 194 hard-coded machine scratch paths in the tree, of the form `C:/Users/skywa/AppData/Local/Temp/claude/...`, and the sentence "runbook R-18/R-19 forbids me to read src/" 22 times. Keep 2, cut 139.

Orphans: `docs/manual-rank-sources.json` and `docs/receipts/oracle-P4B-leaf29.json`. Keep the 13 gated receipts and the 5 single-purpose ones listed in the auditor report.

### 6.4 `CLAUDE.md`: 62 Known Quirks, 4,845 words, 86% of the file

Classified: 38 TRAP entries, about 2,595 words, go to `TRAPS.md` in six sections: tests and CI; goldens and receipts; engine and pricing; platform and tooling; frontend and vision; champions, which absorbs `bug-history.md`. 16 DESIGN entries, about 1,376 words, go to `architecture.md`. 7 RULE entries, about 703 words, stay. 1 DATA entry, the degraded-parse champion list that `coverage-frontier.md:43` duplicates, goes to `coverage-status.md`.

Correction: the docs auditor first reported every citation as resolving. Its cross-check found five stale citations in the 62 entries, each re-verified against the tree:

| Entry | Claim | Tree |
|---|---|---|
| Sightline and ruff | `.sightline-baseline` holds a rule #54 row and a rule #35 row | The file holds rules 27 (53 rows), 14 (3) and 11 (3) only |
| Full-suite runs under concurrent edits | three tests pin `inspect.getsource` | Only `test_trigger_stream.py` does. `test_import_namespace.py` and `test_gate_receipt.py` use `Path.read_text`. The hazard stands, the API claim does not |
| The pylint score gate | `_percent_ratio` at lines 982 and 1544 | Lines 1088 and 1650 |
| Atom manifest digests | the `data/bin/characters` bins are gitignored | 183 are tracked, and `.gitignore:38` says "TRACKED" |
| Charge cadence | "11 Electro Harpoons in a 10 s fight" | `charge_cadence.py:8` says "16 basic-ability casts" for the same defect |

Five stale citations in 62 entries is the measured drift rate of a 4,800-word section with no gate. Eight entries duplicate another home in substance, including three docstrings: charge cadence against `charge_cadence.py:1-23`, Terminus pen against `fight/resists.py:17-28`, the CC vocabulary against the `control_spec.py` header. Two entries narrate: "intended since 5055dc5", "217 findings to 216". Entry 50 is two traps in one bullet. Entry 32, at 282 words, is the largest and is a pointer to `pyproject.toml` plus the baseline policy.

Target: `CLAUDE.md` at about 65 lines and 1,500 words, `TRAPS.md` at about 250 lines, `architecture.md` at about 300. Stop it growing back with a word-budget test in the shape `tests/test_p0b_ops.py` already uses, and promote the `pointer` rule in `scripts/prose_lint.py` from reporting to failing once the campaign docs are gone.

One naming collision to fix: `scripts/prose_lint.py` targets `src` and `scripts` and never reads markdown, while the plugin hook `comment_lint.lint_prose` reads markdown. CLAUDE.md calls both "prose lint" with nothing saying they differ.

## 7. Cross-cutting agent residue

| # | Category | Measured | Proposal |
|---|---|---|---|
| X1 | Campaign and issue archaeology: 2,233 markers in 495 `.py` files, 1,421 in docstrings, 603 in comments, 209 in code. By token: `campaign` 445 hits, `Phase N` 298, `issue #NNN` 142, `CP10.x` 97, "this campaign exists to" 27, `runbook R-NN` 22. Only three kinds of marker resolve to something real: the three `campaign-*.json` receipts that `behavior_frontier.py` and `golden_snapshot.py` read, `ER5_TAIL` and `ROOTS`, and open issues. Worst case: `tests/test_eclipse_shield_selection.py:18` names `HANDOVER.md:1311` as its source of truth. | 495 files | Rule: a campaign token in prose must sit beside a path that resolves, or be `issue #N` for an open issue. Otherwise state the fact. About 30 lines in `scripts/prose_lint.py`, with a count that may only fall. Extend it to test docstrings. The length exemption stays, the "no dangling pointer" rule applies. |
| X2 | One concept, many spellings. Refusal has 11 spellings: `refused` in 141 names, `withheld` 61, `blocked` 45, `refusal` 41, `excluded` 35, `denied` 31, `starved` 16, `unavailable` 16, and three more. Only `Withheld` and `Starved` are types. 20 modules use 5 or more, and `quantity.py` itself uses 5. This is the costliest split, because the whole design rests on failing closed with a named reason, and the reason has six names. Also `catalog` 55 against `catalogue` 10, all in the atomizer, `teammate` against `ally`, `wearer` against `holder`, and `record` at 70 with no documented stage. | | Give refusal one owner in `quantity.py`. Ban the rest by lint outside `quantity.py` and `control_spec.py`. Codemod `catalogue`, `teammate`, `wearer` and `record`. |
| X3 | Multiple homes for one fact. Gate commands live in five homes, `tests.yml`, six `ci/*.sh`, `Makefile`, `docs/ci-local.md` and `CLAUDE.md`, with nothing that checks agreement. `ci/static.sh:27` and `tests.yml:120` both spell the pylint line and its justifying comment. Seven of CLAUDE.md's 16 commands reach CI only through a test. The Python version has four homes and one live divergence, see A4. 206 hand-listed string collections of 8 or more entries hold 4,696 entries. `ER5_TAIL` is fully derivable, and `_CHAMPION_MODULES` at 173 could be a glob plus the contract validator, which is the fail-closed property that matters. | | Generate `ci/*.sh` from `tests.yml` with a `--check`, or delete them and have `make` call `act`. Derive `ER5_TAIL`. |
| X4 | Suppression markers: 243 `pylint: disable`, 100 `type: ignore`, 53 `noqa`, 25 `pragma: no cover`, 18 `sightline-ok`, 9 real `xfail`, 52 `pytest.skip`. Every `noqa` and `sightline-ok` carries a reason. 53 `type: ignore` have one cause, P13. 163 pylint arity and locals disables overlap sightline, P11. | | Fix the two causes and leave the rest. |
| X5 | Leftovers: 3 to-do markers, at `src/app.py:1940` (a cross-group pointer), `test_eclipse_shield_selection.py:182` (an unfiled merge debt tagged for the interpreters) and `test_gate_receipt.py:241`. 194 absolute machine paths in tracked receipts, 96 `C:\Users\...` and 98 `/Users/...`, nearly all in the oracle receipts of 6.3. Four files are LF by accident with no `.gitattributes` entry. | | One lint over tracked JSON: no string that matches `^[A-Za-z]:[\\/]` or `^/(Users\|home)/`. File the merge debt. |
| X6 | Data surface: 41.2 MB of tracked JSON. `data/atoms/v2` is 166 files, 9.3 MB and 537,810 lines, landed in the code-free commit `5b0ad6ea`, with no generator, no manifest, and one reader at `test_milio_fired_up_blocker.py:49`. `GOAL-0fails.md` records that its last effect was 48 suite failures from "depth2-atom-corpus data drift". `data/item-atoms` is 325 files and 1.4 MB, documented as retired by `test_build_receipts.py:3`. Two atomizers exist, `scripts/atomize.py` and `scripts/extract_atoms.py`, the second calling itself "WS3 atomic catalog, v2", writing two schemas into one directory while the `atomizer` skill says there is one. | about 12 MB, 1,300 files | Delete `data/item-atoms` and `data/atoms/v2`, keeping `milio.atoms.v2.json` as a test fixture or inlining its values. Retire one atomizer. Add one test: every tracked file under `docs/receipts/` and `data/atoms/` is named by a regenerator or read by a test. |
| X7 | Frontend. `escapeHtml` is duplicated verbatim in `eventorder.js:25` and `feedback.js:44`, and two HTML escapers that can drift is the one duplication with a security edge. `render` is defined in 3 files and `init` in 2, with no `shared.js`. 216 lines of inline `<style>` sit across 5 templates. 64 CSS classes are dead: 26 in `ui/src/calculator.css`, 16 in `champion-hud.css`, 9 of 15 in `tooltip.css`. `ui/src/scoreboard-vision.js` looks like a copy of `static/js/scoreboard.js` but `build.mjs` generates it under a `--check` gate, which is correct single sourcing. | | Extract `static/js/shared.js`. Move the inline CSS to `style.css`. Run PurgeCSS over `ui/src/*.css`. |
| X8 | Tooling: 10 quality tools and 10 domain gates. `pyproject.toml` arbitrates the overlaps with a reason on every ignore, and `.sightline-baseline` holds 59 entries, 53 of them rule #27. Disciplined, not sprawl. The cost is drift: CLAUDE.md describes baseline entries the file does not hold. | | Derive the sentence from the file. |
| X9 | Stray root files: `HANDOVER.md`, `GOAL-0fails.md`, `DESIGN.md`, `Project Design.tldraw`, `PRODUCT.md` with 0 readers but current content, and `Agents.md`, which stays as the non-Claude entry point. | | See 6.1. Link `PRODUCT.md` from the README. |

Clean tree-wide: no debug prints, no tracked artefacts, no conflict markers, no orphaned worktrees, one documented OS assumption at `data_updater.py:25`, every `__init__.py` docstring-only per architecture.md, and 1,132 of 1,187 module docstrings ending in a period.

## 8. Correctness asides found on the way

These are not slop, but each surfaced because a test or a receipt was gating around a defect instead of fixing it.

| # | Finding | Location | Evidence |
|---|---|---|---|
| A1 | Akshan's E per-shot damage does not scale with attack speed, and the repo pins that as "still tracked" rather than fixing it. | `champions/akshan.py`, `tests/test_champion_inputs.py:234-278`, `docs/receipts/escalated-defects-P3-3.7.json` | The test asserts `_extract_e_per_shot` returns the same value at 0 and at +250 bonus attack speed, and that the stat it reads is absent from `calculate_total_stats`. |
| A2 | Seven cached-prose readers degrade silently to a `MEASURED` zero on a reworded wiki row. | `sett.py:310`, where `derive_self_healing` returns `[]` when either regex misses and zeroes the whole passive regen; `akshan.py:84,107,135`; `chogath.py:89,106`; `taric.py:263` | `CachedSentence.match` raises `ValueError(self.missing)`. These hand-rolled readers return empty. Fix before the next patch pull. |
| A3 | `StateTimeline.transitions()` sorts with `key=lambda t: (..., self._transitions.index(t))`, which is O(n^2 log n) per fight timeline. The unused `_order` counter of D11 is the intended fix. | `state_timeline.py:152,171` | Stamp `_order` onto each `Transition`, or drop the fourth key because `sorted` is stable. |
| A4 | `Dockerfile:6` pins `python:3.15.0rc2-slim`. `.python-version` and all three CI jobs pin 3.14, and the `pyproject.toml` comment asserting the Dockerfile runs 3.14 is false. Production runs a release candidate of a version nothing tests. | `Dockerfile:6` | Pass `.python-version` as a build argument. |
| A5 | `ResourceAccount` takes `regen_per_second` with a 5-line finiteness validation threaded from `mana_walk.py:52-58` and never applies it. `mana_walk.py:193-204` computes regen from its own local. | `resource_ledger.py:117` | Cut the parameter. |
| A6 | `AllyStatEffect.assumption` holds a real disclosure sentence, that the ally healed or shielded the attacker immediately before combat, and nothing publishes it. | `ally_effects.py:138` | Wire it to the response's disclosure channel. |
| A7 | `.wiki-popover`, D39: the advanced page's item tooltip silently misses the Scryglass theme override the rule intended. | `static/css/scryglass-theme.css:71` | Rename to `.item-tip`. |
| A8 | `test_knights_vow_compiled_parity.py:1238 test_enemy_holder_poisons_the_compiled_context_and_falls_back` is byte-identical to `:1285` and asserts the opposite of its name, `ctx.uncompilable is False`. If the poisoning case was meant to be covered, it is not. | `tests/test_knights_vow_compiled_parity.py:1238` | Delete one, name the survivor honestly, and decide whether the poisoning case needs a real test. |
| A9 | `item_coverage._TARGET_MODELED_IMPLS` names the dead `interpreters.sustain.sustain_slot` as the pricing home for three items, D4. The receipt resolves only because the symbol exists. | `item_coverage.py:1789,1794,1795` | Repoint to `declared_sustain`. |
| A10 | `fight/after/amplifiers.py:279` defaults `total_damage` to int `0` where the other 28 sites use `0.0`. No live effect, but it is the published-zero-type trap CLAUDE.md records. | `fight/after/amplifiers.py:279` | `0.0`. |
| A11 | `participant_timeline.py:864-871` declares a PEP 695 type parameter on `_keystone_holder[KeystoneEffect]` and then uses the module-level `TypeVar` instead, so the parameter is dead. | `participant_timeline.py:864` | Pick one mechanism. |
| A12 | Four tests read repo files through cwd-relative paths and pass only from the repo root: `test_jayce_w_mana_restore.py:167`, `test_mel_searing_brilliance.py:67`, `test_naafiri_pack.py:74`, `test_participant_timeline.py:5888`. | | Anchor on `ROOT`. |
| A13 | `test_optimizer.py:819` asserts optimization under 15 s. Its docstring records the cap was loosened from 8 s when the CI multiplier moved. A gate loosened whenever it fires is not a gate, and `benchmarks.md` is the home. | `tests/test_optimizer.py:819` | Delete. |

## 9. Proposal

The work is deletion first, structure second, and one long mechanical campaign third. Every step gates on `pytest`, `black --check`, `pylint src/`, and both golden compares showing zero diffs. Codemods run one at a time with a green golden between each, never batched, because compiled slot order and ledger insertion order are numeric.

### Phase 1: delete what nothing reads, one PR, zero risk

1. Tracked data: `data/atoms/v2` keeping `milio.atoms.v2.json` as a fixture, `data/item-atoms`, 139 `oracle-C6-leaf*.json` and the P4B orphan, 46 `expected-golden-diff-*.json`, `docs/manual-rank-sources.json`, the 11 files under `ui/assets/league/`, `static/fonts/`, `static/img/stat-icons/`, `Project Design.tldraw`. About 17 MB and about 1,500 files.
2. Docs: the 17 finished-campaign docs in 6.1, after lifting HANDOVER section 11 into `architecture.md`, quoting the Eclipse 4.26 numbers into `test_eclipse_shield_selection.py`, and repointing the other 12 HANDOVER citations. Merge the deploy, monitoring and coverage pairs of 6.2. Trim `surface-area-backlog.md` to its four open rows and regenerate `coverage-status.md`.
3. Scripts and frontend: D34 to D41.
4. Two guards: a test that every tracked file under `docs/receipts/` and `data/atoms/` is named by a regenerator or read by a test, and a lint that no tracked JSON holds a machine path.

### Phase 2: split CLAUDE.md into CLAUDE.md, TRAPS.md and architecture.md, one PR

Create `TRAPS.md` with the six sections of 6.4, the champion traps from `bug-history.md`, and the docstring traps from Naafiri, Rumble, Sylas and Gnar. Move the 16 DESIGN entries to `architecture.md`. Fix the five stale citations, the three docstring duplicates, and `architecture.md:210`. Add the word-budget test. Promote the `pointer` rule in `prose_lint.py` to failing.

### Phase 3: tests, three PRs

1. One codemod moves the three champion contract tests into `test_module_cc_census.py`, replaces the 69 docstrings with a pointer, and drops the 76 `cc_kinds == MODULE_CC` restatements. Then the `test_item_damage.py` fixture codemod and the `.clear()` to `monkeypatch` codemod of 2.7.
2. Delete the closeout blocks of 2.4, the deletion freezes of 2.5, the bug pins of 2.6 after fixing Akshan, the substring tests of 2.3, and the tautologies of 2.8. Parametrize 2.9.
3. Relocate: the `test_literal_defaults.py` matrix to a baseline file with a derived `ER5_TAIL`, the `test_p1_review_*` champions into their own files, the six lints into `scripts/`. Rename the 69 campaign-named files. Fix the xfail doc rot and apply the skip-versus-deselect ruling.

### Phase 4: dead code and wrappers, two PRs

1. D1, keeping `RIDER_KINDS` and the rider classes for `receipt_walk_schedule.py`. D2. D4 with the `_TARGET_MODELED_IMPLS` repoint. D27. Then D3 and D5 to D26 as one sweep.
2. D29 to D33, the facade, gated on the goldens for import order. W2 to W12.

### Phase 5: champion codemods, one PR each with goldens between

In order of payoff and risk: `SelfHealCtx` (C1); the seven silent prose readers and then the rest of the `CachedSentence` migration (C4, A2); `@ability_slot` (C5); the `no_damage_slot` and `damage_entry` hold-outs (C4); `_ROTATION_CLASSIFICATIONS` onto OPTIONS rows (C7); `at_level` and `extract_cast_time` by hand (C4, C8); the ten rule classes (C6); the docstring cap and history strip, per file, with traps routed to `TRAPS.md` (C2); the ASSUMPTIONS cap in `prose_lint.py` (C3).

### Phase 6: core structure, the long campaign

1. Typed row readers over the 1,616 `.get(key, literal)` sites, P1. Mechanical, module by module, with goldens between. The `test_literal_defaults.py` count shrinks to zero as it lands, and the file goes.
2. Split `derive_item_support_effects` and `_compose_pass` through `extract_modules.py` assignment files, P3.
3. Collapse the exception hierarchy and the `typed_payload` re-check, P4 and P5. Tests move to `ValueError` plus a message.
4. The history-prose sweep in runtime source, P6 and X1, with the lint landed first so it cannot return.
5. `aggregate_public_results` and `_validate_payload` to tables, P8 and P5. `binary_roots.dig`, P10. The comprehension pass, P12. The `ITEM_EFFECTS` typed accessor, P13. The refusal vocabulary, X2.
6. Last, and gated by a `benchmarks.md` row landed first: the `SurvivalAction` split per `ActionKind`, P2.

### What to leave alone

The leaf-module style, the `partial` aliases, the `MappingProxyType` freezes, the single-member enums, the long parameter lists with stated reasons, the `_compile_<rune>`, `_parse_<item>` and `_<x>_owners` registry rows, the M1 to M9 mutation suite, `test_survival_kernel.py`, `test_module_cc_census.py`, `conftest.py`, the `test_e1` to `test_e9` files, and every gate whose reason sits beside it in `pyproject.toml`. Two auditors reached the same conclusion independently: the codebase is in better shape than its prose.

## Sources

This file condenses eleven per-dimension reports with full grep evidence per finding, written to `.audit/` during the audit and not tracked. Their scopes: dead code in core `src/`; dead code in champions, scripts and frontend; low-value tests in four alphabetic slices plus the `tests/` helpers; wrappers and stubs; code patterns in core `src/`; code patterns and drift across the champion modules; documentation and receipts; cross-cutting residue over the whole tree.
