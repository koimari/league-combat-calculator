# Slop audit: useless and low-value tests, slice tests/test_[j-p]*.py

Scope: 135 files, 59,847 lines, 2,438 test functions.
Method: AST scans for dead names, duplicate bodies, assert-free tests and
oversized units, plus grep candidate lists per category, then reading each
candidate. Read-only. Nothing in the tree changed.

## Counts per category

| # | Category | Candidates | Judged low value | Est. lines |
|---|---|---|---|---|
| 1 | Asserts a removal or an absence | 31 grep hits | 14 tests, 1 whole file | 330 |
| 2 | Pins source text: getsource, ast, read_text of src/js/md | 31 files, 118 sites | 34 tests | 700 |
| 3 | Tautology, or assertion on the fixture | 12 | 6 | 110 |
| 4 | Duplicates | 12 exact-body groups, 2 structural families | 12 groups | 1,430 |
| 5 | One-off campaign residue | 15 p-named files, 13 Unchanged/Parity classes, 13 regression_surface funcs | 26 blocks | 1,520 |
| 6 | Skips, dead fixtures, dead helpers | 7 skips, 5 dead names | 5 dead names, 3 stale xfail notes | 45 |
| 7 | Oversized files over 1500 lines | 6 | 3 | 2,330 relocatable |
| 8 | Shared state or wall clock | 6 | 4 | 25 |

Totals: about 2,960 lines deletable and about 4,070 lines relocatable, out of
59,847 in the slice. That is roughly 12% of the slice.

## Summary table

| # | Finding | File::test | Cat | Lines | Proposal |
|---|---|---|---|---|---|
| F1 | Closeout blocks re-pin what golden_baseline.json already pins | 10 files, see detail | 5 | 1,172 | Delete. The golden gate owns it |
| F2 | 2,330-line frozen site matrix inside a test file | test_literal_defaults.py | 7 | 2,330 | Move to a baseline file beside scripts/literal_defaults.py |
| F3 | Two Fimbulwinter claims re-asserted per champion, two full fights each | 28 files, 131 tree-wide | 4 | 170 | Parametrize once in test_module_cc_census.py |
| F4 | JS, CSS and markdown substring pinning in Python tests | test_p5_ux, test_p1a_onboarding, test_program_views, test_p0a/b/d, test_p1b | 2 | 630 | Delete the prose bingo. Keep one node --check |
| F5 | Whole file asserting a blocker's sources still say nothing | test_milio_fired_up_blocker.py | 1, 5 | 180 of 234 | Keep 1 tripwire, move 2, delete the rest |
| F6 | Byte-identical bodies under different names | 5 groups | 4 | 90 | Delete the copy. One is mislabelled |
| F7 | 280 lines of campaign docstring plus four "today" pins | test_olaf_r_cleanse, test_milio_r_cleanse | 5 | 350 | Cut docstrings under 25 lines, delete the pins |
| F8 | 30 champions' tests filed under campaign batch names | test_p1_review_1/2/3.py | 5 | 1,742 | Move each champion into its own test_<champion>.py |
| F9 | Five tests per case, each re-running one call for one field | test_known_good.py | 3 | 90 | Collapse to one stats test per case |
| F10 | Three tests asserting one fact, plus a stale xfail note | test_ksante_r_atomizer.py | 4, 6 | 45 | Keep one, fix the module docstring |
| F11 | Dead module-level names | 5 sites | 6 | 40 | Delete |
| F12 | 15 parametrize rows that take the same branch | test_keystone_audit.py::test_unexposed_keystones_reject_any_option | 4 | 20 | Derive the rows from the catalog |
| F13 | cache_clear on a production memo, and a wall-clock cap | test_program_views, test_optimizer | 8 | 25 | Monkeypatch the table. Delete the clock cap |
| F14 | A test asserting its own source file's text | test_patch_update.py::test_this_file_injects_rather_than_patching_module_attributes | 2, 3 | 10 | Delete |
| F15 | Asserts a champion module's docstring contains two strings | test_jayce_w_mana_restore.py:165 | 2 | 8 | Delete the source read |
| F16 | Two tests asserting a hand-listed set is empty | test_pair_preview.py:292, :326 | 1, 3 | 60 | Merge into one derived check |
| F17 | Regex over inspect.getsource, and a cwd-relative source read | test_participant_timeline.py:5538, :5883 | 2 | 40 | Drop the regex. The next assert proves it |
| F18 | "PIdx" not in text over every kernel file | test_program_identity.py:155 | 1, 2 | 12 | Fold into the import-direction gate |
| F19 | Parametrized pairs with identical bodies | test_mikael_packet, test_muramana_shock_lockout | 4 | 45 | Merge the rows into one test |

Asides, off-task but worth a look. Four tests read repo files through
cwd-relative paths and only pass from the repo root: test_jayce_w_mana_restore.py
:167, test_mel_searing_brilliance.py:67, test_naafiri_pack.py:74 and
test_participant_timeline.py:5888. test_participant_timeline.py imports two
symbols twice under two names, roster_program and _roster_program, survival and
_survival_view. One test's name contradicts its own assertion, F6a below.

## Detail, ranked by payoff

### F1. Campaign closeout blocks, 1,172 lines, category 5

Ten files carry a terminal section whose stated purpose is that a past campaign
did not move anything outside its own slice. They are named for it.

| File | Block | Lines |
|---|---|---|
| test_jayce_form_transition.py | TestP4JParseParity 459, TestP4JScoreParity 970, TestP4JUnchangedBoundaries 1010, TestP4JRegressionSurface 1126 | 222 |
| test_olaf_r_cleanse.py | TestModeParity 2123, TestUnchangedBoundaries 2175, and the 25-line pytest command comment at 2285 | 178 |
| test_ksante_w_resistance.py | TestUnchangedBoundaries 1099, TestScoreReceiptParity 1207 | 176 |
| test_milio_r_cleanse.py | TestModeParity 1727, TestUnchangedBoundaries 1800 | 168 |
| test_maw_compiled_parity.py | 5 regression_surface funcs at 1346, 1367, 1391, 1429, 1444 | 128 |
| test_knights_vow_compiled_parity.py | 5 regression_surface funcs at 1438, 1486, 1500, 1525, 1536 | 99 |
| test_mundo_e_reset.py | TestScoreReceiptParity 753, TestUnchangedBoundaries 782 | 76 |
| test_muramana_packet.py | TestScoreReceiptParity 905 | 59 |
| test_jayce_w_mana_restore.py | test_p112_existing_regression_surface_invariants 809 | 35 |
| test_jaksho_compiled_parity.py | 3 regression_surface funcs at 1051, 1067, 1079 | 31 |

Why they bring no value. The Unchanged halves assert per-slot damage, cooldowns
and mana for one champion. That is what scripts/golden_baseline.json pins. I
checked the file: registered_champion_fights holds all 173 champions including
Olaf, Milio, K'Sante, Jayce and Dr. Mundo, and champion_baselines holds 173 more.
CLAUDE.md makes golden_snapshot.py compare the gate that a pure refactor shows
zero diffs on, so these blocks are a second, hand-maintained, partial copy of a
gate that is already total. Two of them admit it. The docstring of
test_regression_surface_timeline_redirect_math_stays_green reads "Mirrors
test_participant_timeline.py ~3512".

The ScoreReceiptParity and ModeParity halves assert full-walk versus score_only
byte identity. architecture.md names the owner of that property: cache-vs-no-cache
and compiled-walk-vs-receipt-walk equivalence are pinned by
tests/test_participant_timeline.py and tests/test_optimizer.py. Per-champion
copies of a general property are duplicates of it.

Proposal: delete all ten blocks. If score parity is wanted per champion, it is one
parametrized test over registered_champion_names in one file, not nine hand-written
copies. Each deletion also removes several full calculate_payload fights from the
suite.

### F2. test_literal_defaults.py holds 2,330 lines of data, category 7

The file is 2,442 lines. Six tests live at lines 2381 to 2442. Everything above is
a frozen tuple matrix, ROW_READS and its siblings, one row per surviving literal
default, sorted into buckets by campaign decision code.

The ratchet is real value. CLAUDE.md rule 5 cites the 3x Statikk Shiv
overstatement that a literal fallback hid, and
test_the_frontier_only_ever_moves_towards_the_covered_set is a genuine
monotonicity guard. The problem is the home. The repo already has the right
pattern: .sightline-baseline is a data file beside its tool, merged by union, with
the tool owning the format. A 2,330-line Python literal inside tests/ cannot be
regenerated by the script that produces it, conflicts on every parallel merge, and
makes the file the second largest in the slice for reasons unrelated to testing.

Proposal: scripts/literal_defaults.py gains a baseline writer, the six tests read
the baseline. Net effect on tests/ is 2,330 lines out. A relocation, not a
deletion.

### F3. The per-champion Fimbulwinter pair, 170 lines in slice, 131 files tree-wide, category 4

28 files in this slice, test_jax through test_pyke, each end with the same two
claims with only the champion name changing:

```python
assert cc_review.unreviewed_ability_slots("<Champion>") == []
coverage = cc_review.fimbulwinter_coverage("<Champion>")
assert coverage["complete"] is True
assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
```

Seven bodies are byte-identical: test_janna:45, test_jarvan_iv:445, test_jhin:54,
test_kaisa:610, test_kalista:59, test_karma:50 and test_ksante:61, all named
test_a_timed_fimbulwinter_fight_is_fully_certified.

fimbulwinter_coverage runs a full calculate_payload at level 18 with Fimbulwinter,
and unreviewed_ability_slots runs a separate run_fight. That is two full fights per
champion, 56 in this slice and about 262 tree-wide, for a claim that is a roster
census by construction.

tests/test_module_cc_census.py already exists for this shape, already imports
cc_review, and already parametrizes
test_a_live_declaration_reaches_the_fight_or_is_pinned_as_uncarried over every
registered champion through cc_review.fight_ledger. Its docstring states the
principle: the census is the test because the failures it guards are counts.

Proposal: one parametrized test over _CHAMPION_MODULES in test_module_cc_census.py.
Delete the 28 per-champion copies here and the 103 in the sibling slices. The
runtime win is larger than the line win.

### F4. JS, CSS and markdown substring pinning, 630 lines, category 2

test_p1a_onboarding.py, 328 lines, about 150 low value. It asserts exact
JavaScript source substrings, including a source comment at line 190, an
addEventListener spelling at line 165, and the absence of window.confirm and
window.location.reload at lines 179 and 180. A comment is not behaviour, a handler
spelling is not behaviour, and the absence checks are category 1. Any honest
rename turns this red with nothing broken.

test_p5_ux.py, 448 lines, about 200 low value. Same shape over app.js and
style.css, plus two hand-listed absence loops at lines 371 and 412 that freeze the
2026-08 removal of Quick mode forever. test_app_js_posts_json_through_one_helper,
asserting source.count of the POST literal equals 1, is the one here with a real
invariant behind it, and even that is a lint rather than a test.

test_program_views.py lines 645 to 755, about 110 lines. Seven tests read
static/js/app.js and static/css/style.css inside the file that owns the Python
view layer. test_the_page_has_a_rule_for_what_a_refusal_looks_like asserts a CSS
selector string is present. These belong to the browser surface, not to
program/views, and they are part of why the file is 1,041 lines.

Doc-word bingo, about 160 lines. test_p0d_runbook.py is 82 lines and the whole
file asserts that markdown files contain given headings and words.
test_p0a_deploy.py:465 asserts docs/deploy-runbook.md contains "Neon", "Upstash"
and "Rollback". test_p0b_ops.py:423 and :437 do the same for two more docs.
test_p1b_metrics.py:681 asserts docs/beta-metrics.md contains "25%", "20" and
"72". A doc containing the word "Rollback" is not a doc with a rollback procedure.
The test cannot tell the difference, and a heading rename breaks it.

Proposal: delete the prose bingo. Keep exactly one node --check, which currently
exists twice, see F6e. If the one-POST-helper and no-engine-formulas-in-app.js
rules matter, they are a script in scripts/ run with the other tree gates, not 600
lines of pytest.

### F5. test_milio_fired_up_blocker.py, 180 of 234 lines, categories 1 and 5

A whole file whose stated purpose is to assert the absence of missing terms. Most
of it reads a fixture and checks the fixture:

- test_no_cached_leveling_row_carries_the_burst_values asserts first_values equals [10, 1.67], then asserts 7 is not in first_values. The second assert is implied by the first.
- test_ddragon_carries_only_a_numberless_blurb asserts "7" and "%" are absent from a blurb.
- test_no_cached_source_states_the_level_breakpoints checks four phrases are absent from three JSON dumps.
- test_assumptions_record_that_the_dedup_blocker_is_retired asserts two English phrases appear in a module's ASSUMPTIONS list. Its docstring says its job is to stop a later session citing an old reason. That is a note to a reader, not a behaviour.
- test_p_prices_the_sourced_half_only asserts all five slots are "modeled", which the module contract validator already enforces at import.

The genuinely useful piece is the tripwire: if a patch pull starts publishing the
7/11/15 breakpoints, somebody should be told. One test does that,
test_the_cached_description_still_states_the_bracket_as_prose.
TestTheDedupDependencyIsSatisfied's two tests exercise _empower_window_procs for
real and belong in the empower-window suite.

Proposal: keep 1 tripwire, move 2, delete the rest. About 180 lines.

### F6. Byte-identical test bodies, 90 lines, category 4

An AST scan found 12 exact-body duplicate groups in the slice. Five are real
duplicates rather than differing parametrize rows.

F6a, a probable bug rather than slop.
test_knights_vow_compiled_parity.py:1238::test_enemy_holder_poisons_the_compiled_context_and_falls_back
is byte-identical to :1285::test_roster_holder_compiles_after_certification. The
name says the context is poisoned. The body asserts ctx.uncompilable is False and
ctx.panels, and its own inline comment at 1277 says the capability scan does not
poison the context. The name is wrong. Delete one and keep the other under the
honest name. If the poisoning case was meant to be covered, it is not covered
today.

F6b. test_jaksho_compiled_parity.py:868::test_compiled_capability_scan_is_clean_for_jaksho
is byte-identical to :883::test_compiled_tuple_ledger_fight_fails_closed_with_stack_metadata,
whose docstring ends with a claim that it xfails. No xfail marker exists anywhere
in the slice. Delete the second, 16 lines.

F6c. test_orianna.py:108::test_e_rank5_excludes_shield_and_resists is
byte-identical to :128::test_default_deals_damage. Delete the second. Its sibling
test_disabled_is_zero_damage_utility_cast is the real test of the option and
stays.

F6d. test_knights_vow_compiled_parity.py:1486 and :1500 are byte-identical to
:737 and :849 in the same file. They are the F1 copies.

F6e. test_p1a_onboarding.py:317::test_node_check_passes_for_app_js is
byte-identical to test_p5_ux.py:437::test_node_check_passes_for_app_js. Keep one,
in whichever file survives F4.

### F7. Two 2,000-line TDD matrix files, 350 lines, category 5

test_olaf_r_cleanse.py is 2,305 lines and test_milio_r_cleanse.py is 1,913. They
open with 150-line and 130-line docstrings that are session narrative rather than
contract: "CURRENT RUNTIME FACTS (verified before pinning)", a paragraph about
what a coordinator will most likely wire, and 14 numbered contract sections keyed
to a brief. CLAUDE.md caps handoffs at 400 words and says docs carry current state
only. These two docstrings run to about 2,800 words of history.

Inside, four tests pin today's answer as an answer:
test_r_rank0_still_books_a_cast_today at 836, test_r_rank0_no_cleanse_immunity_stat_rows_today
at 848, test_no_r_stat_rows_in_app_fight_today at 1607, and
test_r_no_typed_timing_option_today at 992. Each freezes a behaviour the same
docstring calls a completion gap, so the next honest fix must delete a green test
to land.

_AWAIT at line 218 is dead. No pytest.mark.xfail exists anywhere in the slice, so
the "genuinely-absent mechanics are xfailed" contract the docstring describes no
longer exists.

Proposal: cut both docstrings under 25 lines naming the sourced contract. Delete
the four "today" pins and _AWAIT. Delete the 25-line pytest command comment at
olaf 2285. The behavioural body of both files, cleanse truncation, immunity window
and suppression denial, is real and stays.

### F8. Champion tests filed under campaign batch names, 1,742 lines, category 5

test_p1_review_1.py at 594 lines, test_p1_review_2.py at 579 and
test_p1_review_3.py at 569 hold per-champion tests for about 30 champions: Akshan,
K'Sante, Locke, Malphite, Nasus, Rek'Sai, Seraphine, Sylas, Vex, Yasuo, Briar,
Kindred, Lux, Mel, Neeko, Riven, Skarner, Varus, Vladimir, Zac and more.

The tests are good. Expectations are recomputed from cached leveling rows and
driven through /api/calculate. The failure is placement. test_nasus.py exists at
85 lines and does not hold the Soul Eater lifesteal tests. Those are at
test_p1_review_1.py:372. CLAUDE.md says a task description should resolve to the
right file in a few greps, and "Nasus healing" resolves to the wrong one.

Proposal: move each champion's tests into its own test_<champion>.py and delete
the three batch files. Zero net line change, a large navigation win, and three
file names that encode a forgotten campaign phase go away.

### F9. test_known_good.py, 90 of 305 lines, category 3

Three test cases, each with five separate test functions: test_total_hp,
test_total_ad, test_total_ap, test_armor and test_magic_resist. Each re-runs the
identical calculate_total_stats call and asserts one key of the result. Fifteen
calls where three would do, and a failure in any one reports the same root cause.

The module docstring also narrates a deletion: a previous companion file was
deleted in a July 2026 refactor campaign. Current state only.

Proposal: one test_stats per case asserting the whole dict, and three docstring
lines. About 90 lines. The file keeps its real value, the hand-validated
game-client anchors.

### F10. test_ksante_r_atomizer.py asserts one fact three times, 45 lines, categories 4 and 6

- test_scalar_row_as_observed_today at 110 asserts values equal [0.5], one evidence receipt from effects[0], and a pinned hash.
- test_scalar_must_not_claim_multiple_durations at 123 asserts the evidence has length 1 and the receipt starts with effects[0]. A subset of the above.
- test_typed_lookup_scalar_query_pinned_as_observed at 207 asserts values equal [0.5] and the same pinned hash again.

The module docstring at line 14 still says the contract assertion is xfailed until
a coordinator lands a dedup fix. The fix landed, there is no xfail, and the third
test's docstring still calls the current value a misleading union while asserting
it is correct.

Proposal: keep test_scalar_must_not_claim_multiple_durations, which is stated as a
contract rather than as an observation. Delete the other two. Correct the module
docstring.

### F11. Dead module-level names, 40 lines, category 6

AST scan, cross-checked against the whole tests/ tree.

| Site | Lines |
|---|---|
| test_ksante_w_resistance.py:257 _resist_term | 22 |
| test_p1b_metrics.py:94 _add_share | 12 |
| test_olaf_r_cleanse.py:218 _AWAIT | 1 |
| test_olaf_r_cleanse.py:227 _R_SIZE_PERCENT | 1 |
| test_milio_r_cleanse.py:169 _R_CAST_TIME | 1 |
| test_p1b_metrics.py:45 WEEK | 1 |

test_patch_update.py:114 real_tree_tripwire also scanned as unused. It is an
autouse fixture, it is live, and it is a good test. Keep it.

### F12. Parametrize rows that take the same branch, 20 lines, category 4

test_keystone_audit.py:145::test_unexposed_keystones_reject_any_option takes 15
hand-listed keystone names and asserts each raises "Unknown option". Every row
takes the same branch: the name is not in the two-member exposed set. That set is
already asserted two tests above in
test_options_exist_only_for_engine_consumed_state, so the list is a hand-maintained
duplicate of a fact the module publishes, and a new keystone escapes it silently.

Proposal: derive the rows from the rune_effects catalog minus
keystone_input_options_meta, or collapse to one representative row beside the
set-equality test that already exists.

### F13. Shared state and wall clock, 25 lines, category 8

test_program_views.py:1034 and :1041 call
capability.declared_view_tags.cache_clear on a production lru_cache. CLAUDE.md is
explicit: never clear a process-wide cache in a test, it passes and silently costs
every later test the warm cache. Under pytest -n auto this evicts a sibling
worker's cache. Proposal: monkeypatch the whole CAPABILITIES table to a fresh
object derived from the table, the pattern CLAUDE.md prescribes.

test_optimizer.py:819::test_optimizer_completes_under_15_seconds asserts
optimization_time_ms is under 15000. Its docstring records that the cap was 8 s
and was recalibrated to 15 s because the CI runner multiplier moved from 2.2x to
3.4x. A gate that gets loosened whenever it fires is not a gate, and CLAUDE.md
puts perf numbers in benchmarks.md with the bench scripts explicitly not gates.
Proposal: delete. scripts/bench_optimize_build.py owns this.

test_optimizer.py:806::test_optimizer_positive_damage runs a full 5-slot
optimize_build, one of 35 such calls in that file, to assert the total is above
zero. The neighbouring tests make that claim implicitly by asserting actual item
picks. Delete.

test_ledger_projection.py:131 and test_program_walk.py:276 rebind module
attributes by hand inside try/finally instead of monkeypatch.setattr. They restore
correctly today, but they are the shape issue #263 closed and the autouse guard
now catches. Convert to monkeypatch.

test_live_amp.py:442 and :447 clear a test-local lru_cache. Lower risk, the memo is
local to the file, but it costs the rest of the file its warm cache. Scope the memo
per test instead.

### F14. A test asserting its own source file's text, 10 lines, categories 2 and 3

test_patch_update.py:370::test_this_file_injects_rather_than_patching_module_attributes
reads Path(__file__) and asserts two strings are absent, assembling the needles at
runtime so the test does not match its own source line. It tests the test file, not
the code. Proposal: delete, or make it a rule in the existing lint gate if the
convention matters.

### F15. Asserting a module's docstring text, 8 lines, category 2

test_jayce_w_mana_restore.py:165 reads src/calculator/champions/jayce.py through a
cwd-relative path, with an __import__ call inside the test body, and asserts two
strings appear in the docstring. The sourced fact it guards, the cached leveling
row, is asserted correctly four lines above. Delete the source read.

### F16. Asserting a hand-listed set is empty, 60 lines, categories 1 and 3

test_pair_preview.py:292::test_the_retired_routing_family_has_no_preview_to_double_count
and :326::test_the_retired_shred_family_has_no_preview_to_double_count. Each opens
with a 20-line docstring, then hand-lists three mechanic names and asserts they
intersect nothing. The file's own helper _one_dropped_preview_mechanic shows the
right pattern, and its docstring says so: reading the difference off
walk_repriced_mechanics rather than naming a mechanic is what keeps these cases
pointed at dropping the day another family retires. The two retired-family tests
do the opposite.

Proposal: one derived check, that every RiderDelivery capability declares no
_preview twin, covers both families and every future one.

### F17. test_participant_timeline.py source reads, 40 lines, category 2

:5538::test_support_attributes_match_the_profile_lookup_source runs a regex over
inspect.getsource and asserts the captured variable names. The next two lines
assert the real invariant directly, that _SUPPORT_ATTRIBUTES equals the union of
_SHIELD_ATTRIBUTES and _HEAL_ATTRIBUTES. The regex half only pins how the function
happens to be spelled. CLAUDE.md also flags inspect.getsource tests as producing
phantom failure sets when anything else edits src/ concurrently. Drop the regex,
keep the set equality.

:5883::test_the_composer_never_calls_itself parses a cwd-relative path to assert
the module contains no recursive call. A recursion guard in the composer would be
shorter and total.

### F18. Substring absence over every kernel file, 12 lines, categories 1 and 2

test_program_identity.py:155::test_the_kernel_does_not_import_the_logical_identity_module
walks every file under survival/ and asserts two substrings are absent. A substring
scan false-positives on any identifier containing PIdx and false-negatives on an
aliased import. test_program_structure.py already owns the program to survival
direction as an AST import check. Fold this in there.

### F19. Parametrized pairs with identical bodies, 45 lines, category 4

test_mikael_packet.py:429::test_validation_rejects_values_above_max and
:452::test_validation_rejects_negative_values have identical 22-line bodies. Only
the parametrize rows differ, 30.5/31/100 against -0.5/-1/-30, and both assert the
same message. One test with six rows.

test_muramana_shock_lockout.py:238::test_missing_identity_withholds_proc and
:260::test_malformed_identity_withholds_proc have identical one-line bodies and
five rows between them. One test with five rows.

## Kept deliberately

These looked like candidates and are not.

- test_program_structure.py TestViewPurity. A lint with a reproducible red on both arms, test_a_sum_inside_a_view_fails_the_check and test_a_sum_one_import_away_from_a_view_fails_it_too, and a committed unresolved-callee boundary. This is what a source-scanning test should look like.
- test_module_cc_census.py. Its docstring states the failure class it guards is a count, invisible per module and obvious per roster. It should absorb F3.
- test_process_state_guard.py. Tests the issue #263 guard by driving real leaks and checking the restore, including the absent-versus-None distinction that made the leak possible.
- test_prose_lint.py, test_public_response.py, test_outcome_state.py, test_live_amp.py apart from the cache_clear calls, and test_kogmaw_trace_fixture.py. All test behaviour against a regenerable fixture or a named refusal.
- test_phase0_sentinels.py, 893 lines. The seven test_the_population_is_..._and_is_not_empty tests assert facts about the fixture, category 3 by the letter, but the docstring names the reason, D-26, a sentinel green over an empty set proves nothing, and the guard is correct. The file name should lose phase0. The content stays. command_sweep runs every registered champion through a fight, so it is one of the slice's most expensive fixtures.
- test_program_structure.py TestTheAllocationBudget reads a ceiling out of docs/receipts/campaign-fingerprints.json and measures allocation live. Borderline: it is a perf ratchet inside pytest, which CLAUDE.md otherwise keeps in benchmarks.md. Worth a decision, not a deletion.

## Skips and xfails

Seven pytest.skip sites, all conditional on a genuinely absent local prerequisite:
local game-file evidence, node, jq, or a tmp_path inside a git repo. All fine.

Zero pytest.mark.xfail decorators in the slice. Three module docstrings still
describe tests as xfailed: test_olaf_r_cleanse, test_jaksho_compiled_parity and
test_ksante_r_atomizer. The stale prose is the finding, not the skips.
