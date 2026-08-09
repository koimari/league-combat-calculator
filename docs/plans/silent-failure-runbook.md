# Campaign Runbook — Verification, Golden, Performance, Agents

*Single source for every protocol shared by more than one phase of the [Silent-Failure Campaign](2026-08-08-silent-failure-campaign.md). Phase docs cite rulings here **by `R-nn` id and by section name** — this document has no numbered sections and nothing may cite one; cross-phase facts, the semantic invariant, decision ids (`D-nn`) and human-owned calls (`H-n`) live in the umbrella. Phase 0A ([phase-0-gates-and-corrections.md](phase-0-gates-and-corrections.md)) builds every instrument whose signature appears in Shape below; that table additionally names three later-phase gates — `behavior_frontier.py` (Phase 3), `migration_frontier.py` (Phase 4) and `cast_dependency_audit.py` (Phase 5) — each with its creating lane. **The instrument signatures in Shape below are the only copy** — no phase document restates them.*

*Decisions owned: **D-96, D-97**.*

## Goal

Every commit in the campaign is judged by one named gate set whose baselines were captured before the first edit, whose every unexplained numeric move earns an independent oracle receipt, and whose performance claims come from counters the harness emits rather than from prose.

## Decisions

### The gate set

**R-01 — Eleven checks gate every commit.** A slice cites this table; it never invents a gate list. "Catches" is why the row exists.

| # | Command | Pure refactor | Semantic | Catches |
|---|---|---|---|---|
| 1 | `pytest` | green; `collected` = the pinned count + declared new, `skipped` and `xfailed` non-increasing | same | everything already pinned, plus a test quietly becoming a skip |
| 2 | `python scripts/golden_snapshot.py compare scripts/golden_baseline.json` | zero diffs | zero unless the slice touches the pair engine | pair-engine leak |
| 3 | `python scripts/golden_snapshot.py compare scripts/golden_coupled_baseline.json` | zero diffs | every diff explained + R-15 | roster/walk behaviour golden cannot see |
| 4 | `python scripts/acceptance_matrix.py --json` | exit 0 | exit 0 | a withheld/partial optimizer result sold as success |
| 5 | `python scripts/champion_optimizer_matrix.py --json` | exit 0 | exit 0 | a new withholding reason across 173 champions |
| 6 | `black --check src/ tests/ scripts/` | clean | clean | formatter drift (version pinned in `requirements.txt`) |
| 7 | `pylint src/ --fail-under=9` + `python scripts/pylint_ratchet.py --check` | pass | pass | per-file rot hidden by a rising mean |
| 8 | `python scripts/bench_coupled_optimizer.py --fixed-work --isolate --json` | counters, residual, winner, score identical | moves only as declared in advance | cache loss, fallback, search poisoning |
| 9 | `python scripts/repin_corpus.py --check` | pass | pass | a corpus receipt pinned at a different engine |
| 10 | `pytest tests/test_survival_kernel.py` (the compiled-vs-receipt equivalence suite) | green | green | compiled score path desyncing from the walk |
| 11 | `python scripts/bench_coupled_optimizer.py --fixed-work --isolate --no-compiled --json` versus row 8's default run, all four bench scenarios | identical winner and score | identical, or an explained rung change | a routing change that only shows up as a different answer |

**R-02 — Rows 4 and 5 are campaign gates, not CI trivia.** A commit that introduces a withholding reason extends `champion_optimizer_matrix.EXPECTED_WITHHOLDING_PREFIXES` in that same commit — otherwise `pytest` is green while CI is red, which is the campaign's own failure shape wearing a different hat (D-23, D-96).

**R-03 — Pylint is two gates.** CI's real gate is `--fail-under=9` (verified in `.github/workflows/tests.yml`), so the 9.53 average is unenforced; the campaign adds a per-file non-decreasing ratchet over every file a slice touches, seeded in the fingerprints receipt (D-99). Why: ~25 small clean modules raise the mean while a hotspot degrades under it.

**R-04 — Gate verdicts reuse `scripts/gate_receipt.build_receipt`.** `scripts/validate_receipt.py` checks the **acceptance** envelope in CI today; the champion-optimizer envelope is explicitly deferred at `.github/workflows/tests.yml:62-64` (`TODO(issue #139)`) and joins in the same commit that adds R-01 row 5. A second receipt shape is a second thing that can quietly stop being true.

**R-05 — A gate ships with a red it can reproduce on demand.** A new check lands with a **permanent** negative test in the M1–M9 idiom — a seam, or a text-injection fixture that makes the check fail on command. Where no seam exists, the throwaway commit's sha and the sha256 of its failing output are recorded in `campaign-fingerprints.json` under `demonstrated_red`. Why: this campaign exists because a check that could not fail was indistinguishable from a check that passed — and "demonstrated once during development" is exactly the unverifiable claim about the past that Phase 1 outlaws.

### Baselines: what is measured, what is merely carried

**R-06 — Every pinned number carries a provenance class.** `VERIFIED` (reproduced against source this session), `CARRIED` (two independent contracts agree, not re-run), `PRIOR` (a number with no producing tool). `docs/receipts/campaign-fingerprints.json` stores the class beside every value. Why: three quarters of the performance contract had no producer and nothing in the numbers said so.

**R-07 — First measurement defines the baseline; a `PRIOR` is never a gate.** The optimizer work counters stand as follows, and the ruling below **overrides Phase 0's slice 0A.4 acceptance line**: an instrument may not be gated on the value it exists to measure. 0A *records* the measured residual beside the prior; it does not assert equality.

| Counter family | Prior (`cassiopeia_3champ` / `cassiopeia_5champ` / `mundo_3champ`) | Producer today | Class |
|---|---|---|---|
| public evaluations | 1324 / 1033 / 706 | `bench_coupled_optimizer.py:311` (`body["evaluations"]`) | VERIFIED (3champ), CARRIED (others) |
| measured proposals | 1306 / 1015 / 688 | none | PRIOR |
| score-memo misses | 1249 / 967 / 577 | none (`_PurchaseSearch._score_memo`, `optimizer.py:915`, is unobserved) | PRIOR |
| pair `run_fight` calls | 2735 / 3127 / 1446 | none | PRIOR |
| residual (`pair_calls − evals × n_enemies`) | 87 / 28 / 34 | none — arithmetic over three PRIORs | PRIOR |
| wall best-of-3, score, `search_timeline_coverage.complete` | 2095.6 ms, 4003.1, `False` (3champ) | `bench_coupled_optimizer.py:128-134` | VERIFIED |

The 0A capture records the measurement and the prior side by side; a divergence is explained in the capture commit body and is **not** a regression. Only `public_evaluations`, wall, score and `complete` may be asserted against a prior.

**R-08 — A counter becomes an equality gate only after a determinism probe.** Five isolated repeats must agree exactly; a counter that does not is demoted to a ratchet with the tolerance recorded in the receipt. Why: `_STATE_PROTO_MEMO` and `_CAST_ORDER_PARAMS_MEMO` clear wholesale at 512 entries, so hit rate is roster-size dependent, and an unexplainable ±2 destroys a gate's authority faster than having no gate.

**R-09 — `--fixed-work` means machine-independent work.** The harness sends `time_budget_ms` at the app's clamp ceiling (60 000; `app.py:1321`, default 12 000) and voids any run whose response reports `truncated: true`. **If every repeat of a scenario voids**, that scenario is written to `campaign-fingerprints.json` as `unmeasurable` with `provenance=PRIOR` and removed from R-01 row 8's gate set **by name** — never left as an absent-but-assumed-green counter. Why verified and load-bearing: `_PurchaseSearch.expired()` (`optimizer.py:939-941`) truncates scoring on a wall-clock deadline, so counters measured at the default budget are a property of the machine, and no PRIOR above can be reproduced without this.

**R-10 — Baselines are captured before a phase's first edit and re-captured only at phase boundaries.** A mid-phase re-capture makes the previous slice's diff unattributable (D-97).

### Golden protocol

**R-11 — Two baselines, two jurisdictions.** `scripts/golden_baseline.json` covers the pair engine only (`golden_snapshot.py` enters through `pipeline.run_fight`); `scripts/golden_coupled_baseline.json` covers the roster path. Golden proves *no pair-engine leak* and proves nothing about the coupled walk, `item_coverage`, or `item_support_effects`; a slice touching those must cite a non-golden numeric gate in its own row or it has no gate (D-93).

**R-12 — The coupled baseline's coverage is derived, not listed.** Its scenario set must cover every `damage_modifier` producer, both ledger shapes, and one Catalyst roster, with the producer set **read** rather than typed so adding a seventh producer without a scenario fails rather than passes. The source moves once: `item_support_effects.cross_participant_authorities()` — **created in 0A.2**, because R-10 captures this baseline before 0B's first edit: at 0A it derives its producer set from the six `kind="damage_modifier"` construction sites, which needs no `Authority` declarations to exist, and 0B's C2 fills its `Authority` values when the packets declare them — repointed at `trigger_stream.CAPABILITIES` in P2a. A source assertion forbids a hand list at either stage. Why the switch is stated: the capability registry does not exist when 0A builds the instrument, and "read from the capability registry" would be unimplementable on the commit that ships it.

**R-13 — Golden equality is equality to two decimals.** Verified: `_rounded` (`golden_snapshot.py:107-119`) rounds every float before write and `compare` recomputes with identical rounding. A summation-order change under 0.005 per leaf is invisible, so bit-exactness claims (Phase 4's `SumPlan`) need their own assertion and may not be discharged by golden. The instrument for those claims is `golden_snapshot.py capture-coupled --exact`, which writes `scripts/golden_coupled_exact.json` with `repr(float)` values, is excluded from the 2-dp compare, and is gated by its own equality test.

**R-14 — Provenance metadata is excluded from compare through one named constant.** `compare` today pops only `metadata.git_head` (`golden_snapshot.py:76-82`); the fingerprint block adds `src_tree_sha`, which changes on a comment-only edit. Both live in `COMPARE_EXCLUDED_PROVENANCE`, and a test asserts the numeric sections are not in it. Why: without this, "zero diffs on a pure refactor" becomes false for every commit and the strongest gate in the campaign gets routinely waived.

**R-15 — Diffs are classified, not eyeballed.** `compare --report <path>` emits one `LeafDiff` per differing leaf (schema in Shape), grouped by scenario and sorted by `|percent|`. A leaf **qualifies for investigation** when `abs(percent) > 10`; or its transition is anything other than `value` — the closed set is `zero_to_value`, `value_to_zero`, `value_to_error`, `error_to_value`, `absent_to_value`, `value_to_absent`, `text_change`; or `abs_delta > 1.0` on a damage-section leaf. A **slice** additionally owes at least one investigator on its largest-`|abs_delta|` leaf per scenario when its differing-leaf count exceeds 1% of the numeric leaves — a ratio, whose denominator `compare` reads from the `fingerprint` leaf-count field of `campaign-fingerprints.json` and never from a figure written in a document. `percent` is `inf` when the old value is zero, which is why from-zero is its own transition rather than a percentage bucket. Why the extra clauses: `diff_snapshots` already emits `<absent>` transitions and golden holds string leaves — notably `item_sweep.<item>.<champ>.breakdown_keys`, whose change is a structural behaviour change — and a systematic single-digit-percent move across the whole snapshot would otherwise owe nobody a receipt, since no individual leaf clears the 10% bar.

**R-16 — Reports are scratch; receipts are committed.** Per-leaf reports, diff dumps and exploratory runs go to the session scratchpad and are cited by path in the commit body; only the two baselines and the files listed in Shape enter the repo.

**R-17 — Never re-capture golden inside a semantic slice.** Land the code against the old baseline plus a committed allowlist of expected diff paths, each carrying its oracle receipt; re-capture once per phase boundary. Why: reverting a slice must not require reverting a multi-megabyte blob (D-97).

### Independent investigation

**R-18 — One fresh Opus 5 investigator per qualifying occurrence (R-15).** It receives the leaf path, the two values, and **a tree export containing exactly `data/` and `docs/math-foundations.md` — never `src/`, `tests/`, `scripts/`, `docs/plans/`, `docs/receipts/` or `.git`** — never the plan, the commit, the diff, or the expected answer. The export command is part of this ruling, not left to the spawning agent:

```bash
git archive --format=tar HEAD data docs/math-foundations.md | tar -x -C <scratch>
```

Why: an oracle that has read the fix is not an oracle — and exporting the working tree hands it `src/`, which *is* the fix. R-19 only ever needs cached wiki text and `docs/math-foundations.md`, so the export is exactly those two paths and nothing else.

**R-19 — The investigator returns an oracle receipt or the baseline does not move.** The receipt lands at `docs/receipts/oracle-<slice>-<leaf-slug>.json` and carries an independent computation from cached wiki text or a quoted formula in `docs/math-foundations.md`, plus a verdict from the closed set `new_value_correct | old_value_correct | both_wrong`. No baseline is re-captured while any qualifying occurrence lacks one.

**R-20 — Occurrence counts are declared in advance.** Every semantic slice in every phase carries an **`Expected qualifying occurrences: <n>`** line — zero is a legal and common value, and stating it is what makes a first occurrence a stop. An unexpected occurrence stops the slice and is investigated, rather than being absorbed as a budget overrun. A slice with no such line has not declared a gate.

R-20's second half — **when `<n>` is not knowable before the edit, declare the population and measure it first.** Some corrections change which rows a baseline holds, so their occurrence count cannot be read off the pre-change tree by inspection. Such a slice declares the **qualifying population** instead: a set enumerated from committed artifacts — the baseline files, the scenario set, the registries — **before the slice's first `src/` edit**, whose size is then written into the `Expected qualifying occurrences` line and into the commit body, and whose membership bounds what may qualify. Any occurrence outside the enumerated population is an unexpected one and stops the slice exactly as an over-count would. Measure, then mutate, then pin: enumerating after the edit measures the fix rather than predicting it, and a slice carrying neither a number nor a pinned population has not declared a gate. Where a slice's occurrences are per scenario, the population is enumerated per scenario and the line carries the per-scenario breakdown.

### E9 corpus discipline

**R-21 — The staleness anchor is the merge-base `src/` tree, supplied to both readers *and the writer* by one function.** D-100 moves the assert off HEAD; verified `tests/test_e9_corpus.py:412-416` *also* selects the executed `_PINNED` set by comparing each scenario's `src` tree to HEAD's, and the assert itself is `:443-452`. Moving only the assert would leave the receipt suite selecting zero scenarios and passing by testing nothing — the campaign's own failure shape inside the campaign's own gate. **The writer takes the same anchor**: `repin(*, at="merge-base", check=False)` is the default, because writing HEAD's sha while comparing against the merge base makes `--check` fail the moment `src/` diverges, including on the comment-only commit Phase 0's criterion 1 requires to pass. One function, three call sites.

**R-22 — `repin_corpus.py --check` fails on a stale pin *and* on an empty or short selection.** "Short" is quantified, not judged: `--check` fails unless the executed non-legacy scenario count equals `campaign-fingerprints.json`'s `corpus.non_legacy_count` **and** the executed id set equals the set `test_e9_corpus` parametrizes. The four legacy scenarios stay exempt and enumerated. Silence cannot be mistaken for success.

**R-23 — One writer.** Only the integration agent re-pins, inside the integration commit. Until R-21 lands, `data/practice-corpus/scenarios.json` is a cross-worktree mutex: two lanes write different `src/` shas into the same field and conflict on every merge, so L0's first commit is the corpus fix and nothing else starts before it merges (D-94).

### Performance protocol

**R-24 — Counters ride one `WorkCounters` threaded on `_PurchaseSearch`, never a monkey-patch.** A patched harness cannot be tested and cannot be trusted in CI.

**R-25 — The residual is the sharp instrument.** `pair_run_fight_calls − public_evaluations × n_enemies` moves the instant a cache stops hitting or a candidate starts falling back, long before wall time leaves noise. Every phase that touches the tuple predicate changes exactly this number, so it is **captured** in 0A — before the first correction, beside its 87/28/34 prior with a one-line divergence cause — and becomes D-01's receipt once R-08's determinism probe passes. Until then it is a `PRIOR` and R-07 forbids gating on it.

**R-26 — Fingerprints are captured with `--isolate` (one subprocess per repeat).** Verified warm-cache contamination: `_RESOLVED_DAMAGE_EFFECTS`, `_DERIVED_RULE_CACHE`, `_MATRIX_DPS_CACHE`, `_ITEM_STATS_MEMO` and `data_fetcher`'s `lru_cache` survive repeats and scenarios, so `--scenario X` alone is not comparable to X inside a full run.

**R-27 — A fourth scenario, `syndra_mandate_3champ`, is part of the instrument.** All three existing scenarios author no `cc_kind`, so the campaign's headline correction is invisible to today's harness; this scenario is what exposes the compiled→receipt routing cost and the search-poisoning cliff (D-69).

**R-28 — Wall time is a ratchet, never a pass criterion**: best-of-3 isolated on `cassiopeia_5champ` may not exceed the stage's declared baseline by more than 10%. **Every Phase 4 stage declares that baseline in its own row**, captured at the stage's first commit and written to `campaign-fingerprints.json` before its second — "the stage's declared baseline" is otherwise declared by nobody. **Allocation is gated once**, at Phase 4 S4: `allocation_probe("cassiopeia_3champ")` (`tracemalloc` peak, one isolated evaluation) pinned with 15% margin, because that stage trades per-fight dict churn for cached frozen records. The probe is an 0A instrument and the peak is a fingerprints field; until both exist the allocation sentence is a `PRIOR` and criterion 4 forbids citing it as a threshold.

**R-29 — The one-walk property is asserted structurally, not measured.** Kernel invocations per pass, `SurvivalAction` construction sites, dispatch ladders in `survival/`, and "no view module performs arithmetic" are counted from source against the stage's expected value, **with the counting rule stated so the number is reproducible**. Measured today: one kernel with **two** invocations (`participant_timeline.py:2045` receipt, `:2809` score); **nine `SurvivalAction(...)` construction expressions** (`participant_timeline.py:2764`; `survival/actions.py:203, :451`; `survival/compile.py:314, 479, 571, 862, 939, 1008`) — a bare `grep -c "SurvivalAction("` returns 11 because it also matches the class statement and a docstring; **seven `survival_action_from_event` call sites** (`participant_timeline.py:341, 349, 1958, 1983, 1999, 2368`; `survival/receipt_state.py:348`); three compile scopes; one dead second ladder. Why source counts: a second engine regrows as code long before it shows up as a number.

### Rollback boundaries

**R-30 — One semantic correction per commit; never batch.** Phase 0's C2 removes a spurious ×1.12 on holder magic, C3 removes one on non-magic, C4 *adds* amp at t=0 — they partially cancel, and batched, the net bench delta is unexplainable. Because they cancel, C2's and C4's coupled-golden allowlists **overlap on the holder's `t = 0.0` magic leaves**; that overlap is enumerated in both allowlists in advance, with an oracle receipt each, and is not an error.

**R-31 — Derivation lands beside the legacy set with an asserted delta; the flip is a one-symbol commit** (D-98). The revert unit is the slice, and a slice that cannot be reverted without reverting a generated artifact is mis-scoped (R-17).

**R-32 — Baselines never move inside a semantic commit.** `golden_baseline.json`, `golden_coupled_baseline.json`, `golden_coupled_exact.json`, `campaign-fingerprints.json` and `item-coverage-classification.json` move in their own commits, authored by the integration agent — **except `campaign-fingerprints.json`'s `wall{stage}`, `alloc{scenario}` and `demonstrated_red{gate}` keys, which the owning lane writes in a receipt-only commit touching no `src/`** (R-28, R-05); every other key in that file is the integration agent's. Why the carve-out: R-28 requires a stage's wall baseline before the stage's second commit and R-05 requires a gate's demonstrated red before its first green is cited, and neither moment is an integration commit — an integration-only writer makes ten stage baselines and every new gate's red unwritable, so Phase 4's criterion 17 could never be discharged.

**R-36 — Machine-derived frontier and audit receipts are slice-local and move *with* the slice that moves their count.** `docs/behavior-frontier.json`, `docs/migration-frontier.json` and `docs/cast-dependency-audit.json` are produced by their script on the commit whose counters they record; holding them back would make every counter-moving slice red until an integration commit it is forbidden to contain — the same deadlock D-94 diagnosed in the corpus gate. Coverage moves inside a Phase 3 slice land against the **committed** classification receipt plus `docs/receipts/expected-coverage-diff-<slice>.json`, the R-17 allowlist mechanism, enumerating every moved key with its reason. `EXPECTED_WITHHOLDING_PREFIXES` is a gate script, not a receipt, and R-32 does not reach it (D-96 requires it move in the same commit).

**R-37 — The plan documents are gated like source.** The campaign machine-checks every `src/` claim and
must not exempt its own plans, which hold dozens of measured counts and citations verified once at
`1274615` and rotting since — three of rev 2's own corrections were instances of that one gap.
`scripts/plan_audit.py`, invoked by `tests/test_plan_audit.py` so it rides R-01 row 1 with no twelfth
gate row, runs three checks over `docs/plans/*.md`:

1. **Citations.** Every `file.py:NNN` pattern must name an existing file, and where a backtick-quoted
   fragment adjoins the citation, the fragment must appear within ±5 lines of the cited line. The
   fragment is the authoritative referent and the line number only a locator: a drifted number is
   refreshed in a doc-only commit; a citation whose fragment no longer exists anywhere in the file is
   escalated as a plan/tree divergence, never silently re-pointed.
2. **Golden shape figures**, two prongs so both failure modes are caught: the retired figure's literal
   spellings are pinned inside the instrument and the live golden/coupled-golden count values are read
   from `campaign-fingerprints.json` at run time, each matched as a standalone word-boundary integer
   (catches a *correct* restated figure); and any integer within a few tokens of golden-shape keywords
   (`golden`, `leaf count`, `entry count`, `scenario entr`) must carry a `fingerprint:` citation marker
   (catches a *wrong* one — the retired-figure incident was a figure that reproduced under no
   definition, which a value match alone can never see). A committed collision allowlist naming the doc
   and reason absorbs legitimate coincidences, so the docs' many non-golden integers are out of reach
   by construction.
3. **Decision inventory.** `docs/receipts/decision-inventory.json` — one row per declared id with its
   owning document and, for split decisions, every half — is asserted equal to what the umbrella's
   manifest and decision tables actually declare, and the reserve gaps are asserted absent. Umbrella
   criterion 11 reads this check instead of performing a prose audit.

### Agents

**R-33 — Every campaign role uses Opus 5; mutating agents work in an isolated `git worktree` from the ownership map in Shape, while verification and investigator agents get read-only clones.** The model assignment covers lanes L0–L6, verification and investigation roles V/I, and integration role X; substituting another model is a campaign-plan change, not an execution-time choice. At most two lanes are live at once — L6 plus whichever of L0→L1→L2→L3→L4→L5 is current. This is a property of the file heat map, not a scheduling preference: any proposal to run L2 and L4 concurrently is rejected because both rewrite `item_support_effects.py`.

**R-34 — Integration is local-only rebase-then-cherry-pick, verified on the integrated tip; no campaign agent pushes, updates a remote branch, opens a pull request, or publishes any artifact.** The `integrate` agent rebases (never merges — a merge commit's `src/` tree matches neither parent and re-breaks the corpus gate even after R-21), cherry-picks in the lane's declared order without ever splitting a derivation/flip pair, runs the full R-01 matrix on the integrated tip rather than the lane tip, re-pins the corpus (R-23), and updates `campaign-fingerprints.json` with one line of cause per moved value. At every barrier it additionally clears `plan_audit.py` (R-37) on the integrated tip and repairs what it reports — drifted citation numbers in a doc-only commit, missing fragments escalated. The check failing red is what drives the refresh; diligence is not the mechanism.

**R-35 — Every coherent slice is signed off by a fresh read-only Opus 5 that has not read the plan.** A slice is the smallest unit with a completion criterion. Its brief is exactly:

> Here are a slice's stated completion criteria and its commit range. Independently verify each criterion against source and by running the gate commands. Do not read the implementation plan. Report per criterion `DISCHARGED` with the evidence you ran, or `NOT DISCHARGED` with what you found. Additionally: name any behaviour the slice changed that its commit bodies do not mention.

The last sentence is the load-bearing one — it is the check that would have caught the original incident. Integration blocks on the verdict; every `NOT DISCHARGED` is resolved before the next barrier.

## Shape

**Instruments and artifacts** — the campaign's one such table. One responsibility each; no other document re-lists these, and the signatures below are the only copy.

| Path | Created by | Role |
|---|---|---|
| `scripts/golden_snapshot.py` | 0A (L0) | gains `fingerprint`, `compare --report`, `capture-coupled [--exact]`, `COMPARE_EXCLUDED_PROVENANCE` |
| `scripts/golden_coupled_baseline.json` | 0A (L0) | roster-path baseline (R-11, R-12) |
| `scripts/golden_coupled_exact.json` | 0A (L0) | unrounded per-attacker totals; the only instrument a bit-exactness claim may cite (R-13) |
| `scripts/repin_corpus.py` | 0A (L0) | corpus anchor + `--check` gate (R-21, R-22) |
| `tests/test_e9_corpus.py` | 0A (L0) | consumes the anchor for both the assert (`:443-452`) and `_PINNED` (`:412-416`) |
| `scripts/bench_coupled_optimizer.py` | 0A (L0) | `WorkCounters`, residual, `--fixed-work`, `--isolate`, `--no-compiled`, `allocation_probe`, fourth scenario |
| `scripts/pylint_ratchet.py` | 0A (L0) | per-file non-decreasing score check (R-03) |
| `scripts/plan_audit.py` + `tests/test_plan_audit.py` | 0A (L0) | the plan documents gated like source (R-37): citation-fragment verification, both golden-figure prongs, decision-inventory equality — rides R-01 row 1 through its test |
| `docs/receipts/decision-inventory.json` | 0A (L0); refreshed in a doc-only commit whenever a decision table changes | every declared decision id with its owning document and split halves — the machine-readable half of umbrella criterion 11 (R-37) |
| `scripts/patch_update.py` | 0A (L0), edited | `ALLY_ITEM_EFFECTS` enters the audit (D-47) |
| `docs/receipts/campaign-fingerprints.json` | 0A captures it once; `integrate` is the only writer thereafter, **except `wall{stage}` / `alloc{scenario}` / `demonstrated_red{gate}`, written by the owning lane in a receipt-only commit** (R-32's carve-out for R-28 and R-05) | the baseline record (R-06, R-10) |
| `docs/receipts/item-coverage-classification.json` | Phase 1, re-captured at Phase 3's coverage flip | the full public coverage dict per item and lane — Phase 1's real numeric gate |
| `docs/receipts/expected-coverage-diff-<slice>.json` | Phase 3, per slice | in-slice coverage moves against the committed receipt (R-36) |
| `docs/receipts/oracle-<slice>-<leaf>.json` | investigator agents | one verdict each (R-19) |
| `<scratch>/oracle-export/` | the agent spawning `investigate-<leaf>` | the only tree an investigator sees — exactly `data/` and `docs/math-foundations.md`, never `src/`; built by the one `git archive` command in **R-18**, which is that command's sole home |
| `scripts/behavior_frontier.py` + `docs/behavior-frontier.json` | Phase 3 (L4) | frontier counters 1–4 **and** their committed exclusion lists (D-40, R-36) |
| `scripts/migration_frontier.py` + `docs/migration-frontier.json` | Phase 4 (L5) | frontier counters 5–7 **and** their committed exclusion lists (D-40, R-36) |
| `scripts/cast_dependency_audit.py` + `docs/cast-dependency-audit.json` | Phase 5 (L6) | declared-vs-inferred edges, suppressions, inferred-kind coverage, marker reach (R-36) |
| session scratchpad | any lane | leaf reports, diff dumps, exploratory runs (R-16) |

**Types and functions.**

```python
# scripts/golden_snapshot.py
COMPARE_EXCLUDED_PROVENANCE: frozenset[str]   # metadata keys compare ignores: git_head, src_tree_sha,
                                              # champions_fetched_at, items_fetched_at
Transition = Literal["value", "zero_to_value", "value_to_zero", "value_to_error", "error_to_value",
                     "absent_to_value", "value_to_absent", "text_change"]

@dataclass(frozen=True, slots=True)
class LeafDiff:
    """One differing golden leaf, classified for triage."""
    path: str; section: str; old: float | str | None; new: float | str | None
    abs_delta: float; percent: float; transition: Transition

def fingerprint(snapshot: Mapping[str, Any]) -> dict[str, int | str]:
    """The leaf/entry counts plus src_tree_sha — the one source of those figures.

    Domain: the numeric sections only.  ``metadata`` is excluded, because it holds
    two wall-clock floats that move on every capture plus the provenance keys
    ``compare`` already pops (R-14); counting them makes the published figure wrong
    on its first run.  A test asserts the excluded key set is exactly
    COMPARE_EXCLUDED_PROVENANCE's, so the two cannot drift apart."""
def leaf_report(old: Mapping, new: Mapping) -> tuple[LeafDiff, ...]:
    """Every difference as a LeafDiff, grouped by scenario, sorted by |percent|."""
def qualifies_for_investigation(diff: LeafDiff) -> bool:
    """R-15's threshold — the one predicate that decides an investigator is owed."""
def capture_coupled(scenarios: Sequence[CoupledScenario], *, producers: frozenset[str],
                    exact: bool = False) -> dict[str, Any]:
    """Roster snapshots through the coupled path, covering every damage_modifier producer.

    ``producers`` is read, never typed: cross_participant_authorities() at 0A/0B,
    trigger_stream.CAPABILITIES from P2a (R-12).  ``exact`` writes repr(float)."""

# scripts/repin_corpus.py — one anchor for the writer and both readers (R-21)
def anchor_src_sha(*, base: str = "main") -> str:
    """The src/ tree object at the merge base — the corpus's real staleness anchor."""
def repin(*, at: str = "merge-base", check: bool) -> int:
    """Re-probe and rewrite every non-legacy sha; --check fails on a stale pin or a short
    selection (R-22).  ``at`` defaults to the anchor, never HEAD: writing HEAD's sha while
    comparing against the merge base makes --check fail on a comment-only commit."""

# scripts/bench_coupled_optimizer.py
@dataclass(slots=True)
class WorkCounters:
    """Threaded on _PurchaseSearch; never monkey-patched."""
    public_evaluations: int; measured_proposals: int
    score_memo_misses: int; pair_run_fight_calls: int; rungs: Counter[str]

def residual(counters: WorkCounters, n_enemies: int) -> int:
    """pair calls minus evaluations x enemies — the cache/fallback tripwire (R-25)."""
def fixed_work_report(scenario: str, *, isolate: bool, repeats: int) -> dict[str, Any]:
    """One scenario's counters, residual, four-state rung histogram, timeline_complete,
    winner, score and wall — void if the response reports truncated (R-09)."""
def determinism_probe(reports: Sequence[Mapping]) -> dict[str, Literal["exact", "tolerant"]]:
    """Which counters repeat exactly and may therefore be equality-gated (R-08)."""
def allocation_probe(scenario: str) -> int:
    """tracemalloc peak bytes for one isolated evaluation — Phase 4 S4's gate (R-28)."""

# scripts/pylint_ratchet.py
def check_ratchet(baseline: Mapping[str, float]) -> tuple[str, ...]:
    """Files whose pylint --output-format=json score fell — empty tuple is the pass condition."""
```

**`docs/receipts/campaign-fingerprints.json`** — `{schema_version, captured_at_src_tree, golden{…counts}, coupled_golden{…counts}, bench{scenario: {counter: {value, provenance, tolerance}}}, alloc{scenario: {peak_bytes, provenance, margin}}, wall{stage: {scenario, best_of_3_ms, provenance}}, tests{collected, skipped, xfailed}, corpus{non_legacy_count}, frontier{counter: {value, provenance}}, demonstrated_red{gate: {sha, output_sha256}}, pylint{path: score}}`. Every leaf value carries `provenance ∈ {VERIFIED, CARRIED, PRIOR}` (R-06) and, when it is a ratchet rather than an equality gate, its `tolerance` (R-08). **This file is the sole home of every golden shape count in the campaign** — no plan document states one.

**Worktree ownership map** — exclusive write per **(file, symbol)**; every lane may read everything. Three files are shared by symbol between lanes that are **live at the same time** — `pipeline.py`, `ability_spec.py`, `champions/syndra.py` — and each carries its carve-out here rather than in a phase doc. A symbol carve-out on a file whose earlier owner has already merged (`item_support_effects.py` after L1, `trigger_stream.py` after L2) is a sequential handoff, not one of those three, and is written into the receiving lane's row.

| Lane | Agent | Worktree | Owns |
|---|---|---|---|
| L0 | `gate-hardening` | `wt/phase0a` | every instrument in the table above, `tests/test_e9_corpus.py`, `tests/test_survival_kernel.py`, the 0A deletions in `survival/`, the `TransitionRank` projection and every float-`phase` repoint, `data_registry.py` (`data_version`), and in `ability_spec.py` the `DamageClass`/`AttackClass`/`Authority`/`Disposition` vocabulary |
| L1 | `corrections` | `wt/phase0b` | `pipeline.py`, `scenario.py`, `item_support_effects.py`, `survival/transitions.py`, `survival/actions.py`, `participant_timeline.py`, `capabilities.py`; in `ability_spec.py` the 0B consumers; and in `champions/syndra.py` **the `recast_of="Q"` stamp only, at C6** |
| L2 | `trigger-bus` | `wt/phase2` | `trigger_stream.py`, `ability_spec.py` (from B1), the five hotspots after L1 merges, and in `src/app.py` **only** the single request-boundary `except ProjectionStarvation` handler D-25 requires — a sequential handoff of that file to L4 at B2 |
| L3 | `coverage-evidence` | `wt/phase1` | `coverage_evidence.py`, `tests/coverage_resolver.py`, `tests/test_coverage_*.py`, `tests/conftest.py`, `tests/test_architecture.py` |
| L4 | `behavior-rules` | `wt/phase3` | `value_ref.py`, `item_behavior*.py`, `interpreters/`, `scripts/behavior_frontier.py`, `src/app.py`, then the migration hotspots |
| L5 | `program-engine` | `wt/phase4` | `program/`, `survival/*`, `participant_timeline.py`, `scripts/migration_frontier.py`, in `trigger_stream.py` **only** the two Phase-4 `MechanicCapability` fields (`view_tags`, `holder_stacking`) with the `HolderStacking` enum beside `Pairing` — a sequential handoff after L2 merges, not a concurrent share; in `ability_spec.py` **only** the `Quantity` algebra beside `Disposition` (D-72), the same sequential-handoff shape; and in `static/js/app.js` **only** S9's withheld-marker rendering helper |
| L6 | `cast-dependency` | `wt/phase5` | `cast_dependency.py`, `rotation_resolver.py`, `champions/{module_contract,packet_module,__init__}.py`, `champions/syndra.py` (everything except L1's C6 stamp), `scripts/cast_dependency_audit.py`, the rotation/Syndra suites (the two Syndra cast-order pin scenarios are **not** a lane-6 fixture — they live in L0's coupled scenario set, per R-12 and Phase 0's 0A.2), and in `pipeline.py` **only** `validate_for_champion` and the post-parse expansion/check call site — that one file from **B1**, not B0 |
| V / I | `verify-<slice>` / `investigate-<leaf>` | none (read-only tree export, R-18) | — |
| X | `integrate` | main clone | merge commits, baselines, `campaign-fingerprints.json` |

**Barriers.** `B0` L0 merged unblocks everything; **`B0.5` L6's `cast_dependency` leaf commit merged unblocks L1's C6**, the campaign's only backwards edge (umbrella *Ordering*); `B1` L1 (all six corrections C1…C6) unblocks L2/L4/L5, hands `ability_spec.py` and `champions/syndra.py` to L2 and L6 respectively, **and hands `pipeline.py`'s `validate_for_champion` and its post-parse expansion/check call site to L6** — C6 creates both, so L6's one `pipeline.py` commit writes into them and waits here; `B2` L2 unblocks L3's pairing evidence and hands `src/app.py` to L4; `B3` L3 unblocks L4's coverage flip; `B4` L4 unblocks L5's amp kernel. L6 runs from B0 to the end and everything it owns outside `pipeline.py` is blocked by nothing — B0.5 is L6 unblocking L1, not the reverse, and B1 is the return edge for that one file.

**L3 and L6 may be live together.** `tests/conftest.py`'s new `pytest_collection_modifyitems` hook is purely additive and collection-order-independent — it stashes the node set and mutates no item — so L6's new test files are stashed like any other. "L3, alone" means alone within the serial chain.

## Success criteria

1. Each of R-01's eleven rows runs from a single named command — the literal command is in the table, including rows 10 and 11 — and each new one (rows 3, 7-ratchet, 8, 9, 11) carries either a permanent negative test or a `demonstrated_red` entry in `campaign-fingerprints.json` before its first green is cited (R-05).
2. `golden_snapshot.py fingerprint` reproduces the counts recorded in `docs/receipts/campaign-fingerprints.json`, that file is the **sole** home of those counts, and `plan_audit.py`'s golden-figure check (R-37's second check — value match on retired literals and live receipt counts, plus the proximity-marker prong that catches a figure whose value is *wrong*, with a committed collision allowlist) asserts no `docs/plans/*.md` file states a golden leaf or entry count. Every consumer reads the receipt, so a doc figure and the file figure cannot disagree because there is no doc figure.
3. `bench_coupled_optimizer.py --fixed-work --isolate --json` emits, for all four scenarios including `syndra_mandate_3champ`: four counter families, the residual, a four-state rung histogram, `timeline_complete`, winner, score and wall; and every run voids itself when the response reports `truncated`.
4. Every value in `campaign-fingerprints.json` carries a provenance class; the file contains no `PRIOR` that is also cited as a gate threshold, and each `PRIOR` retained after 0A carries the measured value beside it plus a one-line divergence cause.
5. `determinism_probe` has run over five isolated repeats per scenario and every equality-gated counter is listed `exact`; every counter marked `tolerant` carries a numeric tolerance in the receipt.
6. `compare` against `golden_coupled_baseline.json` is clean, and a test fails if the producer source `capture_coupled` reads — `cross_participant_authorities()` before P2a, `trigger_stream.CAPABILITIES` after — gains a `damage_modifier` producer with no covering scenario. The post-P2a half of this criterion is Phase 2's to discharge.
7. A test asserts `src_tree_sha ∈ COMPARE_EXCLUDED_PROVENANCE` and that no `champion_baselines` / `registered_champion_fights` / `item_sweep` key is in it; deleting the constant's `git_head` entry turns `compare` red on any commit.
8. `repin_corpus.py --check` fails on a stale pin and when the executed non-legacy count differs from `corpus.non_legacy_count` or its id set differs from the set `test_e9_corpus` parametrizes — asserted, not asserted-by-convention (R-21, R-22). Writer and both readers call `anchor_src_sha`; a source assertion pins that there is exactly one anchor function.
9. Every campaign occurrence satisfying `qualifies_for_investigation` has an oracle receipt in `docs/receipts/` naming a verdict and its source, and each baseline re-capture commit enumerates the receipts covering its diffs.
10. No commit in the campaign range touches both `src/` behaviour and one of R-32's five baselines. Machine-derived frontier and audit receipts are exempt and are expected to move with their slice (R-36); the integration agent checks both halves over the range at every barrier.
11. Every slice has a recorded `verify-<slice>` verdict; no barrier is crossed with an open `NOT DISCHARGED`, and every "behaviour the commit bodies do not mention" finding is either documented or reverted.
12. At no point are more than two lanes live, and no two live lanes own the same **(file, symbol)** pair per the ownership map — checkable from the map plus the active worktree list. The three files shared between concurrently live lanes (`pipeline.py`, `ability_spec.py`, `champions/syndra.py`) are checked at symbol granularity, and their handoffs happen at B0.5 and B1; the sequential handoffs (`item_support_effects.py` after L1, `trigger_stream.py` after L2) are checked as barrier ordering instead, because their previous owner has merged.
13. Wall time on `cassiopeia_5champ` (best-of-3, isolated) stays within 10% of the baseline **declared in that stage's own row**, and the Phase 4 S4 `allocation_probe` peak stays within its 15% margin — both read from `campaign-fingerprints.json`, never from prose.
