# Slop audit: low-value tests in tests/test_[a-d]*.py

Scope: 133 files, 67,536 lines, about 2,900 test functions, plus `tests/conftest.py`. Read-only pass. No tracked file changed.

## Counts per category

| # | Category | Count in slice | Removable lines |
|---|---|---|---|
| 1 | Asserts something was removed or does not exist | 19 tests in 7 files, plus 5 more via `== []` source scans | ~180 |
| 2 | Pins source text via `read_text`, `ast`, `glob`, `inspect.getsource` | 127 tests in 35 files | ~1,250 |
| 3 | Tautologies: literal equals literal, fixture assertions, empty loops | 12 `reason.strip()`, 9 enum and version echoes, 6 vacuous loops | ~150 |
| 4 | Duplicates | 3 byte-identical bodies, 28 cloned coverage tests, 4 AST and execution pairs | ~300 |
| 5 | Campaign residue: issue, phase, and receipt-JSON bookkeeping | 4 whole files, 17 tests in `test_behavior_frontier.py` | ~1,100 |
| 6 | Dead skips, dead setup, unused fixtures | 2 pending-kernel scaffolds over 72 call sites, 1 dead `XFAIL` binding, 2 unused fixtures | ~60 |
| 7 | Oversized files, over 1500 lines | 7 files | see notes |
| 8 | Mutates shared process state | 4 tests clearing process-wide caches | ~10 |

Total removable, de-duplicated across categories: **about 2,300 lines, 3.4% of the slice.**

Category 2 dominates. 127 tests read `src/`, `static/js/`, `scripts/` or `.github/` as text and assert on its shape. About half guard a real failure class and belong in `scripts/` as a lint. The other half snapshot the shape a past commit left.

## Summary table, ranked by payoff

| # | Finding | File and test | Cat | Lines | Proposal |
|---|---|---|---|---|---|
| 1 | `app.js` substring assertions | `test_app.py`, 26 tests plus 34 asserts in 8 more | 2 | ~390 | Delete. Replace with a browser harness like `test_scoreboard_vision.py` |
| 2 | Deferral gate over an empty population | `test_behavior_frontier.py`, 17 tests, L322 to L1250 | 5 | 383 | Delete with the stage and deferral machinery in `scripts/behavior_frontier.py` |
| 3 | Golden allowlist that is vacuous on main | `test_coupled_golden_allowlist.py`, whole file | 4, 5 | 235 | Delete. `golden_snapshot.py compare` is the gate |
| 4 | Prose-to-predicate binding for one sentence | `test_coverage_reason_source_assertion.py`, whole file | 2, 5 | 374 | Reduce to one behavioural test on the published payload |
| 5 | Eight retired registries, plus tests of the freeze's matcher | `test_coverage_claims.py::test_the_eight_retired_registries_*`, 3 tests | 1, 3 | 162 | Delete all three and both helpers |
| 6 | Per-champion clone of one roster-wide check | 28 tests across 27 champion files | 4 | 197 | Parametrize once in `test_module_cc_census.py` |
| 7 | D-85 statement-layout gates | `test_cast_dependency.py`, 5 tests, L760 to L846 | 2 | 83 | Delete. `test_only_declaring_modules_reach_a_validator` is stronger |
| 8 | Three source scans of past deletions | `test_deletion_frontier.py`, whole file | 1, 2, 5 | 95 | Delete |
| 9 | Scanner self-tests pinning other test files by name | `test_ci_evidence_parity.py`, 4 tests | 2 | 65 | Delete 4, keep the parametrized tripwire |
| 10 | Enum member echoes, plus an AST and execution duplicate | `test_ability_spec.py`, 5 tests | 3, 4 | 59 | Delete |
| 11 | Pins a refusal `Counter` the coupled golden already holds | `test_declared_zero_dispositions.py`, 2 tests | 4, 5 | 49 | Delete |
| 12 | Frontier reason tautologies, retired-registry narrative | `test_architecture.py`, 4 tests | 3, 5 | 44 | Delete 3, keep half of the 4th |
| 13 | Dead pending-kernel setup, module shipped | `test_cleanse_eligibility.py`, `test_crowd_control_immunity.py` | 6 | ~45 | Delete both scaffolds, inline 72 call sites |
| 14 | Asserts a known defect still reproduces | `test_champion_inputs.py::TestTheEscalatedDefectIsStillTracked` | 1, 5 | 33 | Fix the Akshan bug, delete the class and the receipt |
| 15 | Retired-literal source scans | `test_custom_cast_order.py`, 4 tests | 1, 2, 4 | 25 | Delete 3, merge the 4th |
| 16 | Process-wide cache clears | 4 tests, 4 files | 8 | ~10 | Use an injected root or `monkeypatch` |
| 17 | Retired-symbol source scans | `test_champion_module_contract.py`, 2 tests | 1, 2 | 14 | Delete |
| 18 | Exact duplicates | `test_amumu.py`, `test_capabilities.py` and `test_aura_arming.py`, the two Ashe files | 4 | ~30 | Delete one of each pair |
| 19 | Meta-test counting the tests in its own file | `test_coverage_claims.py::test_the_mutation_suite_is_nine_*` | 3 | 20 | Delete |
| 20 | Pins the CI workflow's argv | `test_coverage_claims.py::test_ci_runs_pytest_with_no_*` | 2 | 33 | Fold into `test_ci_checkout.py` |
| 21 | Unused fixtures, dead `XFAIL`, stale xfail doctrine | `conftest.py`, `test_ashe_q_active_window.py`, 3 docstrings | 6 | ~12 plus prose | Delete |
| 22 | `not hasattr` one-liners | `test_coverage_evidence.py`, `test_cp20_items.py` | 1 | 4 | Delete the `not hasattr` line only |

## Finding detail

### 1. test_app.py greps static/js/app.js for substrings, about 390 lines

`test_app.py` lines 1027 to 2302. Twenty-six tests read `static/js/app.js`, two read `static/css/style.css`, and assert that identifiers and expressions appear in the text. Eight further tests mix these with real HTTP assertions, adding 34 more substring asserts.

Why it brings no value: the JavaScript never runs. A real regression, the right identifier passed the wrong value, passes all of them. A Prettier run, a rename, or a line rewrap fails all of them. The worst case pins a 140-character expression verbatim:

```python
# test_app.py:1052
assert (
    "setPath(levelPath, Math.max(1, Math.min(cap, "
    "Number(pathValue(levelPath)) + Number(levelButton.dataset.levelDelta || levelButton.dataset.delta || 0))));"
    in source
)
```

`test_frontend_reads_one_registry_field` at line 1846 also loops over six retired identifiers asserting each is absent, which is category 1 nested inside category 2.

Proposal: delete the 26 pure tests and the 34 substring asserts inside the mixed ones. The repo already drives a real browser under the real CSP in `tests/test_scoreboard_vision.py`, and that is where "the frontend consumes the backend receipt" belongs. The contract half survives without a browser and is already asserted by `test_capability_contract_has_a_frontend_control_and_serialization_for_every_supported_field` against `capabilities.py`. Removable: **about 390 lines**, the largest single win in the slice.

### 2. test_behavior_frontier.py gates an empty population, 383 lines

Probed this session:

```
COUNTER_4_DEFERRALS: {}          COUNTER_4_DEFERRAL_FAMILIES: ()
receipt counter_4.deferrals:  {"by_lane": {}, "rows": {}, ...}
```

Seventeen tests at lines 322, 491, and 753 to 1250 exercise the deferral, creditor, stage, and overdue machinery. With the set empty:

- `test_counter_four_defers_in_writing_what_this_phase_cannot_close` at line 753, 46 lines, iterates `block["rows"].items()` zero times and ends on `assert set(block["by_lane"]) <= {"receipt_walk"}`, which is `set() <= {...}`.
- `test_counter_four_targets_are_measured_net_of_the_deferrals` at line 801 asserts `deferred == len({})`.
- The eight "a deferral that fails the gate" reds at lines 814 to 1120 can find no row, so the file fabricates one. `_FABRICATED_DEFERRAL = "sustain/compiled_score_walk"` at lines 673 to 700 exists because, in the file's own words, the debt is discharged and the read now finds nothing. A gate whose subject left the tree tests the gate, not the tree.
- `test_counters_five_to_seven_are_not_reported_here` at line 322 asserts a dict holds exactly the four keys it holds.
- `test_the_hand_set_is_gone_and_the_fold_is_what_the_gate_reads` at line 491 rglobs all of `src/` for a string-spliced retired symbol. Its second half, fold against gate equivalence, is real. Split that out and keep it.

Proposal: delete the 17 tests, and with them `COUNTER_4_DEFERRALS`, `declared_stages`, `creditor_stage`, `campaign_range`, `completed_stages`, `_tag_first_seen` in `scripts/behavior_frontier.py`, and `docs/receipts/campaign-stages.json` and `campaign-slice-tags.json`. Keep the counter 1, 2, and 3 gate and the zero-policy frontier. Those measure live populations. Removable: **383 test lines**, plus a comparable amount of script.

### 3. test_coupled_golden_allowlist.py is vacuous on main, 235 lines

Measured this session:

```
coupled standing diffs: 0    pair standing diffs: 0
allowlisted coupled paths: 2992   pair: 2464   receipts: 48   disposition claims: 774
```

Consequences:

- `test_every_standing_coupled_diff_is_claimed_by_a_receipt` and `test_every_standing_pair_diff_is_claimed_by_a_receipt` assert `() == ()`.
- `test_a_claimed_disposition_transition_moves_no_number` loops 774 times over `if leaf not in moved: continue` with `moved` empty, so it runs zero assertions.
- `test_the_allowlist_mechanism_has_receipts_to_read` asserts the fixture exists.
- `test_an_unclaimed_leaf_turns_the_check_red` tests `unexplained()`, a two-line helper defined in the same file.
- `test_every_receipt_names_the_baseline_it_landed_against` is 48 parametrized rows all checking one JSON key against one literal, a receipt matching itself.
- `test_a_claimed_disposition_transition_names_the_leaf_it_describes` compares one receipt against another.

Even when the diff set is non-empty, a permanently growing 2,992-path exemption list checked as a subset, never as an equality, is strictly weaker than the compare gate it wraps. The baselines have been re-captured since, at commit b6462389.

Proposal: delete the file. The real gate is `python scripts/golden_snapshot.py compare scripts/golden_baseline.json`, already named in CLAUDE.md. The file also costs about 6 seconds of every suite run for no signal. Removable: **235 lines**, plus 48 files under `docs/receipts/expected-golden-diff-*.json`.

### 4. test_coverage_reason_source_assertion.py binds one sentence, 374 lines

Ten tests exist to make one published string provably true by binding it through the AST to the predicate that emits it. The string is the all-defence coverage reason on an item's coverage payload. The file frames itself as discharging a campaign amendment so the justification is not a premise nobody enforces.

Why it brings little value: the fact the sentence asserts, that every family the item declares is in the defence group, is checkable directly. Call the coverage payload for each item that publishes the claim and assert the families. Six of the ten tests are negative fixtures for the AST matcher rather than for the rule.

Proposal: replace the file with one parametrized behavioural test over the items that publish the claim. Removable: **about 330 of 374 lines**.

### 5. test_coverage_claims.py freezes eight retired registries, 162 lines

Lines 1364 to 1471.

```python
assert len(RETIRED_REGISTRIES) == 8          # literal equals literal
assert source_occurrences(RETIRED_REGISTRIES) == {}
```

`test_the_eight_retired_registries_have_no_occurrences_left` freezes a deletion forever, including in prose, so a comment that mentions `_BLOCKED_REASONS` fails it. The two tests after it, `test_the_retired_registry_matcher_reports_a_name_it_is_handed` and `test_the_retired_registry_scan_reads_the_package_it_claims_to_read`, test the scanning helper this same file defines. They are tests of a test. The 46-line `whole_identifiers` and `source_occurrences` pair exists only to serve them.

Proposal: delete all three tests and both helpers. The real invariant, that the ladder yields exactly these statuses, is held by `test_every_status_the_ladder_can_yield_is_reached_by_a_cached_item` at line 1909. Removable: **162 lines**.

### 6. Twenty-eight per-champion clones of one roster-wide check, 197 lines in slice

Every champion test file in the slice ends with the same block:

```python
assert cc_review.unreviewed_ability_slots("<Champion>") == []
coverage = cc_review.fimbulwinter_coverage("<Champion>")
assert coverage["complete"] is True
assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
```

28 instances in this slice. 133 repo-wide across 131 files. Identical assertion, identical path, differing only in the champion string. Each runs a full `calculate_payload` coupled fight. `tests/test_module_cc_census.py` already parametrizes four sibling checks over `registered_champion_names()`.

Proposal: add one parametrized test to `test_module_cc_census.py` and delete the 133 clones. Removable in slice: **197 lines**. Roughly 900 repo-wide, so flag this to the other three auditors.

### 7. test_cast_dependency.py pins statement layout, 83 lines

Lines 749 to 846. Five tests read production functions with `ast` and assert the line ordering of statements: that every `raise` in `_declared_cast_dependencies`, `_cast_dependencies`, `merge_declared_edges`, `derive_champion_rule`, and `build_packet_module` sits below an `if not <name>: return` guard, located by `_emptiness_guard_line`. The last pins whitespace-exact source:

```python
assert "if not declared:\n        return ()" in contract_source
```

`test_only_declaring_modules_reach_a_validator` at line 850, in the same class, is the behavioural half. It spies on every validator across the whole live registry and asserts only Brand, Syndra, and Zed reach one. That is strictly stronger and survives a refactor.

Proposal: delete the five AST tests and `_emptiness_guard_line`. Keep the behavioural test, minus its `assert len(registry) == 173`, a magic count that churns on every new champion. Separately, `test_it_imports_no_sibling_module` at line 203 duplicates `test_loading_it_pulls_in_no_calculator_module` at line 215, which proves the same property by executing the module. Delete the AST one. Removable: **about 101 lines**.

### 8. test_deletion_frontier.py, whole file, 95 lines

Three tests, all source scans of two past deletions:

- `test_exactly_one_dispatch_ladder_survives_in_the_kernel` runs a heuristic AST ladder detector, three or more `if` tests naming `ActionKind`, and pins the answer to `{"transitions.py:run_survival_walk"}`. An honest split of the walk fails it.
- `test_the_survival_action_carries_a_read_utility_kind` asserts `"utility_kind" in SurvivalAction._fields` and `"cleanse" in UTILITY_KINDS`. Both echo the definition.
- `test_the_utility_vocabulary_has_exactly_one_home` greps all of `src/` for the substring `"UTILITY_KINDS = "`.

Proposal: delete the file. If the one-home rule is worth keeping, it is one rule in a `scripts/` lint. Removable: **95 lines**.

### 9. test_ci_evidence_parity.py scanner self-tests, 65 lines

The core test, `test_evidence_reference_is_tracked_or_guarded`, parametrized over discovered references, guards a real failure class seen three times and should stay. The four tests at lines 360 to 431 pin other test files by name:

```python
for expected in ("tests/test_gnar_mega_gamefile.py", "tests/test_dr_mundo_passive.py", ...):
    assert expected in files
assert len(ALL_REFERENCES) >= 15
```

Renaming or deleting any of those five files breaks this module for a reason unrelated to the rule. `assert len(ALL_REFERENCES) >= 15` is a magic floor.

Proposal: delete the four. If non-vacuity matters, assert `ALL_REFERENCES` is non-empty. Better: move the scanner to `scripts/ci_evidence_parity.py` beside `literal_defaults.py` and `swing_stream_audit.py`, and keep one thin test. Removable: **65 lines**.

### 10. test_ability_spec.py echoes four enums and duplicates an import rule, 59 lines

Lines 73 to 179. Four tests assert an enum's member list equals its member list:

```python
def test_disposition_is_the_campaign_invariant(self) -> None:
    assert [member.name for member in Disposition] == ["MEASURED", "STRUCTURAL_ZERO", "WITHHELD", "STARVED"]
```

These fail only when somebody edits the enum, which is the same change that edits them. The three properties that carry weight are already asserted generically: `test_receipt_spellings_equal_their_symbols`, `test_vocabulary_is_closed`, `test_part_damage_types_is_the_damage_class_projection`, and `test_the_axis_rows_cover_every_damage_class`, which is exhaustive over `DamageClass` by construction.

`test_the_vocabulary_leaf_imports_no_sibling_module` at line 152, 27 lines of AST, is subsumed by `test_the_leaf_loads_with_no_package_around_it` at line 190, which executes the module with no package present. The file's own docstring concedes that an AST rule only approximates that. Keep `test_the_leaf_defers_no_sibling_import`, which catches function-scope imports the load cannot see.

Proposal: delete the four echoes and the module-scope AST test. Removable: **59 lines**.

### 11. test_declared_zero_dispositions.py re-derives a golden by hand, 49 lines

```python
assert collections.Counter(entry["reason"] for entry in declared) == {
    "attacker_state_blocked": 16, "trigger_event_skipped": 11,
    "outside_window": 8, "attacker_dead": 2, "target_dead": 2,
}
```

This pins per-reason counts for one coupled scenario, `cleaver_bloodsong_roster`, that `scripts/golden_coupled_baseline.json` already captures leaf by leaf. The 12-line comment above it records one re-measurement already forced by an unrelated Aatrox timing change. `test_the_outcome_ledger_is_the_receipt_walks_companion` at line 147 is an AST count of `OutcomeLedger(...)` construction sites whose docstring narrates a retired reproducer.

Proposal: delete both. Keep `test_a_refused_row_publishes_a_declared_zero`, which asserts the shape, and `test_the_serializer_can_nevertheless_express_all_four`. Removable: **49 lines**.

### 12. test_architecture.py carries reason tautologies and a retired narrative, 44 lines

- `test_every_item_name_frontier_entry_carries_a_reason` at line 292 and `test_every_frontier_entry_carries_a_reason_and_an_owner` at line 313 loop a hand-written literal dict declared 40 lines above and assert its strings are non-empty. Nobody writes `reason=""`.
- `test_the_survey_covers_more_than_the_filename_convention_it_replaced` at line 320, 21 lines, has a docstring entirely about a registry that no longer exists. Its three assertions are near-definitional. `reported <= surveyed` holds because `front_door_report` is derived from surveying `SRC_ROOT`, and `surveyed - reported` being non-empty means at least one module has a test importing it.
- `test_each_narrower_stat_surface_is_narrow_and_says_why` at line 483 is half tautology, `assert reason.strip()`, and half real, no build keyword supplied. Keep the real half.

The two large tests here, `test_damage_engine_does_not_dispatch_on_item_names` and `test_the_pre_combat_stat_recipe_is_written_in_exactly_one_place`, guard real invariants and should stay, though as tree-wide scans they belong in `scripts/` beside `literal_defaults.py`. Removable: **44 lines**.

Twelve `assert <reason>.strip()` tests exist across the slice: `test_architecture.py` four, `test_behavior_frontier.py` five, `test_behavior_catalog.py` line 200, `test_cast_dependency_audit.py` two, `test_champion_inputs.py` line 192, `test_data_version_memos.py` line 240. Each is the same tautology. Delete every one whose table is a hand-written literal.

### 13. Dead pending-kernel setup in two of the slice's largest files, about 45 lines

`tests/test_cleanse_eligibility.py` lines 202 to 221 and `tests/test_crowd_control_immunity.py` lines 125 to 145:

```python
try:  # planned kernel, not landed yet; rows fail with the marker.
    from src.calculator import cleanse_eligibility as ce
except ImportError:
    ce = None

def _require_contract():
    if ce is None:
        pytest.fail("PENDING KERNEL: src/calculator/cleanse_eligibility.py has not landed yet; ...")
    return ce
```

Both modules ship today. I imported both successfully this session, and `architecture.md` lists both as owned leaves. The `except` arm is unreachable, so `_require_contract()` is an unconditional identity function called 40 times in one file and 32 times in the other.

Proposal: delete both scaffolds and replace the 72 call sites with the module reference, via a codemod per the house rule on repetitive edits. Removable: **about 45 lines**, plus 72 lines of indirection made honest.

### 14. test_champion_inputs.py asserts a bug still reproduces, 33 lines

Lines 234 to 278. `class TestTheEscalatedDefectIsStillTracked` reads `docs/receipts/escalated-defects-P3-3.7.json` and asserts two things: the stat Akshan's E reads is still absent from `calculate_total_stats` output, and `_extract_e_per_shot` returns the same value at 0 and at plus 250 bonus attack speed. Its docstring says the gate closes the entry by going red the day the defect stops reproducing.

Whoever fixes the Akshan bug must also edit a JSON receipt and delete this class to go green. That is the freeze-a-deletion shape inverted onto a defect.

Aside for the user, off task but load bearing: **Akshan's E per-shot damage is modelled as not scaling with attack speed, and the repo knows it.** That is a live calculation error, not a test problem.

Also in this file: `test_the_gate_measures_the_same_population_this_file_does` at line 111 compares the test's own scan helper to the script's. Both return `[]` today, so it passes on two empty lists. `test_the_registry_wires_the_options_rows_port` at line 219 is `assert inputs._OPTIONS_ROWS is not None`. Removable: **38 lines**.

### 15. test_custom_cast_order.py scans for retired literals, 25 lines

- `test_the_name_based_q_to_q2_fallback_is_gone` at line 113 asserts a comment is absent: `assert "Q2 is Q's second cast" not in source`.
- `test_neither_permutation_literal_survives` at line 145 asserts `'["E", "Q", "R", "W"]' not in source` across two modules.
- `test_the_call_site_names_the_narrow_check` at line 359 splits `pipeline.py` on the comment string "The post-parse cast-order call site" and reads the next 600 characters. Any edit to that comment breaks it.
- `test_the_four_shape_messages_are_what_a_400_now_carries` at line 160 duplicates `test_malformed_orders_are_rejected` at line 137. Same four inputs, same `pytest.raises(ValueError)`, only `match=` differs. Merge into one parametrize carrying the message.

The behavioural tests in this file are good and should stay: subset orders run, the recast is re-inserted, the response echoes the expanded order. Removable: **25 lines**.

### 16. Process-wide cache clears, against a documented trap

CLAUDE.md states: never `.clear()` a process-wide cache in a test, because it passes and silently costs every later test the warm cache. Four violations in the slice:

| File and line | Cache cleared |
|---|---|
| `test_briar_e.py:303,305` | `_ABILITY_ATOMS_MEMO`, in an autouse fixture bracketing every test in `TestAtoms` |
| `test_data_version_memos.py:532` | `ability_atoms._ABILITY_ATOMS_MEMO` |
| `test_behavior_declaration_acceptance.py:316,317,327,328` | `trigger_stream.tuple_incapable_items`, `streams_for` |
| `test_behavior_frontier.py:1231,1241` | `behavior_frontier._tag_first_seen` |

`test_briar_e.py` is the worst. The fixture is autouse, so every test in the class pays it twice, and every later test on the same xdist worker re-atomizes.

Proposal: give the memo an injectable root or key the way `zero_policy_frontier(root=...)` and `_input_fallback_sites(root=...)` already do, or `monkeypatch.setattr` a fresh dict. Note that `test_capabilities.py:67`, `surfaces["states"].clear()`, is not a violation. It deliberately mutates a returned copy to prove it is a copy. Keep it.

### 17. test_champion_module_contract.py scans for retired symbols, 14 lines

`test_review_campaign_batch_modules_and_imports_are_gone` at line 272 globs for `reviewed_batch_*.py` and scans for the substring. `test_packet_compiler_contains_no_champion_name_override_registries` at line 295 carries three `not in source` asserts. Both freeze deletions. `test_champion_modules_import_only_at_the_top` at line 280, between them, is a real lint and should move to `scripts/`. Removable: **14 lines**.

### 18. Exact duplicates found by AST body comparison

| Pair | Lines |
|---|---|
| `test_amumu.py::test_q_rank1_damage_matches_json:50` and `::test_q_reports_single_cast_damage:87`. Byte-identical bodies, both `parts_raw_total(...) == approx(70.0)` | 13 |
| `test_capabilities.py::test_the_published_list_moved_the_schema_version_with_it:98` and `test_aura_arming.py::test_the_schema_version_moved_with_the_payload:194`. Both are `assert CAPABILITY_SCHEMA_VERSION == 9` under about 12 lines of version-history docstring. A constant asserted against its own literal, twice, with prose that goes stale at version 10 | ~24 |
| `test_ashe_focus_lifecycle.py::test_stripped_q_rows_today_silent_zero_pinned_actual:888` and `test_ashe_q_active_window.py::test_stripped_q_rows_fail_loud:691` | ~8 |

`test_capabilities.py` lines 76 to 79 carry three assertions where the third, A equals C, follows from the first two by transitivity.

### 19 and 20. Meta-tests in test_coverage_claims.py

- `test_the_mutation_suite_is_nine_mutations_that_write_nothing` at line 2430, 20 lines, counts the `test_M1` through `test_M9` functions in its own module and asserts there are nine. The subject is the count of the tests beside it.
- `test_ci_runs_pytest_with_no_keyword_marker_or_path_filter` at line 718, 33 lines, parses `.github/workflows/tests.yml` and asserts the `pytest` invocation carries no `-k`, `-m`, or path. The rule is defensible. Its home is `test_ci_checkout.py`, which already owns what the workflow may say.
- `test_the_fabricated_claim_is_itself_well_formed` at line 314 asserts the fixture is well formed. Defensible as a non-vacuity guard. Low priority.

The rest of this 2,472-line file is strong and should be left alone: the M1 through M9 mutation negatives, the evidence-kind resolution table, and the live-item parametrizations.

### 21. Dead fixtures and dead doctrine

- `tests/conftest.py:183` `kindred_data` and `:187` `lulu_data` have zero references anywhere in `tests/`, `src/`, or `scripts/`. Verified. Delete 2 lines.
- `tests/test_ashe_q_active_window.py` lines 108 and 109:

  ```python
  _AWAIT = "awaiting P1-11 six-second active window"
  XFAIL  = pytest.mark.xfail(reason=_AWAIT, strict=False)
  ```

  Zero uses. No `@XFAIL` decorator exists in `test_ashe_q_active_window.py`, `test_ashe_focus_lifecycle.py`, or `test_dr_mundo_passive.py`.
- The doctrine that genuinely absent mechanics carry a non-strict `pytest.mark.xfail` is described at length in all three module docstrings: about 60 lines in `test_dr_mundo_passive.py`, about 70 in `test_ashe_focus_lifecycle.py` listing which rows are xfailed. None of it is true now, and `tests/coverage_resolver.py:610` treats an xfail marker as a failed evidence claim, so the coverage gate contradicts the doctrine. This is prose only, but it teaches the next author a rule the repo rejects.
- No `pytest.mark.skip` or `skipif` anywhere in the slice. The seven `pytest.skip` calls are honest local-evidence guards that `test_ci_evidence_parity.py` recognizes. No `time.sleep` and no wall-clock assertions in the slice. Category 8 is clean apart from the cache clears.

### 22. not hasattr one-liners

`test_coverage_evidence.py:666`, `assert not hasattr(coverage_evidence, "Lane")`, and `test_cp20_items.py:142`, `assert not hasattr(resolve_damage_effects([...]), "on_hit_heals")`. Two lines each. Both freeze a rename. Delete the `not hasattr` line, keep the positive assertion beside it.

## Category 7: oversized files

| File | Lines | Tests | Lines per test | Verdict |
|---|---|---|---|---|
| `test_damage.py` | 3,462 | 167 | 21 | Dense and behavioural. Fine. Could split by engine step. |
| `test_app.py` | 3,026 | 135 | 22 | About 390 lines are finding 1. The rest is real HTTP contract testing. |
| `test_cleanse_eligibility.py` | 2,723 | 43 | 63 | Size is prose, not copy-paste. `pyproject.toml` exempts it from the comment-width rule. Leave it, minus the dead scaffold. |
| `test_coverage_claims.py` | 2,472 | 102 | 24 | Strong file. Findings 5, 19, and 20 only. |
| `test_crowd_control_immunity.py` | 1,811 | 31 | 58 | Prose-heavy. Dead scaffold, finding 13. |
| `test_dr_mundo_passive.py` | 1,773 | 55 | 32 | 60-line stale xfail doctrine header, finding 21. Content is real. |
| `test_binary_roots.py` | 1,460 | 122 | 12 | Keep as is. 122 one-per-champion game-file parity checks against tracked dumps, 183 files, verified tracked. The `TestBatch5RootedConstants` class names are campaign residue. Rename only. |

No single test in the slice exceeds 150 lines.

## Checked and not reported

Recorded so the next audit does not re-derive it.

- `tests/conftest.py` is clean. The autouse `_process_state_is_given_back` guard and the deselect-never-skip collection hook are the two best pieces of test infrastructure in the slice.
- Good files: `test_binary_roots.py`, `test_deployment_package.py`, `test_bench_coupled_optimizer.py` (26 tests over a bench harness is heavy, but its void rule is a real gate), `test_ci_checkout.py`, the M1 through M9 mutation suite, `test_delivery_*`, `test_catalyst_resource_ledger.py`, and the champion damage-value tests.
- The 33 `assert "<phrase>" in text` cached-wiki-prose assertions across the slice are data tripwires for patch day, which is what `ability_prose.CachedSentence` exists for. Keep them.
- `test_ability_spec.py`'s quantity-read scans, `DECLARED_QUANTITY_READS` and `test_only_the_algebra_folds_two_quantities_into_one_expression`, are real lints with a named failure class. Keep them. But they, `test_architecture.py`'s scans, and `test_ci_evidence_parity.py` are all lints wearing a test's clothes. The house already has a home for those: `scripts/literal_defaults.py`, `scripts/swing_stream_audit.py`, `scripts/prose_lint.py`. Moving them takes about 600 lines of tree scanning out of `pytest` and puts each rule where a reader greps for it.
