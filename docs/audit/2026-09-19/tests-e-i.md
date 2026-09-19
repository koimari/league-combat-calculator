# Slop audit: useless and low-value tests, slice `tests/test_[e-i]*.py`

Scope: 151 files, 2,944 test functions, 69,663 lines. Read-only pass, no tracked file touched.

## Counts per category

| # | Category | Tests | Files | Est. removable lines |
|---|---|---|---|---|
| 1 | Asserts something was removed or does not exist | 32 functions plus 54 parametrize rows | 16 | 420 |
| 2 | Pins source text: `inspect.getsource`, `ast`, `read_text`, regex over `.py`/`.js`/`.css` | 131 | 35 | 900 |
| 3 | Tautologies, no assertion, assertion on the fixture | 22 | 14 | 160 |
| 4 | Duplicates: 67 structural clone groups, 197 functions | 197 | 48 | 3,000 |
| 5 | Campaign residue, receipt checks itself | 2 whole files plus 12 tests | 9 | 530 |
| 6 | Skips on the common path, stale xfail prose | 7 skip sites, 0 live xfail markers, 12 files whose docstrings describe xfails that no longer exist | 15 | 0, doc rot |
| 7 | Files over 1500 lines, single tests over 150 | 6 files, 1 test | 6 | 2,600 |
| 8 | Mutates shared process state | 28 sites | 4 | correctness, not lines |

Total estimated removable: about 4,950 lines, 7% of the slice. About 330 test functions fold into 60.

F1 alone is worth more than everything else combined, and it is mechanical.

## Summary table

| # | Finding | File::test | Cat | Lines | Proposal |
|---|---|---|---|---|---|
| F1 | 44 verbatim copies of the `attacker_stats` conftest fixture, inlined as a 25-key dict | `test_item_damage.py`, whole file | 7, 4 | 2,731 to 330 | Finish the fixture migration the file already started |
| F2 | 54 parametrize rows asserting deleted JS identifiers stay deleted | `test_frontend_crit_contract.py`, whole file | 1 | 124 | Delete. `test_frontend_crit_backend_200.py` pins the behavior |
| F3 | CSS and JS declaration text asserted as strings | `test_frontend_qa_147_157.py` 37, `test_f0_frontend.py` 16, `test_frontend_level_controls_contract.py` 2, `test_f1_bis_metrics.py` 4 | 2 | 533 to 80 | Delete the CSS value rows, keep DOM and node harness tests |
| F4 | 8 of 13 tests grep `src/app.py` for absent function names | `test_issue_158.py` | 1, 2 | 90 | Delete the 8, keep the 5 behavioral, rename the file |
| F5 | Green means two known cache defects are still present | `test_escalated_defects_cached_data.py`, whole file | 5, 8 | 175 | Delete, move the two entries to `TRAPS.md` |
| F6 | 689 lines for an item whose only modelled effect is +10 ability haste | `test_ionian_boots_summoner_haste.py` | 3, 7 | 689 to 240 | Cut to accessor, stat pin, app regression |
| F7 | Per-item copies of engine-wide invariants | `test_gluttonous_greaves.py`, `test_gunmetal_greaves_riot_branch.py` | 4, 3 | 240 | Delete. `test_survival_kernel.py` owns the parity invariant |
| F8 | Identical `TestReviewedCrowdControl` block in 22 slice files, 156 tree-wide | `test_ekko.py` through `test_ivern.py` | 4 | 180 in slice | One parametrized test over the champion registry |
| F9 | 18 byte-identical interpreter refusal clones | `test_interp_*.py` | 4 | 250 | One parametrize driven off `interpreters.INTERPRETERS` |
| F10 | 26 `.clear()` calls on process-wide memos | `test_f3_rotation_all.py`, `test_interp_threshold_defense.py`, `test_f2_rotation.py` | 8 | n/a | `monkeypatch.setattr` a fresh dict |
| F11 | `assert run() == run()` and five siblings | `test_eclipse_timing_packet.py`, `test_f3_rotation_all.py`, 4 more | 3 | 90 | Delete |
| F12 | The ER5 count narrative over a derived receipt | `test_er5_tail_triage.py`, whole file | 5 | 152 to 30 | Fold the one staleness check into `test_literal_defaults.py` |
| F13 | Scattered campaign narrative assertions | `test_immobilize_predicate.py`, `test_golden_snapshot.py`, `test_interpreters_registry.py`, `test_issue_159.py`, `test_issue_160_boundaries.py`, `test_e9_corpus.py` | 1, 5 | 80 | Delete each |
| F14 | Scattered tautologies | `test_engine.py`, `test_f2_rotation.py`, `test_gate_receipt.py`, `test_holder_stacking.py`, `test_heal_event_row.py`, `test_evelynn.py` | 3 | 60 | Delete or fix |
| F15 | AST node-type sequence of a src module asserted | `test_item_outcomes.py::test_the_module_holds_the_declaration_and_nothing_else` | 2 | 10 to 2 | Assert no callable, or move to `behavior_frontier` |
| F16 | Regex counting call sites by indentation | `test_item_support_effects.py`, 7 tests | 2 | 90 | Read the registry, not the file |
| F17 | 4 near-identical `/api/optimize` certification tests, each a real build search | `test_event_order_certification.py` | 4 | 68 to 20 | Parametrize |
| F18 | Skip on the common path could hide a 1,025-line suite | `test_gnar_mega_gamefile.py`, `test_gunmetal_greaves_riot_branch.py` | 6 | n/a | Make missing evidence a failure |

## Detail, ranked by payoff

### F1. `tests/test_item_damage.py`, 2,731 lines of copy-pasted stats dict

6,970 lines and 226 tests, the largest file in the tree. `tests/conftest.py` already ships the fixture these tests need:

```python
@pytest.fixture
def attacker_stats():
    def _build(**overrides: float) -> dict[str, float]:
```

and the file already declares `_FightHarness` at line 267 to install `attacker_stats` and `fight` on its test classes. The migration stopped partway. 44 test bodies still inline the same 25-key dict, differing in two or three values. Measured span of those 44 blocks: 2,731 lines. Each becomes one line, `stats = attacker_stats(attack_damage=104, critical_strike_chance=25, is_melee=False)`.

Two parametrize candidates sit inside those 44:

- `test_ahri_level_18_fiendhunter_zero_crits`, `_one_crit`, `_two_crits`, `_three_crits` at lines 3130, 3192, 3254 and 3313 are four 60-line bodies differing only in the crit count and the expected total. About 180 lines.
- `test_10_autos_rageblade_4_procs`, `_12_autos_rageblade_5_procs`, `_15_autos_rageblade_6_procs` at 3891 through 3913 are three 5-line bodies over `(autos, expected_procs)`.

Why the duplication brings no value: it is vehicle, not coverage. All 44 blocks assert the same thing about the same five keys.

Aside worth fixing on the spot: six sites at 3137, 3194, 3256, 3315, 3495 and 3627 patch `src.calculator.fight.autos.simulation.random.random` with `unittest.mock.patch` to control crits. CLAUDE.md's rule is `deterministic=True` on the request, which `FightConfig` supports and which 39 other call sites in the slice use. The mock pins an implementation detail of the crit roll, `deterministic` pins the contract. Each of the six also re-imports `from unittest.mock import patch` inside the function body.

Proposal: finish the `attacker_stats` and `fight` migration with a codemod, the dicts are structurally identical. Parametrize the two families. Swap the six `random.random` patches for `deterministic=True`. Verify with `python scripts/golden_snapshot.py compare scripts/golden_baseline.json`, which must show zero diffs since this touches tests only.

### F2. `tests/test_frontend_crit_contract.py`, 54 rows asserting a deletion

The whole file, 124 lines, reduces to:

```python
@pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
def test_app_js_forbids_retired_formula_literals(literal):
    assert literal not in SOURCE

@pytest.mark.parametrize("identifier", FORBIDDEN_IDENTIFIERS)
def test_app_js_forbids_dead_engine_identifiers(identifier):
    assert identifier not in SOURCE
```

over 9 literals and 45 identifiers. Two problems.

It freezes a deletion forever. 45 function names removed in one 2026 refactor can never be reused, including generic ones: `statMatrix`, `targetCard`, `allyCard`, `rosterCard`, `windowControl`, `resultReason`.

The literals are bare substrings of a whole JS file: `"1.08"`, `"3089"`, `"6653"`, `"6655"`, `"4645"`, `"6616"`. Any unrelated number in `app.js` containing those digits fails the gate. `"3089"` fires on a `z-index: 3089`, a timestamp, or a hash prefix.

The behavior it claims to protect, that the backend owns the 200% crit multiplier, is pinned at the public boundary by `tests/test_frontend_crit_backend_200.py`, which drives 0%, 25% and 100% crit through `/api/calculate` and asserts against the response receipts. That file is a keeper and makes this one redundant.

Proposal: delete the file. If "no damage engine in the browser" deserves a standing gate, it is one lint in `scripts/` over `static/js/app.js` checking the two formula shapes, `0.7025` and `crit / 100`, not 54 test IDs.

### F3. Frontend CSS and JS source-text snapshots, 533 lines

| File | Tests | Source-text tests | Lines |
|---|---|---|---|
| `test_frontend_qa_147_157.py` | 65 | 37 | 264 |
| `test_f0_frontend.py` | 38 | 16 | 162 |
| `test_frontend_level_controls_contract.py` | 2 | 2 | 42 |
| `test_f1_bis_metrics.py` | 16 | 4 | 65 |

Representative shapes:

`test_constraints_block_uses_shared_panel_transparency` at `qa_147_157.py:431` asserts `"background: var(--rail-panel)" in block` and `re.search(r"--panel-alpha:\s*\.67", tokens)`. The stylesheet asserting its own declaration text, pinning `.67` with no way to change it deliberately.

`test_the_variant_index_to_boolean_rule_has_one_home` at `f0_frontend.py:565` asserts `'options[option.key] = abilityInput("R").variant === 0;' not in source`, a whole JS statement including whitespace and semicolon.

`test_level_controls_use_level_delta_path_contract` at `level_controls_contract.py:9` asserts a 110-character JS expression verbatim, then asserts `"data-level-delta]" in source`, which the assertion two lines above already implies.

`test_dead_renderers_are_removed` at `f0_frontend.py:628` runs 18 `not in source` checks over deleted function names, which is category 1 again.

Why they bring no value: none can tell whether the page works. Each goes red on a rename or a formatter run, and green on a broken UI.

What to keep in those files:

- `test_stylesheet_braces_balance` at `qa_147_157.py:76`. The file's docstring names the bug it caught: an unclosed `@media (max-width: 720px)` block scoped `[hidden]`, `.economics-bar`, `.engine-error` and `.breakdown-panel` to phones. That is a failure class.
- The `run_timeline_renderer` harness at `qa_147_157.py:575` through 710 and the 10 tests on it. It lifts the shipped `renderEventTimeline` out of `app.js` and runs it in node against real event lists. That is behavior, and it is the pattern the rest of the file should have used.
- Every `soup.select_one` test. Those read the rendered page, not the source.

Proposal: delete the `in source`, `in css` and `rule_block` tests. Keep the DOM and node harness tests. Where a CSS value matters for contrast or legibility, prove it with a same-vantage capture, not a string compare.

### F4. `tests/test_issue_158.py`, 8 of 13 tests grep `src/app.py`, 90 lines

`test_public_scalar_parsers_have_one_owner`, `test_app_has_no_flask_calculate_round_trip`, `test_comparison_curve_reuses_resolved_target_projection`, `test_bis_route_only_delegates_and_translates`, `test_optimizer_errors_are_typed_not_message_classified`, `test_routes_use_loadout_rule_owners`, `test_observed_paste_logic_has_a_non_flask_owner`, `test_certainty_logic_has_a_non_flask_owner`.

Each reads `src/app.py` as text and asserts a set of `def _name(` strings is absent. Line 55:

```python
assert "def _calculate_response(" not in source
assert "def _run_calculate_payload(" not in source
assert "response.get_json()" not in source
```

`response.get_json()` is a Flask idiom that could appear in a new route or a health check. These freeze one refactor's shape against every future one.

The 5 behavioral tests in the same file are good: `test_public_integer_policy_accepts_numeric_strings`, `test_public_integer_policy_rejects_booleans_and_decimals`, `test_calculate_payload_runs_without_flask_request_context`, `test_bis_application_boundary_runs_without_flask_context`, `test_validation_receipt_calculation_is_reusable`. They prove "callable without a Flask request context" by calling the thing without a Flask request context.

Proposal: delete the 8, move the 5 into `tests/test_app.py` or a `test_calculator_facade.py`, drop the issue-number filename.

### F5. `tests/test_escalated_defects_cached_data.py`, green means the bug is still there, 175 lines

The docstring states it:

> Red means the defect closed -- retire the entry and invert the assertion; it does not mean a regression.

`test_the_simple_description_still_describes_a_different_item` asserts `item["simpleDescription"] == "Defer damage until later."` for Imperial Mandate, which is the wrong description. It goes red the day the wiki cache is fixed. `test_one_phrase_is_still_three_atoms` pins the atomizer's known over-fan-out at exactly three atoms valued 20.0.

A test whose green state is "the defect persists" has negative value. It turns a fix into a CI failure and teaches the next session to re-pin instead of fix.

Real hazard alongside it: `test_the_scheduled_home_check_has_a_red_it_can_reproduce` at line 104 writes into the tracked tree.

```python
scratch = ROOT / "docs" / "receipts" / ".homeless-for-the-red.json"
scratch.write_text(json.dumps(homeless), encoding="utf-8")
```

CLAUDE.md's own rule from issue #263: a gate that needs a dirty world builds it in `tmp_path`. This races `pytest -n auto` workers and leaves a file in `docs/receipts/` if the process is killed. The function it calls, `escalated_cached_data_lines(scratch)`, already takes a path, so the fix is one argument.

Proposal: delete the file. The two defects belong in `TRAPS.md`, one line each, and in the patch-day audit output that `scripts/patch_update.py` already prints. If the wiring deserves a test, it is one test in the patch-update suite using `tmp_path`.

### F6. `tests/test_ionian_boots_summoner_haste.py`, 689 lines for +10 ability haste

The item's entire modelled effect is a stat. The file spends 689 lines and 20 tests on it. The worst single test is `test_a_flash_or_ignite_cast_would_reuse_9_percent_faster` at line 624, whose docstring says it is "genuinely untestable today (no summoner-spell state exists)":

```python
effective = base_cd * 100.0 / (100.0 + haste)
assert effective == pytest.approx(base_cd * 100.0 / 110.0), spell
assert effective < base_cd, spell
assert pytest.approx(0.0909090909) == 1.0 - 100.0 / 110.0, spell
```

The first assertion computes both sides from `haste`, which the two lines above pinned at 10.0. The third asserts a float literal against arithmetic on float literals, with no repo code involved.

Alongside it: `test_no_summoner_fields_exist_anywhere_in_the_fight_result` at 512, `test_absent_summoner_spell_state_authors_no_row_or_claim` at 566, `test_one_rotation_fight_is_bit_identical_with_and_without_the_boots` at 464, `test_auto_only_fight_is_identical_with_and_without_the_boots` at 486. Four tests asserting the item does nothing, four ways.

Proposal: keep `test_missing_accessor_key_fails_loud_naming_item_and_key`, `test_malformed_registry_value_fails_loud_never_silent_fallback`, `test_ionian_insight_accessor_returns_exactly_10`, `test_boots_contribute_exactly_ten_ability_haste_and_45_ms`, `test_effective_cooldowns_and_recasts_match_the_stat_exactly`, `test_app_boots_slot_fight_stays_green`. Delete the rest. 689 down to about 240.

### F7. Per-item copies of engine-wide invariants, 240 lines

`tests/test_gluttonous_greaves.py` at 907 lines and `tests/test_gunmetal_greaves_riot_branch.py` at 859 each carry three copies of a global fact.

`test_compiled_walk_equals_receipt_walk_<item>_build`. `tests/test_survival_kernel.py` owns this invariant in 10 parametrized rows covering every walk shape. A per-item copy adds one build to a list, not a branch.

`test_score_only_fight_parity_<item>_build`. Same.

`test_identical_fights_produce_identical_receipts_and_stats` at `gluttonous_greaves.py:844`. Runs the same deterministic payload twice, asserts equality of three payload sections, then does it again twice more. Nine assertions, zero branches.

This triad appears in 11 files tree-wide: `bastionbreaker`, `cryptbloom`, `eclipse_timing_packet`, `gluttonous_greaves`, `gunmetal_greaves`, `mikael`, `muramana`, `redemption`, `zhonya`, plus `survival_kernel` which is the owner. Sibling auditors cover the files outside `[e-i]`.

Proposal: delete the three per-item copies in each file. Add the item's build to `test_survival_kernel.py`'s parametrize list if the walk shape is genuinely new.

### F8. Per-champion CC review boilerplate, 22 files in slice, 156 tree-wide

Every champion test file carries the same class:

```python
class TestReviewedCrowdControl:
    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self): ...
    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("<Name>") == []
    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("<Name>")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
```

The clone detector found the fimbulwinter test with an identical AST in 15 slice files at 6 lines each, `test_module_cc_is_the_declaration_the_parser_wired` in 10 at 11 lines each, `test_every_reviewed_part_carries_its_kind` in 5, `test_control_free_slots_name_every_word_their_text_contains` in 8, and `test_each_declared_kind_is_the_word_its_slot_text_uses` in 7.

The duplication also opens a coverage hole. A new champion module can simply not carry the block, and nothing notices. A parametrize over the registry closes that.

Slice files: `test_ekko`, `test_elise`, `test_evelynn`, `test_ezreal`, `test_fiddlesticks`, `test_fiora`, `test_fizz`, `test_forced_attack_control_marker`, `test_galio`, `test_gangplank`, `test_garen`, `test_gnar`, `test_gragas`, `test_graves`, `test_gwen`, `test_hecarim`, `test_heimerdinger`, `test_hwei`, `test_illaoi`, `test_irelia`, `test_item_damage`, `test_ivern`.

Half of `test_declared_kinds_are_the_ones_the_cached_kit_gives` derives from the cached wiki text, `cc_review.control_words(cc_review.slot_text(data, "Q")) == []`. That half is per-champion and valuable. The `assert <module>.MODULE_CC == {literal dict}` half is a constant restating itself, category 3, and is what the derived half should replace.

Proposal: one parametrized test over `_CHAMPION_MODULES` in a shared `tests/test_cc_review.py` for the two registry-wide assertions. Keep the per-champion text derivation. Slice saving 180 lines and 44 functions, tree-wide 1,250 lines and 312 functions. Coordinate with the three sibling auditors before anyone moves this.

### F9. Interpreter refusal clones, 18 tests, 250 lines

Eleven bodies with identical ASTs, differing only in the module and exception type:

```
test_interp_active_cast.py:131      test_interp_ally_packet.py:335
test_interp_cast_proc.py:215        test_interp_charged_strike.py:247
test_interp_crit_profile.py:165     test_interp_defense_state.py:103
test_interp_on_hit_strike.py:173    test_interp_opening_defense.py:182
test_interp_periodic.py:217         test_interp_spellblade.py:206
test_interp_stat_derivation.py:389
```

each being:

```python
(foreign,) = [r for r in behavior_rules("Tiamat") if r.family is RuleFamily.ACTIVE_CAST]
ctx = build_context("Tiamat", FightFacts(level=18, fight_duration_seconds=5.0,
                                          target_bonus_health=0.0, holder_is_melee=True))
with pytest.raises(<Family>InterpretationError):
    <module>.<entry>(foreign, ctx, EngineLane.PAIR_ENGINE)
```

Plus 4 identical `test_the_family_is_registered_on_the_lane_that_builds_it` in `combat_state`, `opening_defense`, `reactive` and `threshold_defense`, and 3 identical `test_deleting_the_interpreter_withholds_rather_than_granting_nothing`.

Same hole as F8. A newly registered interpreter gets no cross-family refusal test unless someone remembers to paste the block.

Proposal: one parametrize in `tests/test_interpreters_registry.py` derived from `interpreters.INTERPRETERS`, which already maps `(family, lane)` to the entry point. The row set then cannot fall behind the registry. 250 lines removed, coverage increased.

### F10. Shared process state, correctness not lines

CLAUDE.md: "Never `.clear()` a process-wide cache in a test: it passes, and it silently costs every later test the warm cache." The slice does it 26 times.

`tests/test_f3_rotation_all.py` clears `_DERIVED_RULE_CACHE` at lines 1158, 1167, 1242, 1244, 1247, 1256, 1258, 1262, 1272, 1274, 1276, 1280, 1307, 1309, 1318, 1331, 1345, 1360, 1378, 1398, 1455 and 1470, plus `_MATRIX_DPS_CACHE` at 1361. That is the rotation-derivation memo for about 170 champions. Every later test on that xdist worker re-derives from cold.

`tests/test_interp_threshold_defense.py` clears `threshold_defense._THRESHOLD_HEALTH_TICK_MEMO` at 288 and 291.

`tests/test_f2_rotation.py:345` mutates the module global `CAST_ORDER_OVERRIDES`, inserting a row then restoring with `clear()` plus `update(original)` in a `finally`. The restore is correct, the window is real under `-n auto`, and the `clear()` half is the shape CLAUDE.md warns about.

Proposal: `monkeypatch.setattr(module, "_DERIVED_RULE_CACHE", {})` in a fixture. The memo is a module attribute, so the substitution is one line and leaves the real cache warm for every other worker.

### F11. Determinism tautologies, 90 lines

`tests/test_eclipse_timing_packet.py:992`, `test_identical_kernel_feed_sequences_produce_identical_receipts`: the body is a local `run()` closure and `assert run() == run()`.

`tests/test_eclipse_timing_packet.py:979`, `test_identical_fights_produce_identical_full_receipts`: same fight twice, same receipt.

`tests/test_f3_rotation_all.py:547`, `test_derivation_is_deterministic`: loops over about 170 champions calling `derive_champion_rule` twice and asserting equality. The function is memoized on `_DERIVED_RULE_CACHE`, so the second call returns the same object. The test cannot fail unless the memo is removed.

`tests/test_gluttonous_greaves.py:844`, `tests/test_gunmetal_greaves_riot_branch.py:380`, `tests/test_ionian_boots_summoner_haste.py:464` and `:486`: same shape.

The legitimate variant of this test is the crit one. CLAUDE.md records that two identical `calculate_payload` requests on a crit build return different totals unless `deterministic=True`. None of these six sit on a crit build.

Proposal: delete all six. One test on a crit-capable build covers the real case, and the golden compare covers it every run.

### F12. `tests/test_er5_tail_triage.py`, the campaign's count narrative, 152 lines

Nine tests over `scripts/tail_site_triage.py`'s committed receipt. Most assert a story.

`test_the_tail_is_mostly_not_convertible_at_all` asserts `total > 1000`, `totals["NOT_A_ROW_FIELD"] / total > 0.4` and `unconvertible / total > 0.9`. Its docstring says the point is so "the count cannot be quoted as a debt figure again". That is an argument, not an invariant.

`test_the_unexamined_remainder_is_what_the_count_reports` duplicates `test_no_tail_site_is_unexamined`. Both assert `CANDIDATE == 0`.

`test_the_triage_receipt_matches_the_tree` checks a derived receipt against its own regenerator.

CLAUDE.md names the owner: `tests/test_literal_defaults.py` owns the covered set `ROOTS` and the ratcheted `ER5_TAIL`. Two homes for one fact, which is the drift rule 3 forbids.

One test is worth keeping. `test_an_adjudicated_site_still_exists_in_the_tree` at line 133 catches a stale adjudication entry that would shrink the count for work that no longer exists.

Proposal: fold that test into `tests/test_literal_defaults.py`, delete the file. 152 down to about 30.

### F13. Scattered campaign narrative assertions, 80 lines

| Site | Assertion | Why it brings no value |
|---|---|---|
| `test_immobilize_predicate.py:222` `test_the_widening_is_ten_kinds_and_the_retired_five_are_a_subset` | `RETIRED_WALK_LITERAL < IMMOBILIZING_CC_KINDS`, `len(IMMOBILIZING_CC_KINDS) == 15`, `len(diff) == 10` | `RETIRED_WALK_LITERAL` is defined only in this test file, and its comment says it is "not read from the tree, because it is the thing the tree does not hold". It measures a past delta. The `== 15` also duplicates `tests/test_cc_kind_vocabulary.py`, which CLAUDE.md names as the one guard over that vocabulary. |
| `test_golden_snapshot.py:1675` `test_the_retired_digest_is_marked_and_not_presented_as_current` | `receipt["retired_sha256"] != receipt["sha256"]`, `"SR6" in receipt["retired_why"]` | Asserts a history field is still history. Nothing can move it. |
| `test_interpreters_registry.py:670` `test_no_gap_row_stands_on_a_counter_this_phase_has_retired` | `assert "counter 1" not in row.reason` | A substring check over prose in a table. A reason legitimately citing counter 1 fails it. |
| `test_issue_159.py:53` `test_the_retired_duplicate_walks_are_gone` | rglobs all of `src/` for 4 deleted identifiers | Freezes 4 names forever, including the generic `expire_timed_shields`. The sibling test above it, `test_no_other_module_consumes_or_grants_a_shield_pool`, is a real lint and stays. |
| `test_issue_160_boundaries.py`, whole file, 55 lines | `assert not Path("src/calculator/healing_legacy.py").exists()` and four more, plus `assert len(healing.HEALING_RULE_CHAMPIONS) == 62` | Four "deleted file stays deleted" assertions plus a champion count that goes red on every honest champion addition. The `resolver.__module__ == module.__name__` loop is the one real check. |
| `test_e9_corpus.py:385` `test_the_reader_walks_no_history` | `assert not hasattr(sys.modules[__name__], "subprocess")` | Asserts the test file itself does not import `subprocess`. No repo code under test. The two lines after it, that the reader half of `repin_corpus.py` contains no `subprocess.run`, are the real check. |

Proposal: delete each named test, keep the sibling lints. Fold `test_issue_160_boundaries.py`'s one real check into `tests/test_healing.py` and delete the file.

### F14. Scattered tautologies, 60 lines

`test_engine.py:215` `test_phase_order_constant`: `assert PHASE_ORDER == ("buff", "debuff", "damage", "onhit", "amp")`. A constant equal to its literal.

`test_f2_rotation.py:340` `test_a_derived_rule_carries_no_override_reason`: constructs `ComboRule` without `override_reason` and asserts `override_reason is None`. It asserts the default it declined to pass.

`test_gate_receipt.py:319` `test_no_output_path_writes_nothing`: calls `emit_receipt(..., output=None)` then asserts `list(tmp_path.iterdir()) == []`. `tmp_path` was never handed to the function, so the assertion is on the fixture.

`test_gate_receipt.py:113` `test_validate_rejects_int_passed` is subsumed by `test_validate_rejects_string_and_falsy_int_passed` at 120, which drives `("true", 0, 1)` through the same branch.

`test_holder_stacking.py:233` `test_arm_key_is_the_only_arming_dedupe_in_src`: `assert deciders == ["amp.py:" + str(_arm_key_lineno())]`, where `_arm_key_lineno()` re-parses the same file and returns the first `arm_key` def's line. The line-number half cannot disagree with itself. The useful half, no second `arm_key` anywhere under `src/calculator/`, is one line. The helper and the string building are 20 lines around it.

`test_heal_event_row.py:57` `test_the_optional_keys_really_are_sometimes_absent`: counts key frequency in `golden_baseline.json` rows and asserts four keys are neither absent everywhere nor present everywhere. A measurement of the corpus, not of code, re-derived from a file the golden gate already pins.

`test_evelynn.py:30`: `assert evelynn.MODULE_CC["W"] == "per_part"` restates the dict literal asserted five lines earlier in the same test.

Eight tests carry no `assert` and no `pytest.raises`: `test_item_coverage.py` at 359, 363, 402 and 891, `test_item_behavior.py:170`, `test_e3_stacks_2.py:494`, `test_event_order_certification.py:209`, `test_golden_snapshot.py:1788`. Most call a helper that raises, which is defensible. Read `test_persistent_state_champions_validate_for_every_fight_window` and `test_kindred_mounting_dread_pounces_on_third_stack` before keeping them: a test that only constructs only checks for exceptions.

### F15. `tests/test_item_outcomes.py::test_the_module_holds_the_declaration_and_nothing_else`

```python
shapes = [type(node).__name__ for node in tree.body]
assert shapes == ["Expr", "ImportFrom", "ImportFrom", "AnnAssign"], shapes
```

This asserts the exact AST node-type sequence of `src/calculator/item_outcomes.py`. A `from __future__ import annotations`, a third import, a type alias, or splitting the declaration all fail it, and none is the failure the test names, which is a `def` appearing in a declarative home. The real invariant is no `FunctionDef`, `ClassDef` or `If` in the module. That is two lines and survives every legal edit.

`scripts/behavior_frontier.py` already owns the declarative-home exclusion this test defends, so that is the right home.

### F16. `tests/test_item_support_effects.py`, 7 source-text tests, 90 lines

`test_every_damage_modifier_packet_is_a_row` at line 674 counts call sites with `re.findall(r"^\s*kind=PacketKind\.DAMAGE_MODIFIER\.value,$", body, re.MULTILINE)`. Black reflowing one `_packet(...)` call onto a single line drops a site from the count, and the test still passes because both sides fall together.

`test_only_the_coupled_producer_reads_the_blue_bubble_values` at line 990 asserts `readers == {"item_behavior_catalog.py", "item_effects.py", "item_support_effects.py"}` from an rglob for the substring `"blue_reduction"`. Its own docstring records that this set already grew from two names to three.

`_damage_modifier_call_sites` at line 626 is a 46-line AST walk asserting each `_packet(kind="damage_modifier")` call names a literal `Authority.<member>`. That guards a real failure class, since an expression where a literal is required means the registry cannot be checked.

Proposal: move `_damage_modifier_call_sites` to `scripts/` beside the other structural gates. Delete the other two.

### F17. `tests/test_event_order_certification.py`, 4 near-identical optimize tests

`test_optimize_api_certifies_tahm_kench_event_order` at 242, `_qiyana_multistage_ultimate` at 261, `_shyvana_form_packets` at 280, `_ziggs_minefield_cadence` at 365. Identical ASTs, 17 lines each, differing in the champion name. Each POSTs `/api/optimize` with `max_legendary_slots: 1` and asserts the same three fields, and each runs a real build search.

Proposal: one parametrize over the four names, about 20 lines. Consider deriving the name list from the champions whose packets carry `event_order_certified`, which closes the same "a new one gets forgotten" hole as F8 and F9.

### F18. Skips that could hide a suite

`tests/test_gnar_mega_gamefile.py`, 1,025 lines and 41 tests, calls `pytest.skip("local Gnar game-file evidence is unavailable")` at 161, 645 and 653 when `data/bin/characters/gnarbig.bin.json` cannot be read. The bins are tracked: `git ls-files data/bin/characters` returns 183 files and `git check-ignore` reports not ignored. The skip is defensive today. It is still the shape that retires a 1,000-line suite the day a sparse checkout or an LFS miss lands.

`tests/test_gunmetal_greaves_riot_branch.py:169` has the same shape.

Four `pytest.skip("node is not installed")` sites at `test_f0_frontend.py:355` and `:721`, `test_frontend_qa_147_157.py:604`, `test_issues_78.py:500`. Reasonable on a local box. On CI the absence of node should fail, otherwise the node harness tests never run and nobody learns.

Proposal: make the missing-evidence branch `pytest.fail` while the file is tracked. Gate the node skip on an env var CI sets.

Doc rot found alongside: 12 files describe themselves in their docstrings as containing `pytest.mark.xfail` rows, for example "genuinely absent contract pieces are `xfail` with reason `awaiting P3-3L ...`". The slice holds no live `pytest.mark.xfail`. The markers went, the prose stayed. Files: `test_eclipse_shield_selection`, `test_eclipse_timing_packet`, `test_ezreal_w_mark_refund`, `test_fimbulwinter_cc_packet`, `test_fimbulwinter_nearby_enemy_range`, `test_fimbulwinter_same_time_ordering`, `test_force_of_nature_compiled_parity`, `test_gangplank_w_cleanse`, `test_gluttonous_greaves`, `test_gunmetal_greaves_riot_branch`, `test_heimerdinger_multihit`, `test_ionian_boots_summoner_haste`. Rule 4 asks for current state only, so those headers should say what the file now does.

## Files over 1500 lines in the slice

| File | Lines | Tests | Note |
|---|---|---|---|
| `test_item_damage.py` | 6,970 | 226 | F1, 2,731 lines are one copy-pasted dict |
| `test_engine.py` | 1,867 | 107 | Genuine coverage, one tautology in F14 |
| `test_golden_snapshot.py` | 1,797 | 100 | Genuine tooling suite, 3 narrative tests in F13 |
| `test_item_effects.py` | 1,679 | 127 | Genuine, one 3-row clone group at 448, 562 and 698 |
| `test_guardian_angel_resurrection.py` | 1,607 | 34 | Holds the one test over 150 lines: `test_ordinary_stasis_stacked_beyond_the_revive_window_blocks_on_its_own_terms` at line 689, 182 lines |
| `test_f3_rotation_all.py` | 1,600 | 54 | F10, 26 cache clears, and F11 |

## Keep list, so a cleanup does not overshoot

These read like candidates and are not.

The `test_e1_*` through `test_e9_*` campaign-named files covering healing, DoT ticks, stacks, summons and fixes. Despite the names, every test drives a real `/api/calculate` fight and asserts a number recomputed from `data/champions.json` leveling rows. They are the champion coverage frontier. The only residue in them is `test_e9_corpus.py:385`, listed in F13.

`test_frontend_crit_backend_200.py`, 110 lines. Real behavior at the public boundary, and it makes F2 redundant.

The `run_timeline_renderer` node harness in `test_frontend_qa_147_157.py`. It executes the shipped renderer.

`test_stylesheet_braces_balance`. It caught a documented real bug.

`test_import_namespace.py`'s duplicate-formula scans, which hold `0.7025` and `0.0175` to `stat_formulas.py`. A real lint over a real failure class. It belongs in `scripts/` beside `literal_defaults.py`, both because CLAUDE.md's quirk about untrustworthy full-suite runs under concurrent `src/` edits names this exact file, and because a script can run it without the import cost.

`test_event_slots.py::test_src_constructs_no_second_registry` and `test_issue_159.py::test_no_other_module_consumes_or_grants_a_shield_pool`. Both count constructions of a singleton or direct arithmetic on a pool. Real invariants, same note about belonging in `scripts/`.

`test_gate_receipt.py` apart from the two tests named in F14.
