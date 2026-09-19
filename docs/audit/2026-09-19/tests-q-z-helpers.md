# Slop audit: low-value tests in `tests/test_[q-z]*.py` and the `tests/` helpers

Scope: 182 files matching `tests/test_[q-z]*.py`, 62,102 lines, plus the 20 non-`test_`
modules under `tests/`, 3,281 lines. Read-only audit. Nothing was edited.

## Counts per category

| # | Category | Candidates | Findings | Lines removable |
|---|---|---|---|---|
| 1 | Asserts something was removed or does not exist | 61 hits in 23 files | 11 | 430 |
| 2 | Pins source text of `src/` or `static/js` | 11 test files, 4 helpers | 7 | 590 |
| 3 | Tautologies | 25 no-assert tests, 20 of them false positives; 118 constant pins | 5 | 130 |
| 4 | Duplicates and un-parametrized copy-paste | 74 normalized-duplicate bodies; 3 census tests replicated 56 to 64 times | 8 | 1,320 |
| 5 | Campaign residue and receipt-fingerprint tests | 48 `expected-golden-diff-*.json` read by one pin; 7 issue-named tests | 4 | 270 |
| 6 | Skips, xfails, unused fixtures | 22 `pytest.skip` sites, 0 unused fixtures | 3 | 0 |
| 7 | Oversized files and docstrings | 11 files over 700 lines, 3 docstrings over 130 lines | 3 | 290 |
| 8 | Shared process state and wall clock | 8 process-cache `.clear()` calls, 6 `sys.path.insert`, 1 `time.sleep(60)` | 3 | 0 |

Total removable in this slice: about 2,770 lines, 4.2 percent.
All 20 helper modules are used. None is dead. None duplicates a helper in `src/`.

## Summary table

| # | Finding | File::test | Cat | Lines | Proposal |
|---|---|---|---|---|---|
| F1 | Two identical census tests, one copy per champion | `test_[q-z]*.py::test_a_timed_fimbulwinter_fight_is_fully_certified` (60 files), `::test_every_ability_event_carries_the_review` (56 files) | 4 | 483 | Merge into `test_module_cc_census.py` as one parametrized pair |
| F2 | 31 of 49 tests pin strings inside `static/js/*.js` | `tests/test_redesign_frontend.py` | 2 | 310 | Delete the source-only tests, keep the 18 that run node or the Flask client |
| F3 | Nine tests drive the shared cleanse kernel; four pin the feature's absence | `tests/test_rengar_w_cleanse.py` | 4, 1 | 391 | Delete. `tests/test_cleanse_eligibility.py` owns all of it |
| F4 | Section labelled "mirrors the originals" | `tests/test_verdant_barrier_compiled_parity.py` lines 1209 to 1412 | 4 | 181 | Delete the section |
| F5 | Full-tree AST scans proving deleted names stay deleted | `test_trigger_stream.py::test_a2_*`, `::test_a4_*`, `::test_no_retired_symbol_is_named_anywhere_in_src_not_even_in_prose`, 3 seams | 1, 2, 5 | 171 | Delete all eight |
| F6 | `cc_kinds == MODULE_CC` restated per champion; one docstring copied into 69 files | 29 and 69 files in slice | 3, 7 | 374 | Assert once in the census, replace the docstring with a pointer |
| F7 | Golden re-derivation weakened by a 3,063-path allowlist | `test_syndra.py::TestTheDerivedOrderPinScenario` and `::TestTheCustomOrderPinReadsTheBaseline` `test_the_live_run_reproduces_the_committed_entry` | 5, 4 | 90 | Delete. `golden_snapshot.py compare` is the gate |
| F8 | One fail-closed path written four times | `test_rune_effects.py::test_missing_registry_key_raises_with_context` and `::test_missing_distance_scaling_raises_with_context` | 4 | 52 | One parametrize |
| F9 | Two module docstrings narrating finished campaigns | `test_verdant_barrier_compiled_parity.py:1`, `test_rengar_w_cleanse.py:1` | 7 | 270 | Cut each to 15 lines |
| F10 | `legacy_phase` deletion scan, `CAPABILITY_SCHEMA_VERSION == 9`, a source grep | `test_transition_rank.py:505,783,886` | 1, 3, 2 | 59 | Delete two, move the third to `scripts/literal_defaults.py` |
| F11 | `not hasattr` tails on six retirement tests | `test_tag_dispatch_parity.py:140,156,158,200,214,307` | 1 | 10 | Strip the tails, keep the parity assertions |
| F12 | Process-global caches cleared in tests | `test_rotation_semantics.py:38,229,253,296,311,312`, `test_rotation_resolver.py:232,241` | 8 | 0 | Use `monkeypatch.setattr` to a fresh dict |
| F13 | Test re-runs the production loop and asserts its own output | `test_yuumi.py::test_the_retired_claim_is_false_the_caster_channel_exists:273` | 3, 1, 2 | 19 | Delete |
| F14 | Asserts two methods that never existed still do not | `test_rengar_ferocity_ledger.py:469` | 1 | 2 | Strip two lines |
| F15 | `assert not hasattr(samira, "MODULE_COVERAGE")` | `test_samira.py:59` | 1 | 1 | Strip one line |
| F16 | `static/data.json` and `app.js` string greps | `test_static_data.py:77,78,92` | 2, 1 | 35 | Drop the three absence greps |
| F17 | Constant equals its literal | `test_rotation_resolver.py:333` | 3 | 8 | Delete, the sibling test is the real check |
| F18 | Six of twelve tests never run off POSIX; 22 skips depend on a gitignored cache | `test_wiki_refresh.py`, 10 champion evidence files | 6, 8 | 0 | Report the unrun evidence checks the way conftest's D-22 ruling does |
| F19 | 23 more duplicate bodies that should be parametrize rows | `test_vayne.py`, `test_state_lifecycle.py`, `test_zeri_p_execute_range.py`, `test_vladimir_e_charge_time.py`, `test_redemption_packet.py`, `test_rune_paths_*` | 4 | 400 | Collapse to parametrized rows |

## F1. Two census tests replicated 116 times

```
tests/test_qiyana.py:64  test_a_timed_fimbulwinter_fight_is_fully_certified   60 files here, 131 tree-wide
tests/test_rakan.py:88   test_every_ability_event_carries_the_review          56 files here, 105 tree-wide
```

Every copy is identical except the champion string:

```python
def test_every_ability_event_carries_the_review(self):
    assert cc_review.unreviewed_ability_slots("Rakan") == []

def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
    coverage = cc_review.fimbulwinter_coverage("Rakan")
    assert coverage["complete"] is True
    assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
```

No value: there is no per-champion content. One roster-wide invariant is written out 116
times, so adding a champion means remembering to paste it again. That is the drift
`tests/test_module_cc_census.py` exists to catch, and that file already carries the right
shape, `@pytest.mark.parametrize("name", CHAMPIONS)` over four tests.

Proposal: move both into `test_module_cc_census.py` as two parametrized tests, about 10
lines, and delete the 116 copies. The report still names the failing champion, and a new
champion is covered the moment it registers.

## F2. `tests/test_redesign_frontend.py` pins JavaScript source text

31 of 49 tests run no code. They assert literal substrings of `static/js/app.js`,
`feedback.js`, `eventorder.js`, or a CSS file, at lines 111, 132, 169, 176, 187, 193,
204, 229, 240, 252, 260, 266, 271, 277, 288, 330, 348, 359, 410, 429, 441, 451, 479,
490, 515, 537, 552, 592, 604, 618, 696.

```python
assert "DATA.items = catalog.map((entry) => ({" in body
assert "...entry," in body
for gone in ("QUICK_STATE", "renderQuickView", "bindQuickEvents"):
    assert gone not in source
```

No value: these pin the spelling of an implementation, not a behaviour. Renaming a local
or re-wrapping a line turns them red with no user-visible change, and any of them can
stay green while the widget is broken. Nine are category 1, freezing 2026-08 deletions.

Proposal: delete the 31 source-only tests. Keep the 18 that drive node at line 641, the
Flask client, or the parsed DOM. If the receipts-only contract is worth keeping, no
`0.7025`, `0.0175`, or `crit / 100` in `app.js`, promote that one check to a lint in
`scripts/` beside `literal_defaults.py`.

## F3. `tests/test_rengar_w_cleanse.py` tests another module's kernel, and a non-feature

Nine tests drive the generic cleanse kernel, several of them with Gangplank rather than
Rengar:

```
917  test_kernel_rengar_declaration_gates                      60L
978  test_kernel_cleanse_fires_while_caster_crowd_controlled    26L
1018 test_kernel_heal_cast_while_disabled_carve_out             22L
1143 test_kernel_one_use_latch                                  42L
1186 test_kernel_second_gp_activation_use_spent                 37L
1254 test_truncate_intervals_contract                           23L
1278 test_kernel_truncation_historical_remains_later_untouched  35L
1513 test_kernel_heal_unchanged_by_cleanse                      31L
1594 test_kernel_cleanse_packet_never_prices_damage             28L
```

`tests/test_cleanse_eligibility.py`, 2,723 lines, already owns each one:
`test_r14_repeated_use_second_activation_fails_closed` for the latch, `test_r12` and
`test_r13` for truncation, `test_r15_*` for the unknown kind,
`test_r10_no_active_control_mikaels_heal_still_fires` for heal non-interference,
`test_r24_mercurial_movement_is_a_separate_utility_effect` for the damage-free packet.

Four more pin the absence of the feature the file was written for:

```
1115 test_a_kind_outside_the_vocabulary_never_reaches_the_kernel   9L
1346 test_named_denial_vocabulary_pinned                          23L
1370 test_rengar_source_unresolved_fails_closed                   15L   asserts a KeyError
1386 test_no_cleanse_receipts_in_fight_today                      40L
```

No value: the module docstring says the P2-6 wiring has not landed and that absent
mechanics are marked `pytest.mark.xfail`. The xfails are gone and what remains asserts
the gap, so the day P2-6 lands the suite goes red on a correct change.

Proposal: delete the nine kernel tests and the four absence pins. Keep S1 to S3, the
cached W rows, base versus empowered pricing, and the live Ferocity condition, and S9 to
S13, the grey-health heal, byte parity, and no duplicate damage. Those are Rengar's own
behaviour.

## F4. `tests/test_verdant_barrier_compiled_parity.py` section 9

```
1222 test_regression_surface_defensive_effects_annul_is_ready            9L
1233 test_regression_surface_issues_46_annul_blocks_one_typed_ability   40L
1275 test_regression_surface_spell_shield_eligibility_auto_attack_gate  61L
1338 test_regression_surface_participant_timeline_opening_annul         24L
1364 test_regression_surface_app_opening_enemy_spell_shield             39L
1405 test_regression_surface_item_coverage_target_models_annul           8L
```

Every docstring opens with "Mirrors `test_<other file>.py`". The section header reads
"Existing regression surface (kept green, disjoint, mirrors the originals)".

No value: a copy that announces it is a copy. Two homes for one assertion means two edits
and one silent divergence. The file's core mechanic is triple-covered already, because
`test_spell_shield_eligibility.py::test_r2_annul_items_block_one_ability_then_second_passes`
parametrizes over all three Annul items including Verdant Barrier.

Proposal: delete section 9. Then compare sections 4 to 7 against
`test_spell_shield_eligibility.py` and keep only the item identity, typed accessor, and
compiled certification tests that are specific to this item.

## F5. `tests/test_trigger_stream.py` A2, A4, and the prose scan

```
1086 RETIRED_SYMBOL_HOMES   15 symbols, every value []
1129 test_a2_the_retired_scanners_are_defined_only_in_their_retiring_module
1134 test_a2_has_a_permanent_injection_seam
1229 LEGACY_NAME_SET_SITES  8 symbols, every value []
1263 test_a4_the_legacy_name_sets_occur_exactly_where_the_schedule_says
1268 test_a4_has_a_permanent_injection_seam
1310 test_no_retired_symbol_is_named_anywhere_in_src_not_even_in_prose
1315 test_the_prose_scan_has_a_permanent_injection_seam
```

The comments state it outright: "P2b/P2c emptied it, so every entry is now `[]`", and
"the criterion this discharges is zero occurrences in `src/`".

No value: a campaign's closeout checklist, frozen. Nobody will reintroduce
`_fimbulwinter_trigger_kind` or `TAKEDOWN_SCAN_SUPPORT_ITEMS`, and doing so would be
deliberate. The prose scan is the worst of the three, because it forbids the string from
appearing in any comment under `src/`, which makes an honest note about the history
illegal. Each scan parses every file under `src/` twice, live and injected, so the three
cost six full-tree AST walks.

Proposal: delete all eight. Keep A1, A3, and A5 to A9. Those check live invariants, one
`cc_kind` parser, guarded equals declared, nobody branches on the opaque receipt token,
one immobilize vocabulary, every declared stream load-bearing, and their injection seams
earn their place there.

## F6. Restated constants and one docstring in 69 files

In 29 files here and 76 tree-wide:

```python
assert volibear.parse_abilities.cc_kinds == volibear.MODULE_CC
```

`packet_module.compile` stamps `cc_kinds` from `MODULE_CC`, so this holds by construction
for every module. It cannot fail for one champion without failing for all.

In 69 files, word for word:

> A control-armed holder shield (Fimbulwinter's Everlasting) has to know whether an
> ability event was a control event; an ability packet that never says makes the whole
> timed fight fall back to coarse ordering. `MODULE_CC` is where this kit answers, read
> from the cached text.

No value: 69 homes for one fact, against CLAUDE.md's rule that each fact lives in one
place. When the Fimbulwinter rationale changes, 69 files drift.

Proposal: assert `cc_kinds == MODULE_CC` once, parametrized, in
`test_module_cc_census.py`. Replace the repeated docstring with one line pointing there.
Keep the per-champion `assert X.MODULE_CC == {...}` literal and the cached-text check
through `cc_review.slot_text` and `cc_review.control_words`. That pair is the real review
and it is genuinely per champion.

## F7. `tests/test_syndra.py` re-derives a golden behind a 3,063-path allowlist

```
409 _coupled_baseline()    reads scripts/golden_coupled_baseline.json
500 _allowlisted_moves()   unions docs/receipts/expected-golden-diff-*.json
523 _pin_diffs(name)       golden_snapshot.leaf_report(committed, live)
530 _assert_pinned(name)
554 TestTheDerivedOrderPinScenario::test_the_live_run_reproduces_the_committed_entry[39|60|120]
590 TestTheCustomOrderPinReadsTheBaseline::test_the_live_run_reproduces_the_committed_entry[39|60|120]
```

Measured this session: `_allowlisted_moves()` unions 48 receipt files into 3,063 admitted
leaf paths, 356 of them Syndra-scoped, and only 75 carry a declared new value. A diff on
any of the other 2,988 paths satisfies `assert diff.path in claimed` with no value check.

No value, three ways. It re-implements
`scripts/golden_snapshot.py compare scripts/golden_coupled_baseline.json`, which CLAUDE.md
names as a pinned compare target and CI already runs. Its own docstring concedes the end
state, "Once the boundary lands the difference set is empty and both clauses hold
trivially", and that state is now. The allowlist is append-only, so the pin weakens on
every campaign.

Proposal: delete `_allowlisted_moves`, `_pin_diffs`, `_assert_pinned`, and the six pinned
rows. Keep `test_q_recasts_at_five_seconds`,
`test_the_second_charge_rides_its_parents_cast_times`,
`test_the_derived_timeline_is_not_the_requested_one`, and
`test_the_requested_order_keeps_the_second_charge`. Those assert C6's fold rather than
re-checking a committed file.

Aside, off task: the same union over `docs/receipts/expected-golden-diff-*.json` is a
tree-wide hazard. Any other suite that reads it inherits the same monotonic weakening.

## F8. `tests/test_rune_effects.py` writes one fail-closed path four times

```
282 test_missing_registry_key_raises_with_context      Electrocute,      ap_ratio
338 test_missing_registry_key_raises_with_context      First Strike,     gold_conversion_ratios
425 test_missing_registry_key_raises_with_context      Press the Attack, stack_duration_seconds
521 test_missing_distance_scaling_raises_with_context
```

The bodies are identical apart from two strings: build a `broken` registry with one key
removed, `monkeypatch.setattr`, then `pytest.raises(KeyError, match=...)`.

No value: three of the four exercise one branch in `rune_effects.resolve_rune`. The extra
rows add lines, not paths. Three functions also share a name in one module, so a failure
report is ambiguous at a glance.

Proposal: one `@pytest.mark.parametrize(("rune", "key"), [...])` over a
`_broken_registry(rune, key)` helper. 72 lines become about 20.

## F9. Two module docstrings narrate finished campaigns

```
tests/test_verdant_barrier_compiled_parity.py:1   154-line docstring for one item
tests/test_rengar_w_cleanse.py:1                  138-line docstring for one slot
```

Both read as run-books: "CURRENT RUNTIME FACTS (verified before pinning)", "The
coordinator's completion (P2-6) will (most likely)", a numbered S1 to S13 brief.

No value: CLAUDE.md asks for current state only and no comment longer than its function.
These are longer than most of the tests below them, and the forward-looking half is
already false in places. The facts worth keeping, the cached row values and the game-file
evidence, belong in assertions where they are checked.

Proposal: cut each to 15 lines naming what the file owns, pointing at the champion module
and `TRAPS.md`.

## F10. `tests/test_transition_rank.py`

```python
# 505  test_the_float_projection_is_deleted_from_the_tree, 21 lines
for path in sorted((ROOT / "src").rglob("*.py")):
    ...
assert offenders == []
assert not hasattr(actions_module, "legacy_phase")
```

A full-tree AST walk proving a name nobody will retype is still absent.

```python
# 783  test_s6_publishes_no_new_phase_name_and_bumps_no_schema, 30 lines
assert CAPABILITY_SCHEMA_VERSION == 9
```

A hand-maintained literal whose own comment explains that neither 8 nor 9 belongs to S6.
It goes red on the next honest schema bump for a reason unrelated to the test's name. The
`PARTICIPANT_LEDGER_CONTRACT["phases"]` half of the same test is the real assertion.

```python
# 886  test_both_ledgers_read_the_one_helper, 8 lines
assert "scheduled_heal_time(heal_event)" in source, module
assert 'heal_event.get("time", 0.0)' not in source, module
```

A source grep, but it guards a real failure class, the rule-5 literal default.

Proposal: delete the first. Split the second so only the published-phase list survives.
Move the third into `scripts/literal_defaults.py`, the tree's one home for a literal
fallback on cached data.

## F11. `tests/test_tag_dispatch_parity.py` retirement tails

```
140 assert not hasattr(_ladder(owner), "execute")
156 for retired in ("crit_damage_bonus", "navori_refund_percent"): assert not hasattr(ladder, retired)
158 assert not hasattr(ladder, "cooldown_refund_source")
200 assert not hasattr(_ladder(owner), "first_auto_crit")
214 assert not hasattr(_ladder(owner), "on_hit_heals")
307 assert not hasattr(_ladder(owner), "magic_amp")
```

The module docstring calls this deliberate: "each retired tag keeps a test asserting the
projection carries no field for it".

Low value: the catalog-side assertions in the same tests, each number read through
`required_effect_value`, are what prove the number has one owner. The `not hasattr` tail
adds only that the old field is still gone, which no refactor threatens, and it blocks the
name being reused.

Proposal: strip the six lines and rename the tests from
`..._is_retired_from_the_ladder_and_owned_by_the_catalog` to `..._is_owned_by_the_catalog`.

## F12. Process-global caches cleared in tests

```
tests/test_rotation_semantics.py:38   autouse fixture clears _DERIVED_RULE_CACHE after every test in the file
tests/test_rotation_semantics.py:229, 253, 296, 311
tests/test_rotation_semantics.py:312  ability_dps_matrix._MATRIX_DPS_CACHE.clear()
tests/test_rotation_resolver.py:232, 241
```

CLAUDE.md states the rule: never `.clear()` a process-wide cache in a test, because it
passes and silently costs every later test the warm cache. The autouse fixture makes it
worse, evicting the resolver memo after all 11 tests in the file, so every later test on
that xdist worker pays a cold resolve. It is the shape behind the two gates that went red
on `main` only.

Proposal: use `monkeypatch.setattr(champion_rotation_rule, "_DERIVED_RULE_CACHE", {})`
inside the three tests that need a cold cache. Delete the autouse fixture and the other
four sites. Same coverage, no eviction of a sibling worker's cache.

## F13. `tests/test_yuumi.py:273`

```python
stats = {"heal_and_shield_power_percent": 0.0}
for stat_key, buff_value in {"heal_and_shield_power_percent": 8.0}.items():
    stats[stat_key] = stats.get(stat_key, 0.0) + buff_value
assert healing_reduction.heal_and_shield_power_factor(stats) == pytest.approx(1.08)
assert "heal_and_shield_power_percent" in inspect.getsource(
    healing_reduction.heal_and_shield_power_factor)
```

No value, three ways. The middle block re-implements `_apply_stat_buff_ultimates`' fold
inside the test and then asserts a pure function of the result, so nothing under test
runs. The first assertion repeats the same call with the same number two lines earlier.
The last is an `inspect.getsource` substring check, which CLAUDE.md flags as unreliable
while another process edits `src/`. The test's stated purpose is to prove a sentence in a
retired receipt was wrong, which is a docs claim, not a behaviour.

Proposal: delete. The one live fact, `heal_and_shield_power_factor({...: 8.0}) == 1.08`,
belongs in the healing tests once.

## F14 to F17. Small deletion freezes and constant pins

- `test_rengar_ferocity_ledger.py:469` asserts `not hasattr(state, "apply_damage")` and
  `"note_dot"`, two methods that were never written. The rest of the test, the freeze
  boundary at 10.0 against a re-armed 15.0, is real. The same test reaches the private
  `state._materialize_expiries`, which wants a public seam if a test is going to drive it.
- `test_samira.py:59` asserts `not hasattr(samira, "MODULE_COVERAGE")`. The next line
  already reads the derived contract, which is the fact that matters.
- `test_static_data.py:77,78,92` grep `app.js` and two build scripts for absent strings,
  `mergeItemCoverage`, `backendAvailable`, `'"--patch", default="'`. The snapshot shape
  and the patch stamp in the same file are worth keeping.
- `test_rotation_resolver.py:333` asserts a three-entry dict literal equals the module
  constant it was copied from. The sibling `test_each_pinned_slot_still_fans_its_edges` is
  the real check. This one forbids the table shrinking, which the docstring names as the
  desired direction.

## F18. Tests that never run here

`tests/test_wiki_refresh.py` marks 6 of its 12 tests `@posix_lock`,
`skipif(os.name != "posix")`, and the launchd and `plistlib` tests need macOS. One spawns
a child that calls `time.sleep(60)`; the parent bounds it with a 10-second selector, so
wall-clock cost is capped, but the child is left to be killed.

22 `pytest.skip` sites in the slice depend on the gitignored
`data/bin/characters/*.bin.json` cache, so 10 champion evidence files skip on any machine
without it, including CI. `tests/conftest.py:34` argues deselection over skip for exactly
this reason, because `pytest.skip` prints green. The game-file skips do not follow that
ruling.

Proposal: keep the tests. Make the game-file skips visible the way conftest's D-22 ruling
does, deselect plus a session report of how many evidence checks did not run, so green
never quietly means the binary evidence was never read.

## F19. Remaining un-parametrized copy-paste

74 normalized-duplicate bodies were detected in the slice, identical after stripping
docstrings, comments, and string and numeric literals. Excluding F1 and F8, the largest
groups:

| File | Tests | Copies | Lines collapsible |
|---|---|---|---|
| `test_vayne.py` | `test_q_rank5_damage_reference`, `q_rank1`, three `q_cooldown_*` | 5 | 55 |
| `test_vayne.py` | `r_buff_increases_q_damage` and `_e_damage`; `r_rank1_bonus_ad` and `rank3` | 2 + 2 | 37 |
| `test_vayne.py` | `w_rank5_damage_per_hit_reference`, `w_rank1_per_hit` | 2 | 11 |
| `test_state_lifecycle.py` | `gate_is_per_source_slot`, `gate_only_applies_to_declared_packets`, `interval_boundary_is_inclusive` | 3 | 30 |
| `test_zeri_p_execute_range.py` | `executes_below_threshold`, `at_exact_threshold_equality`, `zap_damage_counts_toward_threshold` | 3 | 25 |
| `test_vladimir_e_charge_time.py` | `zero_charge`, `half_charge`, `full_charge` | 3 | 14 |
| `test_redemption_packet.py` | `validation_rejects_above_max`, `negative`, `non_finite` | 3 | 34 |
| `test_rune_paths_*.py` | four groups of "discloses" and "matches no other rune" | 2 to 4 each | 45 |
| `test_rumble.py` | `a_fight_that_never_fills_the_bar_prices_neither_half`, `an_autos_only_fight_never_overheats` | 2 | 17 |
| `test_survival_kernel.py` | `taric_roster_...`, `rakan_q_..._compiled_walk_equals_receipt_walk` | 2 | 20 |

Low value: each group exercises one path with different input rows. Written long-hand they
cost lines and hide the shared claim.

Proposal: one `@pytest.mark.parametrize` per group. No coverage is lost and the row id
names the failing input.

## Helper modules under `tests/`

All 20 are used. None duplicates a helper in `src/`. No unused fixtures were found in the
slice; 11 apparent hits were `@pytest.fixture(name=...)` false positives and all resolve.

| Module | Lines | Users | Verdict |
|---|---|---|---|
| `conftest.py` | 413 | session | Keep. Owns the `TESTING` session flag, `_process_state_is_given_back` for issue #263, six item fixtures, `parse_at`, `attacker_stats`, `fight`, and D-22 deselection. |
| `coverage_resolver.py` | 1617 | 8, including `src/calculator/coverage_evidence.py`, `item_coverage.py`, `scripts/rename_evidence.py` | Keep. Read by `src/`, so it is not test-only. |
| `kernel_fixtures.py` | 441 | 3 | Keep. |
| `view_purity.py` | 401 | 1, `test_program_structure.py` | Keep. One user, but it is the AST engine behind the view-purity gate. |
| `cc_review.py` | 210 | 173 | Keep. The highest-leverage helper here. F1 and F6 exist because callers duplicate around it. |
| `support_effect_fixtures.py` | 207 | 3 | Keep. Calls `_declared_authorities.cache_clear()` at 53 and 58, the same hazard as F12, but bracketed so it restores. `monkeypatch` is cleaner. |
| `coverage_truth.py` | 123 | 10 test files, `scripts/coverage_status.py`, 2 `src/` modules | Keep. |
| `process_state.py` | 108 | 2, `conftest.py` and `test_process_state_guard.py` | Keep. Named in CLAUDE.md as the watched-surface table. |
| `row_review.py` | 93 | 46 | Keep. |
| `kernel_coverage.py` | 87 | 2 | Keep. |
| `rider_probe.py` | 56 | 12 | Keep. |
| `ability_math.py` | 43 | 12 | Keep. |
| `parse_stats.py` | 42 | 11 | Keep. |
| `survival_probe.py` | 34 | 23 | Keep. |
| `app_config.py` | 31 | 42 | Keep. Its docstring is the clearest account of the `PROPAGATE_EXCEPTIONS` trap in the repo. |
| `committed_bytes.py` | 24 | 4 | Keep. Owns the CRLF against LF manifest hashing quirk. |
| `engine_source.py` | 23 | 3 | Keep with a caveat. It exists only to serve source-text assertions. If `test_teemo_*`, `test_tristana_*`, and `test_udyr_*` move to behaviour checks, this module goes with them. |
| `item_probe.py` | 16 | 10 | Keep. |
| `game_binary.py` | 16 | 6 | Keep. |
| `__init__.py` | 0 | n/a | Keep. |

## Order of work

1. F1 and F6. One codemod, about 860 lines gone here and 1,200 tree-wide, and the roster
   invariant lands in the file that owns it. Bulk repetitive work, so it gets a script.
2. F2. 310 lines, and it ends a class of false failures on every frontend edit.
3. F3 and F4. 572 lines of self-declared mirrors of other suites.
4. F12. A live defect against a documented trap. No lines, real cost.
5. F7, F5, F10. Retire the campaign closeouts before the next refactor trips on them.
