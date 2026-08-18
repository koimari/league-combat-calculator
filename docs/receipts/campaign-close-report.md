# Silent-Failure Campaign — Closing Verification Report

*Dated 2026-08-14. Written on the final tip `067c94c` of `command-amp-and-gnar-mega`, against the
[umbrella contract](../plans/2026-08-08-silent-failure-campaign.md) rev 2 and the
[campaign runbook](../plans/silent-failure-runbook.md). Doc-only: this commit touches no `src/`, no
gate script and none of R-32's five baselines.*

Every number below was produced by running the named instrument on this tip. Where an umbrella
criterion is not fully discharged this report says so and names the artifact that carries the gap; it
rounds nothing up.

---

## 1. The R-01 matrix, run in full on `067c94c`

| # | Command | Verdict | What it read |
|---|---|---|---|
| 1 | `pytest` | **GREEN** | 7977 passed, 0 skipped, 0 xfailed. Row 1's second half holds: `tests.collected` is pinned in the fingerprints receipt, `48d5f16` declares 55 new node ids and `067c94c` declares 84, and pinned + 55 + 84 is the number `pytest` reports. |
| 2 | `golden_snapshot.py compare scripts/golden_baseline.json` | **GREEN** | `OK: snapshot identical`. The pair jurisdiction has nothing standing. |
| 3 | `golden_snapshot.py compare scripts/golden_coupled_baseline.json` | **RED as a raw command; explained** | 3 differing leaves, 2 qualifying. All three are claimed by the committed allowlist `expected-golden-diff-P4-H2-ccscope.json`, and `tests/test_coupled_golden_allowlist.py` — which is R-01 row 3's real pass condition, *every diff explained* — is green. See gap **G1**. |
| 4 | `acceptance_matrix.py --json` | **GREEN** | exit 0, `passed: true`, 10 scenarios. |
| 5 | `champion_optimizer_matrix.py --json` | **GREEN** | exit 0, 173 registered / 173 exercised / 173 passed / 0 withheld / 0 failed. |
| 6 | `black --check src/ tests/ scripts/` | **GREEN** | 636 files unchanged. |
| 7 | `pylint src/ --fail-under=9` + `pylint_ratchet.py --check` | **GREEN** | rated 9.61/10; ratchet reports 197 files at or above their recorded score. |
| 8 | `bench_coupled_optimizer.py --fixed-work --isolate --json` | **GREEN** | All four scenarios. Every counter family, the residual and the score reproduce the pinned value exactly on `cassiopeia_3champ`, `cassiopeia_5champ`, `mundo_3champ` and `syndra_mandate_3champ`; no run voided, none truncated. |
| 9 | `repin_corpus.py --check` | **GREEN** | 18 non-legacy scenarios executed at the merge-base anchor; count equals `corpus.non_legacy_count`. |
| 10 | `pytest tests/test_survival_kernel.py` | **GREEN** | 34 passed. |
| 11 | `bench_coupled_optimizer.py --fixed-work --isolate --no-compiled --json` vs row 8 | **GREEN** | `routing_divergences` is the empty tuple on all four scenarios; identical winner and identical score both ways. |

`plan_audit.py` (R-37, riding row 1 through `tests/test_plan_audit.py`): **exit 0 — 8 plan documents
clean.** All three checks pass: citation fragments, both golden-figure prongs, and decision-inventory
equality.

---

## 2. Phase commit ranges

The campaign is the 400 commits in `584071e..067c94c`. Ranges are inclusive of the right-hand sha.

| Phase / lane | Range | Commits | Ends on |
|---|---|---|---|
| Phase 0A — gate hardening (L0) | `584071e..54c8894` | 43 | the Shape table naming the three counter surfaces 0A.3 built |
| B0.5 — Phase 5's `cast_dependency` leaf (L6) | `54c8894..4beab65` | 1 | the campaign's one backwards edge, merged before 0B's C6 |
| Phase 0B — six corrections C1…C6 (L1) | `4beab65..4bc1572` | 21 | the fingerprints receipt reading the tree six corrections made |
| Phase 5 — cast dependencies (L6) | `4bc1572..146a69c` | 47 | the two escalated defects getting a ledger the re-capture cannot absorb |
| Phase 2 — trigger bus (L2) | `146a69c..6459667` | 32 | the trigger-link comment correction |
| Phase 1 — coverage evidence (L3) | `6459667..b9c5696` | 20 | a packet the builder emits owing evidence to somebody |
| Phase 3 — behaviour rules (L4) | `b9c5696..ac1ba4e` | 114 | the fingerprints receipt reading the tree four phases made |
| Phase 4 — program engine + boundary (L5) | `ac1ba4e..067c94c` | 122 | H2's shipped default on the routing path |

43 + 1 + 21 + 47 + 32 + 20 + 114 + 122 = 400.

---

## 3. `[H]` dispositions, as recorded in the umbrella

| `[H]` | Recorded disposition | Where it is written | Consequence carried |
|---|---|---|---|
| **H1** — Carve and Vile Decay to coupled-authoritative | **Unanswered; deferred with its consequence stated.** | Umbrella `[H]` table, *Cost of deferring* | Phase 4's mechanic stage shipped **four of the seven** authority moves (Hypershot, Abyssal, Bloodsong, Shadowflame). `black_cleaver.carve` and `bloodletters_curse.vile_decay` still declare `SPLIT` in `trigger_stream.CAPABILITIES` on this tip. |
| **H2** — `CcScope` for Syndra E | **Answered: *deferred, default shipped*, 2026-08-13 at Phase 4 S7.** | Umbrella `[H]` table, H2 row | Command stays `SPLIT`; `CcScope.Unreviewed` resolves to `SingleTarget` on the pair defender with a disclosure naming the ability; `HolderStacking` fails closed to `PER_HOLDER`. Landed at `067c94c`; the two payload fields are gap **G1**'s standing diff. |
| **H3** — amplification as support value | **Unanswered; nothing blocks.** | Umbrella `[H]` table | Pinned by a sentinel; `support_value` unit mixing is a characterization test and is excluded from every coverage expectation (D-14). |
| **H4** — four dead effect tags, six self-referential ones | **Unanswered.** | Umbrella `[H]` table | Ten tag-claims sit on Phase 1's frontier with explicit reasons; the members are enumerated in `docs/behavior-frontier.json`'s `h4_tags` block. |
| **H5** — scope the compiled-kernel extension | **Answered: SCOPED**, recorded at `2662b93`, superseding the earlier DESCOPED note at `b6f3a7c`. | Umbrella `[H]` table, H5 row | The stage landed after Phase 4 S7 (`aff5611` kernel, `e4ef0b2` declaration beside the refusal, `e6feed9` the one-symbol D-98 flip). Its effect is visible in row 8: `syndra_mandate_3champ`'s residual fell from the 1422 the campaign carried for the life of H5 to 98. |
| **H6** — the missing chill marker | **Answered: Phase 5 ships the audit with a dated acknowledged gap; H6 itself is not resolved.** | Umbrella `[H]` table, H6 row | `docs/cast-dependency-audit.json`'s `acknowledged_gaps` carries exactly one entry, `enhanced_consume`, dated 2026-08-10, decision D-88 / H6. |

---

## 4. Baseline re-captures, with the receipts each enumerated

R-17/R-32/D-97 held throughout: **zero commits in `584071e..067c94c` touch both `src/` and one of
R-32's five baselines**, checked by walking every commit's name-only file list against the five paths.

| Commit | Jurisdiction | Differing / qualifying | Receipts |
|---|---|---|---|
| `1483b46` | Phase 0 boundary, **pair** half | 1 differing, 1 qualifying (`absent_to_value`, the `recast_of` leaf C6 added) | 1 — `oracle-C6-leaf138.json` |
| `51db3f6` | Phase 0 boundary, **coupled** half | 215 differing, 191 qualifying across 3 scenarios (mandate_abyssal_curse_roster 53/53; syndra_custom_order_120 80/69; syndra_custom_order_60 80/69) | 206 committed `oracle-*.json`, matched on the `scenario` + `leaf_path` pair; every one of the 191 covered |
| `3a74735`, `c88d25a` | Phase 1's coverage classification receipt, re-captured at Phase 3's 3.8 flip (against the `755ce70` before-image) | per-slice, against `expected-coverage-diff-3.8.json` and siblings | the R-36 allowlist mechanism, not oracle receipts |
| `a966532` | Phase 3 boundary (covering Phases 2, 1, 3 **and** 5), **coupled** half only — the pair baseline had nothing to absorb | 104 differing, 102 qualifying, partitioned exactly 24 + 14 + 64 by three committed allowlists | 102, one per qualifying leaf, matched literally on `leaf_path`. Verdicts as written: 79 `new_value_correct`, 15 `old_value_correct`, 8 `both_wrong` — the 23 dissents adjudicated in `escalated-defects-P5-retire.json`, the 3.8 allowlist's `dissents` block, and the integration report |
| `c2b3d88` | Phase 4 boundary, **coupled** half only | 124 differing, 106 qualifying | 106, all answered: 43 `oracle-P4B-*`, 30 `oracle-S6S7-*`, 4 both, 3 `oracle-P4-arbitrate-*`, 11 the `P4C-C1` whole-series re-adjudication, and 13 `combat/dispositions` blocks declared `NOT_OWED_NO_OLD_VALUE` by three allowlists and carrying a `new_value_correct` receipt each anyway |
| `8357432` | correction to the exact-baseline note the re-capture landed with | 0 executable | receipt-only |

`golden_coupled_exact.json` moved **no value** at either the Phase 3 or the Phase 4 boundary: its
per-attacker totals are byte-identical across both, which is the bit-exact evidence that no computed
number moved even where receipt structure re-valued.

---

## 5. Final frontier counters

**Behaviour frontier** (`scripts/behavior_frontier.py --check`, exit 0, `docs/behavior-frontier.json`):

| Counter | Value | Bound | Met |
|---|---|---|---|
| 1 — runtime item-name dispatch | 0 | 0 | yes |
| 2 — claim-prose sites | 21 | 21 | yes, net of the committed Class C exclusions Amendment A ruled |
| 3 — undeclared registry entries | 0 | 0 | yes |
| 4 — uninterpreted `(family, lane)` / `PAIR_ENGINE` | gross 0, deferred 0, net 0 | 0 | yes |
| 4 — uninterpreted `(family, lane)` / `RECEIPT_WALK` | gross 14, deferred 14, net 0 | 0 | met **net of 14 deferral rows**; see gap **G4** |

`zero_policy_frontier.forbidden_input_fallbacks` is **empty** — D-24's source assertion over
`champions/`, the guard its declared default only holds with, finds no `.get(key, <literal>)`
feeding a damage formula.

**Migration frontier** (`scripts/migration_frontier.py --check`, exit 0, `docs/migration-frontier.json`):

| Counter | Value | Target | Met |
|---|---|---|---|
| 5 — `SurvivalAction` constructors outside `program/compile.py` | 1 (`survival/actions.py`, the declared survivor) | 1 | yes |
| 6 — `round(` inside `program/` | 0 | 0 | yes |
| 6 — `round(` inside the kernel (non-increasing ratchet) | 75 | ≤ 118 baseline | yes |
| 7 — `id()`-keyed cache sites | 0 | 0 (from a baseline of 3) | yes |

**Cast-dependency audit** (`scripts/cast_dependency_audit.py`, `docs/cast-dependency-audit.json`):
`passed: true`, 29/29, 0 withheld, 0 failures; 4040 option states walked over 173 champions; one
dated acknowledged gap (`enhanced_consume`); `order_override_frontier` at 7 entries, all
`dps_tiebreak`, 0 unclassified.

---

## 6. The eleven umbrella success criteria, one by one

### 1. The invariant holds by machine — **PARTIALLY DISCHARGED**

Discharged, by machine: `serialize_leaf` is the single writer of both a payload leaf and its
`dispositions` entry; `tests/test_payload_dispositions.py` and `tests/test_view_leaf_provenance.py`
are green (27 tests) and assert two-way key-set equality over the whole `/api/calculate` response,
its combat receipt, `/api/bis` and `/api/optimize` — no block list, no hand-maintained path list.
Live requests run for this report confirm it end to end: `/api/calculate` returns two disjoint maps
(492 entries at the root, 495 on `combat`), `/api/bis` 18 978 entries, `/api/optimize` 6, every entry
well-formed. `Quantity.__add__` carries the propagation row, and `Disposition` survives as its tag
projection.

**Not discharged:** every disposition every production path emits is `MEASURED`. Verified
independently for this report — the three live payloads above yield the spelling set `{MEASURED}`
and the view-tag set `{applied}`, and `grep -rn "OutcomeLedger(" src/` returns **nothing**: the
record that produces the other three dispositions has no construction site outside its own module,
so the walk runs on `ScoreLedger`/`ReceiptLedger` and no request can reach a `STRUCTURAL_ZERO`,
`WITHHELD` or `STARVED` leaf. The wire shape, the renderer and the propagation algebra are real and
gated; the *production* half is fixture-only. Carried open at
`escalated-defects-P4-S9.json` → `no_production_path_emits_a_non_measured_disposition`, whose
`for_the_phase_owner` line asked the phase to schedule the ledger join or record a fixture-only
discharge. Neither happened. Gap **G2**.

### 2. The incident cannot recur silently — **DISCHARGED**

All nine mutation tests run and pass as permanent seams, not one-time demonstrations:
`test_M1_renaming_the_pair_engine_effect_accessor_is_noticed`,
`test_M2_deleting_the_pair_side_pricer_is_noticed`,
`test_M3_removing_the_command_packet_literal_is_noticed`,
`test_M4_dropping_owner_from_a_dual_sided_packet_is_noticed`, and M5–M9. Each resolves against the
**live** tree first and then against the mutated one, so a real rename in `src/` turns the suite red
rather than the suite merely proving a shim raises. The M4 seam was additionally driven by hand for
this report: `_packet_call_without_owner` removes the `owner=` keyword from the
`Imperial Mandate — Command` packet call and nobody else's, line-precisely.

Phase 2's **A9** — `test_a9_every_declared_stream_is_load_bearing` plus
`test_a9_has_a_permanent_injection_seam` — passes with its R-05 red on demand.

Phase 0's criterion-18 roster fixture (`tests/test_command_amp_roster.py`, 10 tests) passes and
fails on a **number**: the holder total and the ally total are each pinned and each differs from the
no-Command control, the amplification row is the sourced fraction of its window, and the holder is
asserted not amped twice.

### 3. Six, not five — **DISCHARGED**

`golden_snapshot.cross_participant_producers()` returns exactly six, read from the semantic and never
typed: Abyssal Mask — Unmake, Black Cleaver — Carve, Bloodletter's Curse — Vile Decay, Bloodsong —
Expose Weakness, **Dream Maker — Blue Dream Bubble**, Imperial Mandate — Command.
`item_support_effects._check_cross_participant_authority` enforces `owner` present **iff**
`Authority == SPLIT` at packet construction; `tests/test_item_support_effects.py` carries the
seventh-producer negative in both directions ("a seventh producer is a row the moment its capability
parses" and "a seventh producer cannot ship undeclared even if it never runs").

### 4. The retired figure is gone and nothing replaces it — **PARTIALLY DISCHARGED**

The plans half is machine-gated and green: `plan_audit.py`'s check 2 runs both prongs — a value match
against the retired literals and against every live count read at run time from
`campaign-fingerprints.json`, plus the proximity-marker prong — over all 8 plan documents, and
reports clean. The retired scenario-entry figure appears nowhere.

**Not discharged:** the criterion also binds receipts and commit bodies, and that half is an
integration-agent scan with no gate behind it. Run for this report over `docs/receipts/*.json` and
every commit body in the range, matching the live shape counts read from the receipt itself, nine
sites state a golden or coupled-golden shape count of a **committed** baseline outside its sole home:

* `oracle-0A.2-golden-leaf0.json` — `golden.entries` and `golden.numeric_leaves`
* `oracle-P4B-leaf59.json` — `coupled_golden.leaves`
* `oracle-S9-leaf11.json` — `coupled_golden.numeric_leaves`
* `escalated-defects-P4-boundary.json` — `coupled_golden.leaves`
* `expected-golden-diff-P4-H2-ccscope.json` — `coupled_golden.leaves`, as the old value of the leaf it allowlists
* commit bodies `1483b46`, `c2b3d88`, `8357432`, `067c94c`

Every one of the nine is structurally forced by another rule: an oracle receipt must state the two
values of the leaf it adjudicates (R-19), an allowlist must state the expected old and new value of
each path it claims (R-17), and a baseline-move commit must give one line of cause per moved value
(R-34). The `/metadata/fingerprint/*` leaves are themselves leaves of the snapshot, so any receipt
that adjudicates or allowlists one must restate it. Criterion 4's exemption covers "a measured diff
count from a positive control or an allowlist" and does not reach a shape figure quoted as a leaf
value. This is a rule collision the umbrella did not anticipate, not a drifted figure — but it is
not what the criterion says, so it is recorded rather than rounded up. Gap **G5**. (The other
coincidences the scan surfaced — a bench rung ceiling and an ability-power value that happen to equal
`golden.entries`, and the small integers 0, 13 and 82 — are collisions, not restatements.)

### 5. Every gate means what it says — **PARTIALLY DISCHARGED**

Ten of R-01's eleven rows are green on this tip (§1). Zero pair-engine golden diffs stand anywhere:
`compare scripts/golden_baseline.json` reads `snapshot identical`, so the second clause holds
outright.

**Not discharged:** row 3 is not green at the campaign's final tip. Three coupled leaves stand, all
claimed by `expected-golden-diff-P4-H2-ccscope.json`, and no closing baseline re-capture followed
`067c94c`. The allowlist mechanism is exactly what R-17 prescribes *between* boundaries, and the
mechanised join `tests/test_coupled_golden_allowlist.py` is green — but the campaign's last commit is
a semantic slice, not a boundary re-capture, so the criterion's "all eleven rows green at every phase
boundary" has no boundary to be true at here. Gap **G1**.

### 6. The hand-maintained adequacy sets are gone — **DISCHARGED**

The five hand name sets and the four raw-row scanners have **zero occurrences in `src/`**, asserted
by `RETIRED_SYMBOL_HOMES` (every entry `[]`) with an injection seam that goes red if any is
reinstated anywhere, plus a prose-level scan (`test_no_retired_symbol_is_named_anywhere_in_src_not_even_in_prose`).
`tuple_incapable_items()` derives 10 members and `enriched_view_items()` derives 6 — Fimbulwinter is
a member of the latter, as D-03 ruled — each equal to its docstring enumeration.
`ledger_projection.LEDGER_CONDITIONS` holds **ten** declared adequacy conditions and `pipeline.py`'s
tuple gate is now projection satisfaction over them rather than a conjunction kept at the call site,
so all ten of D-38's clauses are derived. Every replacement landed beside its legacy set with an
asserted delta before a one-symbol flip (D-98) — the front-door tuple (`c419480` → `b4eb20d`), the
compiled-walk hand set (`a6e264b` → `fb9027a`), the H5 compiled declaration (`e4ef0b2` → `e6feed9`).

### 7. Declarations outrank prose — **PARTIALLY DISCHARGED**

Phase 3's counters read 1 = 0, 3 = 0, counter 4 net 0 on both `PAIR_ENGINE` and `RECEIPT_WALK`, and
counter 2 at 21 against its bound of 21 — the three `bis.BIS_CERTIFIED_DEFENSIVE_EFFECTS` residuals
Amendment A left as a live gap were retired at `88f464a`/`c70d765`, so the clause is now met rather
than merely bounded. Phase 4's counters 5–7 are at their stage targets (§5). Every exclusion,
deferral and reason list is committed in `docs/behavior-frontier.json` /
`docs/migration-frontier.json` and diff-gated by set equality, never inside the measuring tool.

**Not discharged:** Amendment B's second sentence. The 14 `RECEIPT_WALK` deferral rows each record
`retires_at: "Phase 4 S3 — one kernel, five views"`, and Phase 4 has completed through S10 and its
boundary. The rows are still present and still `owed_to` that stage; counter 4's receipt-walk lane is
"met **net of** 14 of 14" rather than retired. Phase 4's exit does not re-assert them retired,
because nothing did. Gap **G4**.

### 8. One engine prices one mechanic — **PARTIALLY DISCHARGED**

Discharged: one kernel invoked exactly `len(passes)` times per request, asserted as a number rather
than a call-site count (`tests/test_program_walk.py`, 25 tests green, including the Catalyst
two-pass case). One `SurvivalAction` constructor — migration counter 5 reads 1 against a target of 1,
the declared survivor being `survival/actions.py`'s default row. Five views, none of which re-runs
arithmetic, asserted rather than documented (`tests/view_purity.py`, `tests/test_program_views.py`).
Zero mixed-view sums — `Tagged.__add__` refuses a mixed fold structurally. The pairing divergence
ledger is empty of unreceipted rows: `trigger_stream.DIVERGENCES` is `{}`, and
`test_a_divergence_reference_that_resolves_in_nothing_is_still_rejected` keeps that emptiness from
making `divergence_ref` a field nothing checks. Measured on this tip, `trigger_stream.CAPABILITIES`
holds 48 declarations of which 6 are `PAIRED` — `abyssal_mask.unmake`, `bloodsong.expose_weakness`,
`shadowflame.cinderbloom`, `black_cleaver.carve`, `bloodletters_curse.vile_decay` and
`imperial_mandate.command` — which is the deliberately revised end state the umbrella's rev-1
retirement row records, not the emptied registry rev 1 wanted.

**Not discharged:** "at most one `APPLIED` contribution per `(mechanic, subject, event_id)`" is
enforced where the contribution is written, on `OutcomeLedger`, and unit-tested there
(`tests/test_outcome_state.py`, 32 green) — but `OutcomeLedger` has no construction site in `src/`,
so the rule never fires over a real fight. Same root cause as **G2**; recorded as **G3**.

### 9. The public schema is derived — **DISCHARGED**

`PARTICIPANT_LEDGER_CONTRACT["phases"]` is computed by `_ledger_phases()` walking `TransitionRank` in
declaration order with no hand-listed member, and it publishes seven names including
`death_or_terminal_cutoff`, the one carried by the producer-less `TERMINAL` rank.
`CAPABILITY_SCHEMA_VERSION` reads **4**, the end of D-63's chain, and each of the four values has
exactly one owning commit: 1 at 0A's derivation, 2 at 0B's C4 (`AURA_ARM`, whose publication is the
first proof the derivation works), 3 at Phase 3's 3.8 coverage flip, 4 at Phase 4's S9. S6's rank
split was asserted payload-neutral and took no value.

### 10. Declared cast dependencies reproduce the seeds they retire — **DISCHARGED**

Four seeds retired (`23ab54d` Syndra, `4b6caaf` Aatrox, `3a030ac` Jhin, `ad9ba79` Aphelios) with
zero golden diffs, and the positive control that makes "zero diffs" mean something is committed
rather than claimed: `campaign-fingerprints.json`'s `demonstrated_red.P5_syndra_seed_positive_control`
carries the throwaway commit's sha, the sha256 of its failing output, the perturbation (deleting
`CAST_ORDER_OVERRIDES["Syndra"]` and emptying her `CAST_DEPENDENCIES`), the gate it turned red and
the section it moved — proving the pair baseline is sensitive to that champion's cast order.
`tests/test_syndra.py::test_the_positive_control_is_recorded_in_the_fingerprints_receipt` reads it.

### 11. Governance is closed — **DISCHARGED, with the `[H]` clause read as written**

`plan_audit.py` check 3 passes: `docs/receipts/decision-inventory.json` holds **78** declared ids —
the number the umbrella's manifest states — of which **8** are split (D-38, D-44, D-45, D-47, D-49,
D-63, D-68, D-101), each naming every one of its halves, and the **23** reserve gaps (D-15…D-19,
D-27…D-29, D-39, D-53…D-59, D-73…D-79) are asserted absent rather than missing. The inventory is
derived from the manifest by the instrument and fails when the two disagree, so no prose read is
involved. The remaining clauses of the criterion — phase headers matching the manifest verbatim, no
phase document re-ruling a decision, no cross-phase number appearing twice with two values — are not
machine-checked, and the criterion does not ask them to be: it names only the id-coverage and
split-halves clauses as the machine's.

The `[H]` clause reads: every `[H]` is answered and recorded in the umbrella, or its dependent slice
is explicitly descoped there with its criterion restated. H2, H5 and H6 carry recorded rulings. H1,
H3 and H4 are unanswered and each carries its deferral consequence in the same table — H1 naming the
four-of-seven split, H3 naming the sentinel, H4 naming the ten frontier tag-claims. H1's restatement
is the thinnest of the three: it states what Phase 4 shipped rather than restating a criterion, and a
reader who wants the descoped criterion must infer it from the semantic-authority table's two `H1`
rows. Recorded as **G8**, not as a failure.

---

## 7. Residual gaps

| # | Gap | Artifact | Blocks |
|---|---|---|---|
| **G1** | R-01 row 3 is not clean at the final tip: 3 coupled diffs, 2 qualifying, both `absent_to_value` on H2's two new payload fields. No closing baseline re-capture followed `067c94c`. | `expected-golden-diff-P4-H2-ccscope.json`; join gated by `tests/test_coupled_golden_allowlist.py` | Criterion 5. Closing it is one integration-agent re-capture commit touching only the coupled baselines and the fingerprints golden blocks; both occurrences are adjudicated **by citation** under the R-15 amendment of 2026-08-14, so no oracle receipt is owed and the re-capture is not blocked by R-19. |
| **G2** | Every disposition any production path emits is `MEASURED`; `OutcomeLedger` has zero construction sites in `src/`. | `escalated-defects-P4-S9.json`, entry `no_production_path_emits_a_non_measured_disposition`, open, with a live reproducer and an inverted reproducer for closure | Criterion 1. Closing it is a kernel-ledger join plus retyping `AttackerOutcome` and `ObjectiveFold` to carry `Quantity` — a slice no phase budgeted. |
| **G3** | D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` uniqueness never fires over a real fight. | same entry; re-raised by the second R-35 pass | Criterion 8. Same fix as G2. |
| **G4** | The 14 `RECEIPT_WALK` deferral rows record `retires_at: Phase 4 S3` and were never retired; counter 4 is met net of them. | `docs/behavior-frontier.json`, `counters.counter_4.deferrals` | Criterion 7 / Amendment B's exit clause. |
| **G5** | Nine sites state a committed baseline's golden shape count outside `campaign-fingerprints.json` — five receipts and four commit bodies, every one forced by R-19, R-17 or R-34. | enumerated in §6 criterion 4 | Criterion 4's non-plan half. Resolving it needs an umbrella amendment carving out a leaf's own adjudicating receipt, not an edit to the nine sites. |
| **G6** | 51 adverse oracle verdicts stand repo-wide (of 81 across 550 receipts), and no R-01 row goes red if a future capture pins over one. Includes one filed *after* the capture it opposes. | `escalated-defects-P4-integration-final.json`, open; enumerated and pinned by `tests/test_standing_oracle_dissents.py` (60 tests green) | Runbook criterion 9's repo-wide reading. The receipts are gated as an artifact; the *blocking* half of R-19 is not mechanised outside the two Phase-4-boundary scans. |
| **G7** | Two further open Phase 4 escalations: the bit-exact clause names four bench scenarios the exact baseline does not hold; `ReceiptWalk.reason` reaches no receipt, log line or payload. | `escalated-defects-P4-S10.json`, entries 2 and 3 | Phase 4's criteria 14 and 16's fallback-cause clause. |
| **G8** | H1, H3 and H4 unanswered; H1's descope states what shipped rather than restating the criterion. | umbrella `[H]` table | Criterion 11's `[H]` clause, read strictly. |
| **G9** | One dated acknowledged gap, by design: `enhanced_consume` has no producing champion. | `docs/cast-dependency-audit.json`, `acknowledged_gaps` | Nothing — H6's recorded ruling is that Phase 5 ships exactly this. |

---

## 8. What the campaign delivered

Six layers failed independently on one item's amplification and produced a zero with no error. On
this tip: the amplification is declared once for both engines, its authority is a typed field a
packet cannot ship without, the predicate that decides what an immobilize is has one home, the four
dispositions are an algebra whose propagation is `__add__` rather than a convention, every published
number on all three score-serving endpoints carries exactly one entry naming which of the four it is,
and deleting either half of Command fails on a number rather than on a sentence. What remains
undone is written above with its artifact and its reproducer, and none of it is a claim standing
where an implementation is missing — which was the campaign's whole subject.

---

## 9. Corrections, and the closing remediation pass

*Appended 2026-08-14 on `1db568c`, after an independent R-35 pass over this report and the two
commits that carried it returned **nine criteria NOT DISCHARGED** and six findings of behaviour the
commit bodies did not mention. Everything above this line is left exactly as it was written on
`067c94c`: a report that edits itself to match what turned out to be true is a report whose earlier
readers were told something nobody can now recover. Corrections first, then the re-grade.*

### 9.1 Claims above that this repository now contradicts

| Where | What it says | What is true now |
|---|---|---|
| Section 1 row 3, section 6 criterion 5, **G1** | row 3 is "RED as a raw command; explained", and no closing re-capture followed `067c94c` | The closing coupled re-capture landed at `1db568c`. `compare scripts/golden_coupled_baseline.json` reads **`snapshot identical`**, and all eleven R-01 rows are green together for the first time since Phase 4 S7. |
| Section 6 criteria 1 and 8, **G2**, **G3** | `OutcomeLedger` has zero construction sites in `src/`, so D-62's uniqueness never fires over a real fight | It is the receipt walk's companion since `69e7323`. Over the five committed coupled scenarios the ledger records 314 slots, claims 290 applied contributions with 0 unidentified, and observes 24 refusals. **G3 is closed.** G2's emission half is not, and its block is now named exactly rather than costed vaguely -- see 9.3. |
| **G5** | resolving it "needs an umbrella amendment ... not an edit to the nine sites" | Still true of the criterion's wording, and half wrong about the remedy: the *scan* was the missing piece. `scripts/sole_home_scan.py` (`1e209e2`) mechanises criterion 4's second half, so a tenth site fails a gate. The residue is pinned as a number, and it fell to eleven rows across six sources when the closing re-capture superseded a figure -- a fall, not a discharge. |
| **G6** | "51 adverse oracle verdicts stand repo-wide (of 81 across 550 receipts)" | The population was 552 when this sentence was written and is 552 now; 81 and 51 are unchanged and were re-derived. The 550 was superseded one commit later by `ce34610`, inside the same slice group, and nothing gated a figure inside this report. That is a small instance of exactly what section 6 criterion 4 is about, in a document arguing about it. |
| **G8** | H1, H3 and H4 carry a deferral consequence rather than a restated criterion | Fixed at `1de067b`: each row now names its dependent criterion and states how it is read under the deferral, in H5's shape. **G8 is closed.** |

### 9.2 What the remediation pass changed

| Commit | Subject |
|---|---|
| `47c5218` | `live_damage` is a diagnostic and stops aliasing the applied outcome field |
| `ff5e31d` | the rule that refused an action owns its receipt, not the rule that followed |
| `69e7323` | the receipt walk runs the write-once outcome ledger |
| `1e209e2` | criterion 4's second half stops being an agent reading |
| `4267fd3` | a receipt's date is read however the receipt spells it |
| `98351d1` | two cached-data defects an oracle receipt asserted as an aside |
| `1de067b` | H1, H3 and H4 get the criterion restatement criterion 11 asks for |
| `7d2975d` | a deferral whose stage has shipped is a debt and now says so |
| `1db568c` | the closing coupled re-capture |

Two defects the ledger join surfaced are worth naming here, because neither was visible until a walk
drove that record. `OutcomeLedger._WRITE_ALIASES` mapped the diagnostic `live_damage` onto the
`applied` outcome field beside `damage` -- two numbers that agree exactly when nothing overkilled.
And the kernel's trigger arm skipped without `preserve_reason`, so a redirect child Knight's Vow had
already cancelled published `trigger_event_skipped`, the consequence, in place of
`holder_health_gate`, the cause, which was the only one of the two that named a rule.

### 9.3 The gaps, re-graded

| # | State | Note |
|---|---|---|
| **G1** | **CLOSED** | `1db568c`. Row 3 green; the exact baseline moved no value, which is the bit-exact evidence that nothing computed moved across the pass's three `src/` commits either. |
| **G2** | **OPEN, and the block is now named** | Not budget: **adjudication**. Publishing a refused row's outcome as `StructuralZero` moves 38 leaves in the coupled baseline, each a `text_change` on a disposition string. R-15's 2026-08-14 amendment adjudicates by citation only a *membership* transition, and no oracle built by R-18's export can decide whether a zero the walk refused is `MEASURED` or `STRUCTURAL_ZERO` -- that is a question about this campaign's own vocabulary, which the export exists to keep out of an investigator's hands. The slice needs a ruling, not a lane. |
| **G3** | **CLOSED** | `69e7323`. |
| **G4** | **OPEN, and now gated** | The rows cannot retire while G2 is open: the retiring stage's mechanism is the projection G2 lacks, and re-dating them is Amendment B's to do rather than a lane's. What changed at `7d2975d` is that a deferral whose stage has shipped is declared **overdue** with a blocker naming an artifact, and the gate refuses an undeclared one -- so the next stage that passes without retiring its rows fails on the commit that passes it. |
| **G5** | **OPEN, and now counted** | `1e209e2`. See 9.1. |
| **G6** | **OPEN, one hole closed** | The supersession rule reads a receipt's date under any of eleven live spellings since `4267fd3`, not two. Twenty-three dated receipts were being counted as undated, and an undated dissent is treated as cleared by any same-leaf answer. The standing set does not move -- 51 either way -- so this closed a hole rather than correcting a verdict. |
| **G7** | **OPEN, unchanged** | Not in this pass's scope. |
| **G8** | **CLOSED** | `1de067b`. |
| **G9** | **OPEN by design, unchanged** | H6's recorded ruling. |
| **G10** | **NEW, OPEN** | Criterion 1's clause "`static/js/app.js` takes exactly one budgeted change at S9" is false, and neither this report nor the commit bodies said so. Three commits touched the file in the campaign range: `bf4a6d3` (+26), `44331c7` (+52/-10, the withheld marker the clause names) and `f25dcfa` (+13/-5, a row-classification refactor). The budget overran by two and nothing counted it. Reverting a shipped refactor to satisfy a budget clause would be worse than recording the overrun, so it is recorded. |
| **G11** | **NEW, OPEN, filed and gated** | Two cached-data defects an oracle receipt asserted as an aside and no commit body mentioned: Imperial Mandate's `simpleDescription` describes a different item, and one ability-haste phrase is atomized three ways. Neither reaches a damage number, and the gate asserts that rather than saying it. `docs/receipts/escalated-defects-cached-data.json` (`98351d1`). |

### 9.4 The re-grade

Criteria **3, 6, 9, 10** are unchanged and discharged. **8** and **11** move to **DISCHARGED**.
**5** moves to **DISCHARGED**: all eleven rows are green at the closing boundary, and there are zero
pair-engine diffs anywhere. **1**, **4** and **7** remain **PARTIALLY DISCHARGED**, each on one named
clause with a named blocker -- G2 for criterion 1, plus G10 on its frontend clause; G5 for criterion
4; G4 for criterion 7 -- and each of the three now fails a machine rather than a reader if it grows.

Two of the three open clauses need an umbrella ruling and cannot be closed by an implementation lane
at all: how a disposition transition is adjudicated (G2, and G4 behind it), and whether a leaf's own
adjudicating receipt may state that leaf's value (G5). That is the honest end state -- not "done",
and not a claim standing where an implementation is missing.

---

## 10. The second remediation pass

*Appended 2026-08-14. A second independent R-35 pass over slice group
`campaign-close` — this time over `8d4695e..94faa95`, which includes the first
remediation — returned **six criteria NOT DISCHARGED** and **six findings of
behaviour the commit bodies do not mention**. Everything above this line stays
as written, for the reason section 9 gives.*

### 10.1 What the six findings were, and what happened to each

| Finding | Disposition | Where |
|---|---|---|
| `_superseding_value` resolves by **filename order**, not by "later" — the mechanism `1db568c`'s body sells is not the mechanism that shipped | **fixed and gated** (`a6725ad`) | supersession is now a `supersedes` block an allowlist declares; two claimants raise, an undeclared claim is inert |
| `COMPLETED_STAGES` is a literal inside the measuring tool and the sole trigger of the overdue rule | **fixed and gated** (`6988301`) | `docs/receipts/campaign-stages.json`; shippedness derived from commit subjects |
| The write-once ledger is a live 500 risk on all three serving endpoints | **documented, open** (`2c79bd0`) | `docs/receipts/escalated-defects-ledger-join.json`, and an owed ruling |
| `4267fd3` reindented a 194-line escalation ledger while describing one changed field | **reverted** (`2e302ad`) | `git diff 4267fd3^` over that file is now one line |
| Three bench allocation peaks above their pins with no body naming a memory effect | **fixed and gated** (`25a2edb`) | measured beside each pin; the named candidate ruled out by measurement |
| `1de067b`'s 3-line diff carries ~9.8 KB of ruling text | **documented** (this section) | a property of markdown tables holding whole rulings on one line; the content is what criterion 11 asked for |

### 10.2 The gaps, re-graded again

| # | State | Note |
|---|---|---|
| **G2** | **OPEN — now an owed ruling with a name** | `rulings-owed.json`, `how_a_disposition_text_change_is_adjudicated`. Unchanged in substance. |
| **G4** | **OPEN — and the overdue rule now comes due on its own** | The literal that triggered it moved out of the tool; a deferral may no longer name a stage nothing declares, and shippedness is read from the tree. The rows still cannot retire while G2 is open. |
| **G5** | **OPEN — now an owed ruling with a name** | `rulings-owed.json`, `whether_a_leafs_own_adjudicating_receipt_may_state_that_leafs_value`. Residue unchanged at eleven. |
| **G10** | **OPEN — now an owed ruling with a name** | The frontend budget clause. A lane may not amend a criterion and should not revert a shipped refactor to satisfy one. |
| **G12** | **NEW, OPEN, filed and gated** | The ledger join's raise set reaches three serving endpoints uncaught. |
| **G13** | **NEW, CLOSED** | Runbook criterion 12 was unverifiable, not failed: the ownership map lived only in a plan section. `docs/receipts/lane-ownership.json` is the map outside the plans, and its gate found three writers the map does not list — none a violation, all recorded. |
| **G14** | **NEW, OPEN and measured** | Runbook criterion 11's first clause now has a denominator: 63 slice-group tags derived from commit subjects, one covered, **62** open. Forwards the clause holds by machine; backwards it is measured. |

### 10.3 What is left, and who it belongs to

Four questions, collected in `docs/receipts/rulings-owed.json` with the
criterion each blocks, its measurement artifact, and — the half that matters —
what a lane may **not** do instead. None of the four closes by an
implementation lane trying harder, and all four now have a length rather than
four separate explanations of why work stopped.

The honest end state is unchanged in shape and better in evidence: what remains
undone is written down with its artifact, its reproducer and its owner, and
none of it is a claim standing where an implementation is missing.

---

## 11. The third remediation pass — the sign-off blockers

*Appended 2026-08-14 on `31bce59..1a73f6f`, nine commits, after a Fable sign-off
review withheld sign-off with six **major** findings and three minor ones.
Everything above this line stays as written, for the reason section 9 gives.*

### 11.1 What the pass did, finding by finding

| Finding | State | Where |
|---|---|---|
| **G2** — no production path emits a non-`MEASURED` disposition | **CLOSED** | `4b8779e`, unblocked by umbrella **Amendment E** |
| **G12** — the ledger's raises reach three serving endpoints uncaught | **CLOSED** | `19b03d7`, unblocked by umbrella **Amendment G** |
| **G7**, entry 3 — `ReceiptWalk.reason` published nowhere | **CLOSED** | `5c19b1f` |
| **G7**, entry 2 — the bit-exact clause names a scenario set the instrument does not hold | **CLOSED** | `0f3adca` |
| **G6** — standing dissents invisible to every R-01 row | **half closed, half open and measured** | `9c6adee` |
| **G4** — Amendment B's exit clause undischarged | **RULED**, debt restated at its true size | umbrella **Amendment F** |
| **G5** — eleven forced restatements of a shape count | **CLOSED as a ruled carve-out** | umbrella **Amendment H** |
| **G10** — the frontend change budget clause is false | **CLOSED by amendment** | umbrella **Amendment I** |
| **G14** — the slice groups with no recorded verify verdict | **graded, and its ruling is owed** | `b12a2fe` |
| R-20's missing lines on 8 historical commits | **not actionable** | history; every commit in this pass carries the line |

### 11.2 The two that changed what the calculator does

**A refused transition now publishes the declared zero it is.**  Every
disposition every production path emitted was `MEASURED`, including on the
rows whose `skipped_reason` says the walk refused to price them — the zero was
put there by the refusal, and the map said a rule had produced it.  That is
the campaign's own invariant broken inside the campaign's own receipt.
`survival.outcome_state.outcome_quantity` is now the one verdict, and the
receipt view's three panels publish their outcome fields through it.  **No
published number moves**: `StructuralZero.read()` is `0.0` and the branch is
reached only on a zero, so a live coupled receipt's spelling set is
`{MEASURED, STRUCTURAL_ZERO}` and its 38 declared zeros each carry the walk's
own refusal as their reason.

**A contested outcome reaches the boundary as a named refusal.**  The
write-once ledger's three raises were caught nowhere, so a condition that used
to resolve silently as last-write-wins had become a bare 500 with no receipt
and no named field.  `trigger_stream.StarvedSignal` is the class D-25's one
boundary converts; nothing is absorbed, the ledger still refuses the second
write where it is written, and the D-25 source assertion now ranges over the
class — so catching a *member* somewhere else is as red as catching the base.

### 11.3 What the pass did not close, in its own words

* **G6.**  R-19's blocking half is mechanised repo-wide and a capture that
  pins over a standing verdict now fails a gate.  Of 51 standing dissents, 28
  are blocking; 6 are adjudicated by citation under the R-15 amendment and 22
  stand as open debts, each naming what is owed and the artifact carrying it.
  Re-adjudicating one needs a fresh investigator that has read neither the
  prior receipts nor the escalation, which no implementation lane can be.
* **G4.**  Amendment B named a retiring act that does not exist — a
  `(family, RECEIPT_WALK)` row retires when `interpreters.INTERPRETERS` holds
  that key, and no ledger projection registers one.  The clause is corrected
  rather than carried, the debt is restated in H6's shape with its true
  retiring act named, and the amendment says in terms that it does **not**
  rule the debt acceptable: retiring it is fourteen slices, one per family.
* **G14.**  The residue is graded rather than binary — measured on this tip,
  8 slice groups cite a verdict in their own commit bodies and 63 cite nothing
  anywhere, out of 70 tags with no verdict recorded in the ledger — and the
  question of whether the clause binds the campaign's past is a fifth row on
  `rulings-owed.json`, because a lane may neither re-read "every slice" nor
  commit an owner to sixty-one verification passes.

### 11.4 The R-01 matrix on `1a73f6f`

| # | Verdict | What it read |
|---|---|---|
| 1 | **GREEN** | 8128 passed, 0 skipped, 0 xfailed |
| 2 | **GREEN** | `snapshot identical` |
| 3 | **explained** | 77 differing leaves, 76 qualifying, every one claimed by `expected-golden-diff-campaign-close-dispositions.json`; `tests/test_coupled_golden_allowlist.py` — row 3's real pass condition — green, now including Amendment E's third guard as a machine check |
| 4 | **GREEN** | exit 0 |
| 5 | **GREEN** | exit 0 |
| 6 | **GREEN** | 646 files unchanged |
| 7 | **GREEN** | rated 9.61/10; ratchet reports 197 files at or above their recorded score |
| 8 | **GREEN** | all four scenarios; every pinned counter, residual and score reproduces exactly; no run voided or truncated |
| 9 | **GREEN** | 18 non-legacy scenarios at the merge-base anchor |
| 10 | **GREEN** | 34 passed |
| 11 | **GREEN** | identical winner and identical score both ways on all four |

`plan_audit.py` (R-37): **exit 0 — 8 plan documents clean.**
`sole_home_scan.py --check`, `standing_dissent_scan.py --check`,
`behavior_frontier.py --check` and `migration_frontier.py --check`: all exit 0.

---

## 12. The fourth remediation pass — the close, actually closed

*Appended 2026-08-14 on `86aa1d2..HEAD`, three commits, after a second Fable
sign-off review withheld sign-off with three **major** findings and three minor
ones. Everything above this line stays as written, for the reason section 9
gives.*

### 12.1 What the pass did, finding by finding

| Finding | State | Where |
|---|---|---|
| **Major 1** — the campaign ends without a closing coupled re-capture; row 3 red at the tip, and §9.4's re-grade of criterion 5 names a boundary three later `src/` commits outdated | **CLOSED** | `09956f8` |
| **Major 2** — runbook criterion 11's first clause is measurably unmet and its disposition is an open owed ruling | **OPEN, and it is the one thing left that blocks certification** | `rulings-owed.json`, row 5 — unchanged, and unchangeable by a lane |
| **Major 3** — 22 standing oracle dissents are open debts naming a remedy nobody could begin | **SCHEDULED, with the defect in each prior brief named and measured** | `1414576` |
| Minor — 8 historical commits carry no R-20 line | **not actionable** | history; all three commits of this pass carry the line |
| Minor — the tip re-pinned `tests.collected` outside R-32's carve-out and weakened the S10 inverted test | **disclosed, left standing** | `86aa1d2`'s body; the re-pin reproduces and the load-bearing half is respected |
| Minor — asides, verified accurate | **no action** | every number the reviewer re-ran reproduced |

### 12.2 Major 1, and what a second closing capture cost

The first closing capture (`1db568c`) was followed by three `src/` commits, so
the campaign closed a second time on a semantic slice and row 3 read 77
differing leaves. `09956f8` is the capture that ends it, on `1db568c`'s own
terms: its own commit, no `src/`, the standing allowlisted diffs and nothing
else. The population was enumerated **before** the capture — 77 moved leaves,
0 unclaimed by any committed allowlist, 76 qualifying, transitions
`{text_change: 38, absent_to_value: 38, value: 1}` — and all 76 are disposition
transitions the umbrella's Amendment E adjudicates by citation, so R-19's
precondition is satisfied without an oracle receipt and none may be filed as
though the question were a value question. `golden_coupled_exact.json`
re-captured to a byte-identical digest, which is the bit-exact statement (R-13)
that nothing computed moved across the three `src/` commits the capture absorbs.

One mechanism had to grow for the capture to be landable, and it grew rather
than bent. The coupled leaf counter is one of the sixty leaves the Phase 4
boundary ledger pins; H2's allowlist had already declared itself the successor
to that pin, and this capture moves the leaf a second time. Supersession is
therefore a **chain**: the first claim names the ledger's receipt and entry, a
later claim names the allowlist whose claim it replaces, and resolution walks
the declared links. Every guard the single-hop version had survives — a row that
merely spells the path is inert, two claimants on one predecessor raise rather
than being ordered, a claim naming another entry does not reach it — and two new
negatives pose the chain and the orphan claim. What was **not** available was
editing a boundary row afterwards, which is the one thing that mechanism exists
to make unnecessary.

### 12.3 Major 3, and the shape twenty of the twenty-two share

The debts named a remedy — "a fresh whole-series re-adjudication" — and the
R-15/R-18 amendment's clause 3 makes that remedy unwritable until the
superseding receipt cites *the specific defect in the brief it replaces*.
Nothing had named one, so nothing could start.
`docs/receipts/standing-dissent-docket.json` names them, measured from the
committed pre-change baselines and from nowhere else:

* **`syndra_cast_timeline_ordinal` (3).** C6 *inserted* a cast into the
  timeline, so index *i* names a different cast on the two sides for every
  *i* at or above 1. The brief that produced `oracle-C6-leaf77` said
  `cast_timeline[1]/resource_cost: 100.0 → 0.0`; 100.0 is Force of Will's
  rank-5 mana cost and 0.0 is the second Dark Sphere charge's. The investigator
  computed W's cost, was right about it, and certified an old value nobody had
  disputed.
* **`syndra_rotation_receipt_rederivation` (17).** The seed retirement
  re-derived the whole rotation record; positional pairing then reads a
  surviving member at a new ordinal as a value change, a removal as a shift of
  every later ordinal, and growth as absent-to-value at the tail.
* **`abyssal_unmake_support_multiplier_field` (1).** The brief posed a value
  question about what identity-keyed pairing calls a field removal, and called
  the record's siblings unmoved when three of thirteen had moved.
* **`item_coverage_reason_prose` (1).** No defect to name, and saying so is the
  row's content: the question was well posed and the export cannot rank two
  true sentences. Routed to a ruling, `rulings-owed.json`'s sixth row.

The counts do not move — 51 standing, 28 blocking, 22 open debts — and no verdict
is stated anywhere in the docket. What moved is that a re-adjudication is now a
task with a brief rather than a sentence to agree with, and
`tests/test_standing_dissent_docket.py` holds the join both ways, so the docket
can neither fall behind the population nor outlive it.

Filed as an aside by the same measurement, and the structural cause of twenty
of the twenty-two: **identity pairing does not reach a bare-scalar list.**
`leaf_report` pairs by `event_id` and falls back to positional pairing,
fail-closed and documented — but `cast_timeline` rows are identified by `slot`
plus `ordinal` and the rotation lists by their own values, so an insertion
re-addresses every later member and each re-addressed member becomes a value
diff R-15 sends to an investigator. Escalated rather than fixed at that pass,
because widening identity pairing would re-address every committed allowlist and
oracle receipt in the campaign; the escalation said the widening belongs ahead of
the re-adjudications rather than never.

**Since resolved**, in the slice tagged `campaign-close-identity-pairing`: a
record whose identity is spelled apart — an origin field beside that origin's own
ordinal, which is what a cast row carries — is paired by it exactly as an
`event_id`-bearing record is, and a bare-string list is paired by its own strings
**only when the two lists differ in length**. That guard is what makes it a
correction and not a relaxation: an equal-length list gained and lost nothing, so
a substitution there stays the one `text_change` it is, and only a membership
transition can be adjudicated by citation. Numbers are never value-identified, so
no numeric move loses its `percent`. The re-addressing worry did not materialise
and was measured rather than argued: R-01 rows 2 and 3 report the snapshot
identical to both committed baselines before and after, so there was no diff at
the tip to re-address. It decides no dissent — every cluster's remedy is still a
fresh investigator — and removes the instrument defect that would otherwise have
handed the next one the same mis-posed question.

### 12.4 The gaps, as they finally stand

*Every gap, on every pass, in one table — not only the ones this pass touched.
The four appended re-grades above each stated the gaps their own pass moved and
said nothing about the rest, which is correct as a record of a pass and
misleading as a statement of state: the fourth of them called G7 and G8 open
with a named blocker when §11.1 and §9.3 had already closed all three of their
entries. The state column below is a bare word from a closed vocabulary and the
whole table is derived-checked against
[`campaign-gap-ledger.json`](campaign-gap-ledger.json) by
`tests/test_campaign_gap_ledger.py`, so a future pass that closes a gap without
moving its row fails a gate rather than a reader.*

| # | State | Blocks | Where it stands |
|---|---|---|---|
| **G1** | **CLOSED** | umbrella criterion 5 | `09956f8`, the campaign's second and last closing re-capture. Row 3 reads `snapshot identical`, and the boundary is the tip. |
| **G2** | **CLOSED** | umbrella criterion 1's emission clause | `4b8779e`, unblocked by **Amendment E**. |
| **G3** | **CLOSED** | umbrella criterion 8 | `69e7323`. 290 applied contributions claimed over the committed coupled corpus, 0 unidentified. |
| **G4** | **OPEN** | umbrella criterion 7, and Amendment B's exit clause behind it | Fourteen `RECEIPT_WALK` deferral rows. **Amendment F** establishes that the act retiring one is a per-family receipt-walk interpreter — a behaviour change per family, fourteen of them, budgeted by no phase — and says in terms that it does not rule the debt acceptable. Each row carries its retiring act, its blocker and an overdue flag; a fifteenth fails the gate. |
| **G5** | **CLOSED** | umbrella criterion 4's non-plan half | **Amendment H**, mechanised at `1e209e2`. Closed as a ruled carve-out — a leaf's own adjudicating receipt may quote that leaf at its address — not by editing the sites. `sole_home_scan.py --check` fails on a twelfth. |
| **G6** | **OPEN** | runbook criterion 9's repo-wide reading | 22 open debts, four clusters, three startable with a brief each and one routed to a ruling (`1414576`). Clearing one still needs a fresh investigator or a ruled `src/` slice, which no implementation lane can be. The instrument defect behind twenty of the twenty-two is resolved in `campaign-close-identity-pairing`, ahead of the re-adjudications as the escalation asked; that decides no dissent. |
| **G7** | **CLOSED** | Phase 4's criterion 14, and criterion 16's fallback-cause clause | Both entries: `5c19b1f` publishes `ReceiptWalk.reason`, `0f3adca` gives the exact capture the four bench rosters its criterion names. |
| **G8** | **CLOSED** | umbrella criterion 11's `[H]` clause, read strictly | `1de067b`. H1, H3 and H4 each name their dependent criterion and state how it is read under the deferral. Nothing is answered, and nothing may be by a lane. |
| **G9** | **OPEN BY DESIGN** | nothing | `enhanced_consume` has no producing champion. H6's recorded ruling is that Phase 5 ships exactly this, so the row is the discharge. |
| **G10** | **CLOSED** | umbrella criterion 1's frontend change budget clause | **Amendment I**. The clause names every commit in the range touching `static/js/app.js` with its reason; an unnamed fourth is the overrun, which the integer never caught. |
| **G11** | **OPEN** | nothing this campaign's criteria assert | Two defects in cached wiki text, not in `src/` (`98351d1`). The gate asserts neither reaches a damage number rather than saying so. Fixing either is a vendor-parser or data-refresh slice outside this scope. |
| **G12** | **CLOSED** | nothing — a live operational risk, not an unmet criterion | `19b03d7`, unblocked by **Amendment G**. |
| **G13** | **CLOSED** | runbook criterion 12 | `6549e32`. The criterion was unverifiable rather than failed; the ownership map is an artifact outside the plans now. |
| **G14** | **OPEN** | runbook criterion 11's first clause | The campaign's one certification blocker, and an owed ruling: `rulings-owed.json`, `whether_criterion_11s_first_clause_binds_the_campaign_backwards`. Reading it forwards re-reads "every slice"; reading it backwards schedules some sixty fresh read-only passes. Matthew's, not a lane's. |

Four gaps stand open and one stands open by design. Two of the four — G6 and
G14 — are the sign-off blockers, and neither closes by an implementation lane:
one needs fresh investigators, the other needs a decision. G4 is fourteen
budgeted slices nobody has budgeted. G11 is outside this campaign's scope and
gated where it sits.

**Which snapshot is current.** Every count this report grades a gap by moves,
and the earlier sections quote three different residues for G14 — each true on
its date. None of them is restated in the ledger: it names the artifact that
owns each figure, and its gate reads the figure at run time. The live
artifacts are the authority, always:
[`verify-ledger.json`](verify-ledger.json)'s `coverage` block for G14,
[`standing-dissent-docket.json`](standing-dissent-docket.json) for G6, and
[`behavior-frontier.json`](../behavior-frontier.json)'s `counter_4.deferrals`
for G4. A figure quoted in a dated section above is a record of that date and
is not re-graded here, for the same reason section 9 does not rewrite section 6.

### 12.5 The re-grade

Umbrella criterion **5** moves to **DISCHARGED and stays there**: all eleven
R-01 rows are green on the tip this pass ends on, not on a boundary a later
commit outdated, and the boundary *is* the tip. Runbook criterion **6**'s first
clause is true for the first time in the campaign — `compare` against
`golden_coupled_baseline.json` exits zero.

Criteria **1** and **4** stood at **PARTIALLY DISCHARGED** here through three
passes, and that grade outlived its cause. It is corrected rather than carried,
because a criterion graded short of what its own blockers say is the same defect
as one graded past them — a grade a reader cannot reconstruct from the gap table:

* **Criterion 1 — DISCHARGED, under Amendment I.** Its two named blockers are
  closed. G2 was the emission clause and `4b8779e` closed it under Amendment E;
  G10 was the frontend budget clause and Amendment I closed it by amending the
  clause to what shipped and giving it the property the integer was reaching for.
  Nothing here re-reads the criterion: both closures are recorded in the umbrella
  by its owner, and this line states their consequence.
* **Criterion 4 — DISCHARGED, under Amendment H.** Its named blocker was G5, and
  Amendment H rules the eleven forced restatements a carve-out — a leaf's own
  adjudicating receipt quoting that leaf at its address — on three conditions
  that `sole_home_scan.py --check` holds at zero unexplained sites.
* **Criterion 7 — PARTIALLY DISCHARGED, unchanged.** Its blocker G4 is open, and
  Amendment F is explicit that restating the debt at its true size is not ruling
  it acceptable. Fourteen families' numbers are still priced by the pair engine
  rather than by the one walk, which is a substantive residue of this campaign's
  own thesis and is graded as one.

A criterion discharged *under an amendment* is discharged, and the amendment is
named every time so the reading is one click from the grade. Neither line here
amends anything: both amendments were written by the umbrella's owner before
this pass, and what changed is only that the grade now says what they did.

Runbook criterion **11** stands **NOT DISCHARGED as written**, and this report
says so at the end rather than in a footnote: the campaign is **not certified
against its own runbook** while that clause is unread. Every other criterion in
both documents is discharged, or partially discharged with its residue measured,
gated and owned. What is left is one decision with a cost and an owner, and a
docket of twenty-two investigations somebody can now start.

### 12.6 The R-01 matrix on this pass's tip

| # | Verdict | What it read |
|---|---|---|
| 1 | **GREEN** | 8148 passed, 0 skipped, 0 xfailed — the pinned count plus the 20 node ids this pass declares |
| 2 | **GREEN** | `snapshot identical` |
| 3 | **GREEN** | `snapshot identical` — the first clean coupled compare at a campaign tip |
| 4 | **GREEN** | exit 0, `passed: true`, 10 scenarios |
| 5 | **GREEN** | exit 0, 173 registered / 173 exercised / 0 withheld |
| 6 | **GREEN** | 647 files unchanged |
| 7 | **GREEN** | rated 9.61/10; ratchet reports 197 files at or above their recorded score |
| 8 | **GREEN** | all four scenarios; every pinned counter reproduces exactly; no run voided or truncated |
| 9 | **GREEN** | 18 non-legacy scenarios at the merge-base anchor |
| 10 | **GREEN** | 34 passed |
| 11 | **GREEN** | `routing_divergences` empty, and identical winner and score both ways on all four |

`plan_audit.py` (R-37): **exit 0 — 8 plan documents clean.**
`sole_home_scan.py --check`, `standing_dissent_scan.py --check`,
`behavior_frontier.py --check` and `migration_frontier.py --check`: all exit 0.

---

## 13. The minor findings, dispositioned

*Appended 2026-08-17, after the second sign-off review's three **minor** findings
were left standing rather than closed — §12.1 records two of them as "not
actionable" and "disclosed, left standing". Everything above this line stays as
written, for the reason section 9 gives. Nothing here re-grades a gap or a
criterion: a minor finding that closes closes as a record, and the two grades
this report ends on are untouched.*

### 13.1 The eight historical commits with no R-20 line — **ACCEPTED, CLOSED**

R-20 requires every semantic slice to carry an `Expected qualifying occurrences`
line, and eight commits in the campaign range touch `src/` without one. Two
passes recorded that as "not actionable" and moved on, which is true about the
remedy and is not a disposition: an unactionable finding with no dated record is
indistinguishable, one pass later, from a finding nobody read. This is that
record, and with it the finding is closed rather than carried.

**The population, enumerated rather than described.** Measured over
`584071e..HEAD` by the same rule R-20 states — a commit whose diff touches any
path under `src/`, and whose body contains no declaration of a qualifying
occurrence count in either of the two spellings the campaign has used:

| Commit | Date | Subject |
|---|---|---|
| `4e9f26a` | 2026-08-09 | docs(survival): disclose what 0A.4 decided without saying so |
| `5d89453` | 2026-08-09 | docs(survival): disclose the four 0A.4 behaviours 4e9f26a still missed |
| `581fd19` | 2026-08-09 | test(pipeline): the six C6 behaviours its commit bodies did not name (C6) |
| `518a6e3` | 2026-08-11 | docs(behavior): the defensive closure's prose names the population it has |
| `8e1e23b` | 2026-08-11 | refactor(coverage): the three target registries, deleted (3.8) |
| `6c4f0a2` | 2026-08-11 | fix(behavior): NO_RUNTIME_BEHAVIOR asserts only the absence it reviewed (3.8) |
| `e9c0f78` | 2026-08-11 | docs(behavior): the frontier's invariant sentence, corrected (3.8) |
| `6ab477b` | 2026-08-11 | refactor(coverage): the outcome declaration moves to a home of its own (3.8) |

Eight of the 252 `src/`-touching commits in the range. All eight are Phase 0 and
Phase 1/3 work from the campaign's first three days; the newest of them is
`6ab477b`.

**Why it is accepted rather than remedied.** The remedy R-20 names is a
declaration made *before* the slice's first `src/` edit — measure, then mutate,
then pin. A line written onto a commit today would be neither: it would be a
count read off a tree the edit already changed, which is the exact failure mode
R-20's second half exists to forbid, and it could only be attached by editing a
filed commit, which this campaign's evidence chain does not permit. History is
unreachable in both directions. The honest disposition is a record, not a
repair.

**What makes the acceptance bounded rather than open-ended.** The class is
closed by measurement and not by intention: **129 `src/`-touching commits
followed the newest of the eight, and 129 of them carry a declaration.** None is
missing. So the finding is a fact about the campaign's first three days and
about nothing since, and the count that would make it a live gap is zero.

**What the acceptance does not say.** It does not say the eight moved no
numbers. Five of them are `docs`-subject commits whose `src/` edits are prose,
and three are `refactor`/`fix` commits in the Phase 3 coverage work; what any of
them moved is knowable only from their own bodies and from the baselines of
their day, and no reconstruction is attempted here. What is recorded is that
they declared no count in advance and that nothing can now make them have done
so.

*Corrected 2026-08-17.* The breakdown above read "Five of them are
`docs`-subject commits whose `src/` edits are prose, and three are
`refactor`/`fix` commits" — 4 + 3 against a table of eight. The commit the
arithmetic dropped is `581fd19`, the one of the eight whose subject is neither
`docs` nor `refactor`/`fix`, and it is the only one of the eight whose `src/`
edit was never described here at all. Measured: `git show --stat 581fd19 --
src/` is `src/calculator/damage.py`, +13/−5, and the whole of it is inside
`_ridden_parent_slot`'s docstring, which that commit's own body states in terms
("the only `src/` edit is `_ridden_parent_slot`'s docstring"). So the dropped
row changes nothing about what the acceptance covers — this is an arithmetic
correction and not a re-grade — but it was dropped from the one sentence written
to bound what the acceptance claims, which is the sentence a reader checks the
bound against.

### 13.2 The other two minors

* **The `tests.collected` re-pin outside R-32's carve-out** — closed by amending
  R-32, dated 2026-08-17 in the runbook. The carve-out gains `tests{collected}`
  as a fourth lane-written key, on the receipt-only commit shape `86aa1d2`
  already used, with `skipped` and `xfailed` left to the integration agent so the
  half of R-01 row 1 that catches a test quietly becoming a skip is out of a
  lane's reach. The runbook now grants what the history shows; the history is not
  rewritten to fit the runbook.
* **Stale justification strings in gated receipts** — swept, with the sweep's own
  commit naming each string it moved and the measurement that made it stale.

---

## 14. The closeout, dispositioned

*Appended 2026-08-17 on `a431e34..HEAD`, after a third sign-off review withheld
certification with five findings — the criterion-11 backfill and the ruling behind
it, the fourteen receipt-walk retirements, the standing-dissent docket, and the two
minors section 13.2 left as one-line records. Everything above this line stays as
written, for the reason section 9 gives. **Nothing here re-grades a gap or a
criterion.** Section 12.4's table and
[`campaign-gap-ledger.json`](campaign-gap-ledger.json) are the authority on state
and this section moves no row in either; what it records is what each finding is
answered by, measured on this tip by running the instrument rather than by reading
a body.*

### 14.1 The five, one by one

| Finding | State | Where it stands |
|---|---|---|
| **1 — criterion 11's first clause: the backfill, and the ruling behind it** | **The backfill is complete; the ruling is untouched and still owed** | The clause's residue is 2 of 125 slice tags, down from 118 on 2026-08-14. Both remaining tags cite a verdict a reader can open, so `residue_with_no_verdict_anywhere` is **0**. The ruling is `rulings-owed.json`'s one open row and no lane may write it. See 14.2. |
| **2 — the fourteen receipt-walk retirements** | **All fourteen have left; the re-grade is the owner's** | `behavior-frontier.json`'s `counters.counter_4.deferrals.rows` is `{}` and `receipt-walk-retirement-schedule.json`'s `families` is `{}`. Ten retired by Amendment L's ruled act, one by Amendment O's authority reclassification, three by Amendment Q's lane-declaration correction. See 14.3. |
| **3 — the standing-dissent docket** | **Three of four clusters cleared; one open, and it is a `src/` slice rather than an investigation** | `standing_dissent_scan.py --check` exit 0: 34 standing of 83 adverse across 597 receipts, 11 blocking — 7 adjudicated by citation, 4 open debts. The docket holds one cluster. See 14.4. |
| **4 — minor: the `tests.collected` re-pin outside R-32's carve-out** | **CLOSED** | Ruled, not re-recorded: R-32's amendment of 2026-08-17 in the runbook grants `tests{collected}` to the owning lane on the receipt-only commit shape `86aa1d2` already used, with `skipped` and `xfailed` left to the integration agent. Landed at `1bd837e`. A fresh verifier re-measured every clause of the answering group and returned it DISCHARGED — ledger round 110. |
| **5 — minor: stale justification strings in gated receipts** | **CLOSED** | Two answering groups, both verified. `campaign-close-minor-findings-r35` swept the first cohort (`8aa1ee1`, `ecc6497`, `51ccdce`, `264aeb9`) and `campaign-close-minor-findings-r35-2` the strings the first sweep left or wrote (`f87e4c2`, `df631c8`, `0c46d26`, `9d5b276`). Fresh verifiers over both ranges returned every criterion DISCHARGED — ledger rounds 110 and 111, each re-measuring the contradicted clause against the tree rather than against a body. |

### 14.2 Finding 1 — the clause has a denominator, and 2 of 125 left in it

The clause is "every slice has a recorded `verify-<slice>` verdict", and until
2026-08-14 it quantified over nothing a machine could read. It has a denominator
now — the campaign's own slice tags, derived from commit subjects — and this
closeout finished filling it from the only admissible source the ledger names: the
orchestration journals, one JSON line per rendered verifier report, written by
readers who had not read the plan and before the commits that answered them.

Measured on this tip, and every figure read from
[`verify-ledger.json`](verify-ledger.json)'s coverage block rather than restated
from a body:

| | 2026-08-14 | this tip |
|---|---|---|
| slice tags derived from commit subjects | 68 | **125** |
| with a verdict recorded in the ledger | 1 | **123** |
| residue | 67 | **2** |
| residue citing no verdict anywhere | 61 | **0** |

Three routes closed it and each is a different claim. The **backfill** (`a455839`)
transcribed the verdicts rendered *during* the campaign, at the tip each slice was
verified against. The **residue sweep** re-ran R-35 today over ranges that landed
long ago, in three tranches — `209da2f`, `1e7c342`, and this closeout's `a431e34`,
which took the four verifiers of the 2026-08-17 batch nobody had transcribed and
turned them into 23 pass blocks. `0be8f37` recorded the verdict on
`campaign-close-sweep-findings`, which is the campaign's first recorded verdict on
a lane whose whole job was answering somebody else's.

What is left is two tags: `campaign-close-verify-p4-batch`, whose verdict lives in
a commit body and whose range no verifier's brief ever reached, and this closeout
lane's own tag, which cannot verify itself. Both are listed, both are prepared as
startable rows in [`verify-backlog.json`](verify-backlog.json), and neither is
counted as covered.

**The ruling is not answered and this section does not read on it.** Whether the
clause binds the campaign's past is `rulings-owed.json`'s one open row, and how a
row closes is unchanged: an amendment in the umbrella, written by its owner, with
the row moved to `answered[]` naming it. `b02e4ca` refreshed the row's *measurement*
— the question quoted a population frozen on 2026-08-14, which a verifier filed as
a standing aside — and refreshed nothing else: both branches stand verbatim, no
amendment is cited because none exists, and the row stays in `owed[]`. What the
transcription changed is the price of the backwards branch, from 61 fresh passes to
2. A price is not a ruling.

### 14.3 Finding 2 — the fourteen have left, and the ledger row that says so

Amendment B deferred fourteen `(family, RECEIPT_WALK)` rows to a stage that then
shipped without retiring them; Amendment F established that the retiring act is a
per-family interpreter and said in terms that restating the debt is not ruling it
acceptable. Measured on this tip, by running the instruments rather than reading
the amendments:

* `behavior_frontier.py --check` exit 0, `counter_4` at 16 declared pairs with
  `deferrals.rows == {}` — deferred 0, gap 0, met true on both the `PAIR_ENGINE`
  and `RECEIPT_WALK` targets.
* `receipt_walk_schedule.py --check` exit 0, `families == {}`, `scheduled_slices`
  0, `families_with_no_covering_coupled_scenario` `[]`,
  `slices_whose_retiring_lane_amendment_k_corrects` `[]`.
* `interpreters.INTERPRETERS` holds **13** `(family, RECEIPT_WALK)` keys, read from
  the tree.
* The fourteen leave by three different acts, and the receipt names which:
  **ten** by the ruled per-family retirement slice, **one** (`crit_profile`) by
  Amendment O's Ruling 1 authority reclassification, and **three**
  (`combat_state`, `opening_defense`, `threshold_defense`) by Amendment Q's
  lane-declaration correction. Ten plus one plus three is the fourteen.
* `term_census.py --check` exit 0 — 29 post-authoring packet-mutation sites, 0
  uncovered; 9 authoring-time mitigation terms, 0 uncovered; 3 static holder amps,
  0 unfolded. That gate is the one Amendment N ruled must be clean before any
  family may retire, and it is clean over both halves of a mitigation.

**G4's state is not moved here.** Its own row says what stands in its way is no
longer an interpreter but the re-grade itself, which re-reads umbrella criterion 7
and section 12.4's table with it, and is the owner's rather than a lane's. This
section records the measurement and leaves the grade exactly where the ledger has
it.

### 14.4 Finding 3 — nineteen debts cleared, four standing, one cluster

The docket named 22 open debts in four clusters, each with the defect in its prior
brief measured from the committed pre-change captures. Three clusters have since
cleared and are in `cleared[]` rather than deleted, because a closed row says which
question was re-posed and which receipts answered it:

* **`syndra_rotation_receipt_rederivation`** (17 receipts) — cleared 2026-08-15 by
  clause 1: one fresh investigator per scenario record, the whole rotation computed
  from cached ability rows and `docs/math-foundations.md`, one receipt per leaf,
  each naming the defect and the receipt it supersedes.
* **`abyssal_unmake_support_multiplier_field`** (1) — cleared 2026-08-15 by clause
  1, briefed on the record rather than on the field; verdict `new_value_correct`.
* **`item_coverage_reason_prose`** (1) — cleared by the only route it had. Its
  brief had no defect to name, so clause 3 made a re-run unwritable; umbrella
  **Amendment J** adjudicates a campaign-authored justification string by source
  assertion, and the row closed on the ruling rather than on an investigation.

One cluster stands: **`syndra_cast_timeline_ordinal`**. Clause 1 is spent — the
whole-series re-adjudication ran, well posed, and filed three receipts (two
`both_wrong`, one `new_value_correct`) — so what it owes is clause 2, the producing
correction re-opening as its own ruled `src/` slice. Its four open debts are the two
original C6 receipts and the two `both_wrong` receipts the re-adjudication itself
filed, which are standing dissents on the addresses they answer.

The instrument, not the prose, is the authority:
`standing_dissent_scan.py --check` exit 0 — **34 standing of 83 adverse across 597
receipts; 11 blocking, 7 by citation and 4 open debts.** Every capture that would
pin over a standing verdict fails a gate, which is the half of R-19 the campaign
lacked until `9c6adee`. **G6's state is not moved here** for the same reason G4's
is not.

### 14.5 What this closeout did not close

Recorded rather than rounded up, in the shape section 9 set:

* **The owed ruling.** One row, `rulings-owed.json`, unchanged and unchangeable by
  a lane.
* **Fourteen NOT_DISCHARGED sweep rows, recorded and not answered.** The 23 blocks
  `a431e34` transcribed carry 14 `NOT_DISCHARGED` verdicts. Three name the commit
  that closed the red they found and this lane resolved that commit; two ask for
  exactly the transcription that records them; **nine stand `documented_open`**.
  Recording a verdict is not answering it, the ledger's `residue_sweep` block says
  so in its own words, and a lane that graded its way out of nine findings would be
  doing the thing this campaign exists to stop.
* **`tests.collected` is 406 behind its pin.** `campaign-fingerprints.json` pins
  8128; `pytest` reports 8534 on this tip. The suite is green and nothing is
  skipped, so no gate is red — what is unavailable is R-01 row 1's *second* half,
  "collected = the pinned count + declared new", read from the receipt alone. The
  delta belongs to the declaring lanes' slices and not to this one, which declares
  none; it is recorded here and in ledger round 104's findings rather than absorbed
  by a lane re-pinning over other lanes' arithmetic.

### 14.6 The R-01 matrix on this closeout's tip

| # | Verdict | What it read |
|---|---|---|
| 1 | **GREEN** | 8534 passed, 0 skipped, 0 xfailed |
| 2 | **GREEN** | `snapshot identical` |
| 3 | **GREEN** | `snapshot identical` |
| 4 | **GREEN** | exit 0, `passed: true`, 10 scenarios, 0 failures |
| 5 | **GREEN** | exit 0, 173 registered / 173 exercised, `passed: true` |
| 6 | **GREEN** | 658 files unchanged |
| 7 | **GREEN** | rated 9.61/10; ratchet reports 197 files at or above their recorded score |
| 8 | **GREEN** | all four scenarios; every counter, residual, winner and score pinned in `campaign-fingerprints.json` reproduces exactly, zero mismatches; none voided, none truncated |
| 9 | **GREEN** | 18 non-legacy scenarios at the merge-base anchor `494eb06` |
| 10 | **GREEN** | 161 passed |
| 11 | **GREEN** | `routing_divergences` empty on all four scenarios |

`plan_audit.py` (R-37): **exit 0 — 8 plan documents clean.**
`sole_home_scan.py --check` (6 sites, 0 unexplained), `standing_dissent_scan.py
--check`, `behavior_frontier.py --check`, `migration_frontier.py --check`,
`receipt_walk_schedule.py --check`, `term_census.py --check` and
`verify_backlog.py --check`: all exit 0.

Both compared baselines read `snapshot identical` at this tip and no closeout slice
left a declared diff standing, so this closeout performs **no** boundary re-capture:
there is nothing for one to absorb, and a capture with nothing to absorb is a
baseline move for its own sake.

---

## 15. Section 14, re-measured

*Appended 2026-08-17, after an independent read-only R-35 pass over slice group
`campaign-close-final-integration` (`a431e34`, `0be8f37`, `b02e4ca`, `9ee7505`)
returned the criterion `close-reports-closeout-section-accurate` **NOT DISCHARGED**
on three figures and named six behaviours those four commit bodies do not mention.
The pass reproduced the rest of section 14 by re-running every instrument it cites.
Section 14 stays exactly as written, for the reason section 9 gives, and each
correction below lands beside the sentence it corrects rather than over it.
**Nothing here re-grades a gap or a criterion.** Section 12.4's table and
[`campaign-gap-ledger.json`](campaign-gap-ledger.json) remain the authority on state
and this section moves no row in either. Every figure below is read by running the
instrument named beside it, and — unlike section 14's — every one of them is gated,
by [`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py);
see 15.6.*

### 15.1 The residue's fall is dated to the wrong day, and it rose first

Section 14.1's finding-1 row says the clause's residue is 2 of 125 slice tags, "down
from 118 on 2026-08-14". Section 14.2's own table twenty lines below it reads
`residue | 67 | 2` for that date, so the two disagree inside one section, and the
ledger's history says neither the figure nor the direction belongs to that day.

Measured by reading `coverage.residue` out of every blob of
[`verify-ledger.json`](verify-ledger.json) in its own history —
`git log --format='%H %ad' --date=short -- docs/receipts/verify-ledger.json`, then
`git show <sha>:docs/receipts/verify-ledger.json` for each:

* `c029024` (2026-08-14) — residue **62**, the first commit that gave the clause a
  denominator at all.
* `0f3adca` (2026-08-14) — residue **67**, which is the figure 14.2's table carries.
* `a323202` (2026-08-14) — residue **76**, the last of that day's seventeen
  ledger-touching commits.
* `9961bf2` (2026-08-17) — residue **118**, the highest reading anywhere in the
  file's history, and the commit immediately before the backfill.
* `a455839` (2026-08-17) — residue **47**, the backfill.
* `0be8f37` (2026-08-17) — residue **2**, this closeout's second commit and this
  tip.

So over the three days the residue **rose** and then fell, and the whole of the fall
is inside 2026-08-17: the denominator grew with every slice group that shipped while
the ledger held almost no verdicts, and what closed it — the backfill and the two
sweeps — all landed on the last day. 118 is a 2026-08-17 figure, not a 2026-08-14
one, and 2026-08-14's own reading is the 67 the table already carries.

What the row should say is what 14.2's table already supports: 2 of 125, down from
118 at `9961bf2` earlier the same day, and *up* from 67 on 2026-08-14, before the
denominator grew. The clause "down from 118 on 2026-08-14" misstates the figure's
date and reverses the trajectory it names.

The same figure was written into a second home the same day and carries the same
error there: `b02e4ca` appended "It fell -- 118 to 2 over three days" to
[`rulings-owed.json`](rulings-owed.json)'s open row, in the field
`consequence_of_leaving_it_open`. It is corrected there by a further dated line
beside it rather than by deletion, which is this campaign's rule for a justification
the tree contradicts: a sentence that is only deleted is one no reader can check was
ever real.

### 15.2 A citation flag says a body carries an answer, never whose

Section 14.2 says what is left is two tags, the first being
"`campaign-close-verify-p4-batch`, whose verdict lives in a commit body and whose
range no verifier's brief ever reached". The two clauses contradict each other — a
verdict living in a commit body is a verdict some verifier rendered — and only the
second survives measurement.

**The second clause is true and re-measured.** No `verified_commits` list in any of
the ledger's passes contains `209da2f`, which is that group's only commit. No
verifier's brief has ever reached it.

**The first is false.** No verdict about `campaign-close-verify-p4-batch` exists
anywhere. What exists is the flag: [`verify-backlog.json`](verify-backlog.json)'s
row for the group reads `cites_an_r35_answer_in_a_commit_body: true`, and that flag
is derived — `tests/test_verify_ledger.py::_groups_citing_a_verdict_in_a_commit_body`
is a conjunction over the group's own commit bodies, a mechanism name **and** a
verdict word. `209da2f`'s body carries both because it transcribes R-35 verdicts
about six *other* slices — `P4C`, `P4C-P4E-C2R`, `P4C/P4F`, `P4-arbitrate`,
`P4-R18-amend`, `P4-H2-ccscope` — which is the whole reason that commit exists.

The ledger already records this exact limitation, in the same coverage block the
counter lives in: `a_groups_own_next_commit_can_flip_its_citation_state` says "what
the derivation cannot do is tell WHOSE answer a body carries", and calls the
citation state "deliberately weaker than a recorded verdict". Section 14.1's weaker
phrasing — "both remaining tags cite a verdict a reader can open" — is exactly what
the flag supports and stands unaltered. Section 14.2's stronger one does not, and
neither does the copy `b02e4ca` wrote into [`rulings-owed.json`](rulings-owed.json)'s
`what_the_measurement_now_reads`, where it entered an owed-ruling row while that
commit's body advertised the change as reading a measurement artifact instead of
restating a figure. Both sentences stay written; the measurement lands beside each.

### 15.3 No ledger round measures the act that closed minor 4

Section 14.1's finding-4 row closes the `tests.collected` minor and adds: "A fresh
verifier re-measured every clause of the answering group and returned it DISCHARGED
— ledger round 110." Round 110 does not read on that act.

Measured over [`verify-ledger.json`](verify-ledger.json) at this tip:

* Round **110** verifies the slice group `campaign-close-minor-findings-r35` over
  `8aa1ee1`, `ecc6497`, `51ccdce`, `264aeb9`, `3b0a030`, and every one of its seven
  criterion ids begins `round6-`. All seven read on round 6's ledger row and on the
  gated-justification-string findings — which is finding **5**, not finding 4.
* Minor 4 closed by R-32's amendment of 2026-08-17, which landed at `1bd837e`.
  `1bd837e` carries the tag `campaign-close-minor-findings`, whose only ledger
  rounds are **6** and **7**. Each returned exactly one criterion,
  `no_gated_receipt_carries_a_justification_string_the_tree_contradicts`, and each
  returned it **NOT_DISCHARGED**. Neither reads on the re-pin.
* Searching every `verified_commits` list in all 127 passes for `1bd837e` returns
  rounds 6 and 7 and nothing else.

So the honest state of minor 4 is **closed by a ruling and measured by no pass**.
The disposition section 14.1 records stands — R-32's carve-out now grants what the
history shows, and the runbook was amended rather than the history rewritten — and
what does not stand is the sentence claiming a verifier re-measured it. Finding 5's
citation of rounds 110 and 111 is correct, reads on the group those rounds actually
verify, and is untouched.

This is the third and last of the three figures the pass returned NOT DISCHARGED.

### 15.4 Nine is this closeout's count; the tree's is sixty-two

Section 14.5 records "**nine stand `documented_open`**", and nine is exact for the
population that sentence is about: the 23 pass blocks `a431e34` transcribed carry 14
`NOT_DISCHARGED` rows, of which 5 are `fixed` and 9 `documented_open`. Runbook
criterion 11's second clause — "no barrier is crossed with an open NOT DISCHARGED"
— is not quantified over that population. It is quantified over the ledger, and a
section whose whole job is recording what stayed open is where that number belongs.

Counted over all 127 passes in [`verify-ledger.json`](verify-ledger.json) at this
tip:

| verdict / disposition | rows |
|---|---|
| `DISCHARGED` | 808 |
| `PHASE_TIP_ONLY` | 115 |
| `NOT_DISCHARGED` | 89 |
| ... of which `fixed` | 20 |
| ... of which `fixed_and_gated` | 7 |
| ... of which `documented_open` | 62 |

The 62 stand across 24 slice groups and 27 rounds: 43 of them in backfilled blocks,
9 in residue-sweep blocks and 10 in live passes. `R-28` alone holds 12,
`campaign-close` 8, and `R-37`, `S9` and `S10` five each. Nine of the 62 are this
closeout's; the other 53 were open before it began and none is answered by it.

**This re-grades nothing.** Section 6's criterion 11 and
[`campaign-gap-ledger.json`](campaign-gap-ledger.json) are the authority on the
grade and neither moves here, exactly as sections 14.3 and 14.4 leave G4 and G6
where the ledger has them. What changes is that the clause's own denominator is
written down: 62 open rows is a number that can be re-derived, argued with and
driven down, and "nine" was a true figure about the wrong set.

*The table above is measured at `832a91f`, the commit that landed this subsection,
over the 127 passes the ledger then held. One block has landed since — round 128,
which 15.5 records — and it moves `NOT_DISCHARGED` 89 → **90** and `fixed`
20 → **21**, leaving `documented_open` unchanged at **62**. The table is left at
its anchor and the moved pair is stated here, so no figure is rewritten and none
goes stale.*

### 15.5 The closeout's own verdict, recorded

The pass that returned the three figures above is itself a recorded verdict now:
**round 128** of [`verify-ledger.json`](verify-ledger.json), over
`campaign-close-final-integration`'s four commits, answered by this group. It is the
campaign's second recorded verdict on a lane whose job was answering somebody else's,
and it carries the one criterion the verifier failed with the evidence it ran, plus
the six behaviours it named that those four commit bodies do not mention.

Recording it moves the coverage block: `campaign-close-final-integration` leaves
`slice_groups_without_one` for the list a recorded verdict puts a group on, and this
answering group's own tag takes its place there. The residue is **2** again, of
**126** slice tags, with `residue_with_no_verdict_anywhere` **0** and
[`verify-backlog.json`](verify-backlog.json) preparing **2** startable passes. The
two remaining tags are `campaign-close-verify-p4-batch`, whose range no verifier's
brief has reached, and `campaign-close-final-integration-r35`, which cannot verify
itself — the same honest pair section 14.2 records, one lane further on.

*Anchored 2026-08-17. The five figures in the paragraph above were readings of
this tip when `e4338b7` wrote them, and a reading of this tip stops being one the
moment another slice group ships — which is a thing this campaign expects to
happen and not a defect in the section. They stay exactly as written, and
`tests/test_campaign_close_report_figures.py` now reads them where it already
reads 15.1's six and 15.4's table: at the commit that stated them,
`git show e4338b7:docs/receipts/verify-ledger.json`. The live figures are in
`verify-ledger.json`'s coverage block, which is where §12.4 says they live, and
§16.3 states them as of that section's own tip.*

The six findings, and what each is:

| # | The finding | Disposition |
|---|---|---|
| 1 | `0be8f37`'s body calls the block it writes round 128 three times; the block it added is round 127 | `documented_open` |
| 2 | `b02e4ca` and `9ee7505` both regenerate `verify-backlog.json` and neither body says so | `documented_open` |
| 3 | `b02e4ca` wrote the `campaign-close-verify-p4-batch` attribution into `rulings-owed.json`, not just the report | `fixed` — `0a2bee2`, with 15.2 |
| 4 | `b02e4ca`'s "It fell -- 118 to 2 over three days" is a new dated figure its body does not flag | `fixed` — `6a357b4`, with 15.1 |
| 5 | `9ee7505`'s "what this closeout did not close" counts nine over one batch, not 62 over the ledger | `fixed` — `832a91f`, with 15.4 |
| 6 | `a431e34` moved `slice_groups_citing_a_verdict_in_a_commit_body` 17 → 18, gaining its own tag, unremarked | `documented_open` |

**Three are `documented_open` and none of them can be anything else.** Each is a
sentence in a filed commit body, and each names an artifact that is already correct:
the ledger really does hold 127 passes at `0be8f37` with no holes, the backlog really
was regenerated correctly, and the citation counter is derived rather than authored so
nothing in it is wrong. What was missing is disclosure, in bodies nobody may amend.
What a lane does control is its own practice, and every commit of this group names
each gated receipt it regenerates and each counter it moves, under a heading of its
own. Finding 6 is the second measured instance of the state the ledger already
docketed as `a_groups_own_next_commit_can_flip_its_citation_state`, and that block's
ruling stands: the shape is recorded rather than repaired, because widening a derived
flag into an attribution changes what the counter claims and that is a runbook matter.

**Nothing here re-grades a verdict.** A verdict is the verifier's artifact and a
disposition is the lane's — the ledger's `when_a_later_lane_answers_a_sweep_row` says
it in those words — so the NOT_DISCHARGED stands as returned, with `answered_at`
naming the three commits that answered it.

### 15.6 What gates section 15

The pass's evidence closes with the reason all three errors survived to be found by
a reader: "Section 14 is also ungated: `plan_audit.py` runs over `docs/plans/*.md`
only, so nothing in the tree would catch any of these three." That is true of
section 14 and stays true — no closeout rewrites section 14 — but it stops being
true of the section that carries the corrections.

[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
re-derives every figure this section states from the artifact it was read out of:
15.1's six dated residue readings from the ledger's own history, one
`git show <sha>:docs/receipts/verify-ledger.json` each; 15.4's table from the ledger
as `832a91f` left it; the moved pair and 15.5's coverage figures from the ledger and
[`verify-backlog.json`](verify-backlog.json) at this tip. It re-measures the
section's non-numeric claims too — that no pass's `verified_commits` holds
`209da2f`, that the backlog really flags that group as citing a body, that round
110's criteria read on round 6's row, that `1bd837e` is verified by rounds 6 and 7
and by nothing else, that the three groups 15.4 spells as “five each” really hold
five, and that every phrase 15 quotes out of section 14 is in section 14 word for
word. **39** figures and **6** claims, the count itself among the figures, and the
file rides R-01 row 1 like every other gate.

A figure that is a reading of a moving artifact — 15.1's six, 15.3's search, 15.4's
table — is anchored at the commit that stated it and read out of git there; a
figure about this tip is read from the tree. Both are re-derived. What section 15
quotes out of section 14 is gated as a quotation instead, because a correction that
misquotes the sentence it corrects is one no reader can check.

R-05's red ships with it and is permanent.
`test_the_gate_fails_when_a_stated_figure_drifts` doctors each figure in a copy of
the section — the value alone, in the one place the pattern finds it — and requires
the same comparison to fail. A check that cannot fail is indistinguishable from a
check that passes, which is the sentence this whole campaign is an answer to.

What it does not do is gate section 14, or anything above it. Those sections stay
exactly as the passes that wrote them left them, and this is the first section of
the report a reader does not have to take on trust.

### 15.7 One sentence of 15.3, corrected by the gate that reads it

Building 15.6's gate found a sentence of this section imprecise before the gate had
run once, which is what a gate is for and is the shortest possible demonstration
that section 15 was not checkable until it had one.

15.3 says every one of round 110's "seven criterion ids begins `round6-`". They do
not begin there. The ledger stamps each criterion id with the slice group it belongs
to, so the seven read
`campaign-close-minor-findings-r35/round6-row-exists-and-is-shaped-as-claimed` and
six more of that shape: the tag, a slash, then the stem. What 15.3 rests on — that
all seven read on round 6's row and none on the `tests.collected` re-pin — is what
the stems say, and it is unchanged. What was wrong is where the stem starts.

`test_round_110_reads_on_round_6s_row_and_not_on_the_re_pin` asserts the stem
(`row_id.split("/")[-1]`), so the corrected shape is the one the gate holds, and the
sentence and the check now say the same thing. Round 128's note in
[`verify-ledger.json`](verify-ledger.json) carries the same phrasing and gains the
same dated clause; both stand written, with the measurement beside them.

### 15.8 The R-01 matrix on this lane's tip

| # | Verdict |
|---|---|
| 1 | **GREEN** |
| 2 | **GREEN** |
| 3 | **GREEN** |
| 4 | **GREEN** |
| 5 | **GREEN** |
| 6 | **GREEN** |
| 7 | **GREEN** |
| 8 | **GREEN** |
| 9 | **GREEN** |
| 10 | **GREEN** |
| 11 | **GREEN** |

`plan_audit.py` (R-37) clean, and `sole_home_scan.py --check`,
`standing_dissent_scan.py --check`, `behavior_frontier.py --check`,
`migration_frontier.py --check`, `receipt_walk_schedule.py --check`,
`term_census.py --check` and `verify_backlog.py --check` all exit 0.

**What each row read is in this lane's commit bodies, not here.** Sections 11.4,
12.6 and 14.6 tabulate their readings; this one deliberately does not, for the
reason 15.6 gives: a figure in this section is one this section's gate re-derives,
and a gate reading cannot be re-derived without re-running the gate it came from.
Putting a suite count and a pylint score in a table here would add the first
ungated figures to the one section of this report that has none, which is the
property the corrections above are for. The verdicts are what this section can
carry and check by reading; the numbers live where R-01 puts them, one commit at a
time.

No baseline moves in this lane, no `src/` is touched, and both compared baselines
read `snapshot identical`, so there is nothing for a boundary re-capture to absorb
and none is performed.

---

## 16. The fifth remediation pass — the two majors, closed by the acts their blockers named

*Appended 2026-08-17, after a certification review withheld sign-off with one
blocker and two majors. Everything above this line stays exactly as written, for
the reason section 9 gives. Unlike section 15, this section **does** re-grade, and
says on whose authority: it moves the gap rows whose named blockers have been
discharged, in the shape §12.5 established when it corrected criteria 1 and 4 —
"a criterion graded short of what its own blockers say is the same defect as one
graded past them", and "nothing here re-reads the criterion: both closures are
recorded in the umbrella by its owner, and this line states their consequence".
Every closure below is an act a reader can open: a commit in the campaign range,
or an amendment the umbrella's owner wrote. None of them is an implementation
lane deciding what a criterion means, and the one thing that would be — runbook
criterion 11 — is not closed here, and §16.3 says why in its own words.*

*§16.4 is now the report's final gap table. `FINAL_TABLE_HEADING` in
[`tests/test_campaign_gap_ledger.py`](../../tests/test_campaign_gap_ledger.py)
moves to it in the same commit that writes it, which is the deliberate act that
file's own comment asks for — "a fifth appended section must move this constant
deliberately, which is the moment somebody notices the table it points at is no
longer the last one". §12.4 stays as written and stops being read.*

### 16.1 G6 — the clause-2 correction landed, and the instrument could not see it

G6's blocker said four standing oracle dissents stood as open debts in the
`syndra_cast_timeline_ordinal` cluster, that what they owed was clause 2's ruled
`src/` correction re-opening the producing slice, and that "an implementation lane
can be neither a ruling nor a slice it must not scope for itself".

The first half of that stopped being true before this review ran. The ruling is
the R-15/R-18 amendment's clause 2, written by the umbrella's owner: *a sustained
dissent re-opens the producing correction as a ruled `src/` fix*. The scoping was
done by the filed receipts and not by a lane —
[`oracle-DKT-syndra_cast_timeline_ordinal-leaf1.json`](oracle-DKT-syndra_cast_timeline_ordinal-leaf1.json)
computes the whole cast timeline member by member, and `cast_timeline[6]/slot`
cleared, so the receipts themselves say the `recast_of="Q"` stamp is right and
only the price was wrong. The docket refused to name which of the two must move
and never had to; reading the receipts is what its own `what_the_slice_inherits`
says the slice's first act is.

`b299978` is that slice. A synthetic slot owns no cached ability entry, so
`champions/engine.py`'s resource stamp returned at its first guard, the `Q2` entry
carried no `resource_cost` key at all, and every consumer read the absent key
through its own `.get("resource_cost", 0.0)`. A whole Dark Sphere cast was
published as free because nobody wrote its price — not a wrong number, a number
defaulted to zero on the way out, which is this campaign's own failure shape.
`4f41e6e` pinned the leaf at 60.0 afterwards, which is the order clause 2 requires:
the row's own words are that the baseline may not absorb the address *until* the
slice lands.

What was left was measurement, and it was wrong in the instrument rather than in
the tree. `standing_dissent_scan.py` asked, of every standing adverse receipt,
whether the committed baseline differs from "the one the oracle certified" — and
read that value out of `old_value`, which certifies for an `old_value_correct`
verdict and for no other. A `both_wrong` receipt certifies **neither** committed
side and writes the number its whole-series computation reached under
`oracle_correct_value`. So the two DKT receipts read as pinned over at exactly the
moment the tree agreed with them, and — the direction that mattered — a baseline
still holding the value they refuted would have compared *equal* and left the
population silently. Reading a receipt at what it certified retires those two and
is a red the scan gains, not one it gives up;
`test_a_baseline_holding_a_refuted_value_is_reported` asserts both directions.

The two C6 receipts under them leave by clause 3 instead. Clause 3 makes
supersession explicit — the filing that supersedes names the receipt it replaces
and states the defect in that receipt's brief — and the scan could only ever infer
supersession from a later same-leaf `new_value_correct` verdict, which is the one
verdict a clause-2 re-adjudication never carries. Four guards admit the declared
form, and the strict one is that the superseding filing must itself be out of the
blocking population, so a chain of dissents can never retire a live pin.

Measured on this pass's tip by `standing_dissent_scan.py --check`: **7** blocking
of **34** standing across **597** receipts, all seven `citation`, **0** open debts.
The docket's `clusters` is empty and every row it ever held is in `cleared[]`,
joined to what answered it. No dissent was decided here: all four leave against a
committed baseline holding 60.0, the only value any filed computation reached.

**G6 → CLOSED**, named to `b299978` and `4f41e6e`.

### 16.2 G4 — all fourteen have left, and the act left standing was the re-grade

G4's row said so itself before this review ran: *"What stands in this row's way
is therefore no longer an interpreter: it is the re-grade itself."* Its blocker
was fourteen `(family, RECEIPT_WALK)` deferral rows, and the row's own note
records each of the fourteen leaving, by name and by date. This section
re-measured all of it rather than reading it:

* [`docs/behavior-frontier.json`](../behavior-frontier.json) —
  `counters.counter_4.deferrals.rows` is `{}`, and both counter-4 targets read
  `deferred 0`, `gap 0`, `met true`. `behavior_frontier.py --check` exits 0.
* [`receipt-walk-retirement-schedule.json`](receipt-walk-retirement-schedule.json)
  — `families` is `{}` and `scheduled_slices` is **0**;
  `receipt_walk_schedule.py --check` exits 0.
* `interpreters.INTERPRETERS` holds exactly **13** `(family, RECEIPT_WALK)` keys.
* `term_census.py --check`: **29** post-authoring packet-mutation sites, 0
  uncovered; **9** authoring-time mitigation terms, 0 uncovered; **3** static
  holder amps, 0 unfolded. That is the gate Amendment N put in front of any
  further retirement, and it is clean.

The fourteen are accounted for as **10 + 1 + 3**, and each third has a different
authority, which is why the sum matters more than the total. Ten left by the
ruled retiring act — `d48d042`, `0cd6a9f`, `0b8bded`, `928332c`, `c9d4ac8`,
`6462085`, `d44ba92`, `4e340f3`, `b7f64cb` and the amp-term delivery at
`38f4702` — under Amendments F, K, L, M, N and R. One left by **Amendment O**,
Ruling 1: `crit_profile` authors no pair row anywhere in its covering
population, so its deferral row was a schedule category error rather than a
debt, and it closes by authority reclassification with a machine check that
**reopens** the row if a future mechanic of the family ever authors one
(`7af43f8`). Three left by **Amendment Q**: `combat_state`, `opening_defense`
and `threshold_defense` are served through their declared `DEFENSE_RESOLVER`
lane, so a receipt-walk interpreter there would be the second producer of one
number that D-60 and criterion 8 forbid in terms, and the correction is that the
table stops declaring a lane it must not (`be85720`), again with a check in both
directions and a reopening condition.

Amendment F's one prohibition is the thing to check against, and it is
satisfied: *"no phase document may read this amendment as permission to stop
counting them."* Nobody stopped counting. All fourteen were counted, each
retired or reclassified by a named act with its own `Expected qualifying
occurrences` line, and the row that records them is the count.

**G4 → CLOSED**, named to the ten retiring commits and to `7af43f8` and
`be85720`, unblocked by **Amendment O**.

### 16.3 Criterion 11 — measured, and not closed

Runbook criterion 11 stands **NOT DISCHARGED as written**, exactly as §12.5
grades it, and nothing in this section supersedes that sentence. What this
section adds is measurement and one fact about the mechanism that whoever rules
G14 does not currently have written down anywhere.

**Clause 1 — every slice has a recorded `verify-<slice>` verdict.** Measured on
this tip: **127** slice tags derived from commit subjects, **128** recorded
passes, and a residue of **3** — `campaign-close-verify-p4-batch`,
`campaign-close-final-integration-r35`, and `campaign-close-certification`, the
tag of this pass. All three are prepared as startable rows in
[`verify-backlog.json`](verify-backlog.json) and none has been run. This lane
did not run them and could not: R-35's verifier is *a fresh read-only Opus 5
that has not read the plan*, and a lane that has read the plan writing one would
be the unverifiable claim about the past Phase 1 outlaws.

**Clause 2 — no barrier is crossed with an open `NOT DISCHARGED`.** Over the
ledger's 128 passes: **90** `NOT_DISCHARGED` rows, of which **60** stand
`documented_open`, 23 `fixed` and 7 `fixed_and_gated`.

Two of them moved in this pass and neither moved by judgement. Round 1's
`umbrella-7` reads *"fourteen deferral rows still retire at a stage that shipped
without retiring them"* and round 3's `runbook-9` reads *"22 standing oracle
dissents remain open debts"* — those are the findings §16.2 and §16.1 measure to
zero, so each row now names the commits that answered it and its disposition is
`fixed`. The verdicts are untouched: a verdict is the verifier's artifact and a
disposition is the lane's, which is what the ledger's own
`when_a_later_lane_answers_a_sweep_row` rules in those words.

The other 60 stay exactly as filed. Re-dispositioning one is a judgement about a
verifier's finding, and a lane making it about the lanes being checked is the
reconstruction `what_this_ledger_does_not_hold` refuses. The clause is unmet, and
it is unmet by 60 rather than by 62 because two of them were answered rather than
re-read.

*Anchored 2026-08-17. The seven ledger readings in the two clauses above were
readings of this section's own tip when `3799bef` wrote them, and §16.6 wrote
down in advance what the next pass that moved one had to choose between —
restate the figure, or anchor it the way `SECTION_15_5_ANCHOR` does. Round 129
moved two of them, by transcribing an R-35 verdict that had been rendered on
this campaign and never recorded, so they stay exactly as written and
`tests/test_campaign_close_report_figures.py` reads them at
`git show 3799bef:docs/receipts/verify-ledger.json`. The live readings are in
that file's coverage block, which is where §12.4 says they live, and §17 states
them as of its own tip. What the anchoring does not touch is either clause's
grade: criterion 11 is not discharged, by the same two clauses, on this tip as
on that one.*

**The fact that is new.** The owed ruling —
[`rulings-owed.json`](rulings-owed.json)'s
`whether_criterion_11s_first_clause_binds_the_campaign_backwards`, still the one
open row of nine answered — offers two branches: bind the clause backwards and
schedule the residue's passes, or read it forwards and let the gate hold the
next slice group. **Neither branch reaches zero, and the reason is structural
rather than a matter of anybody working harder.** Recording a verdict is itself
a commit; every commit carries a slice tag; a tag with no verdict is residue. So
the act of closing the residue creates residue. The ledger's own history is the
measurement: rounds 123–127 were recorded by lanes whose tags then needed
verdicts and got them from later rounds, round 128's recording lane
(`campaign-close-final-integration-r35`) is the live end of that chain today,
and this pass adds a second live end by existing.

There is a third branch, and it is the only one that terminates: **a group's
verdict may be recorded by a commit carrying that same group's tag.** Round 128
had it available and declined it in terms — *"the answering group's own tag takes
its place there, because a lane cannot verify itself and the residue says so
rather than closing on a lane's word"* — which is a convention, honestly chosen,
and not an impossibility. Whether the clause's unit is the slice group (in which
case a group with a recorded verdict is covered, and the recording commit inside
it is not a second slice) or the commit (in which case the residue has no zero at
all) is precisely the reading the owed ruling exists to settle.

Naming a branch is not choosing one. `rulings-owed.json`'s own
`what_a_lane_may_do_and_has_done` draws exactly this line — *"price the branch it
may not choose"* — and a branch nobody has priced because nobody has written it
down is the cheapest thing a lane can hand whoever rules. **G14 stays OPEN**,
its blocker unchanged, and this pass closes nothing about it.

### 16.4 The gaps, as they finally stand

*The report's final table, derived-checked against
[`campaign-gap-ledger.json`](campaign-gap-ledger.json) by
`tests/test_campaign_gap_ledger.py`. §12.4's preamble applies to it word for word,
including which artifact owns each live figure: the ledger names them and its gate
reads each at run time, so no count in this table has a second home.*

| # | State | Blocks | Where it stands |
|---|---|---|---|
| **G1** | **CLOSED** | umbrella criterion 5 | `09956f8`, the campaign's second and last closing re-capture. |
| **G2** | **CLOSED** | umbrella criterion 1's emission clause | `4b8779e`, unblocked by **Amendment E**. |
| **G3** | **CLOSED** | umbrella criterion 8 | `69e7323`. 290 applied contributions claimed, 0 unidentified. |
| **G4** | **CLOSED** | umbrella criterion 7, and Amendment B's exit clause behind it | All fourteen `RECEIPT_WALK` deferral rows have left — ten by the ruled retiring act, one by **Amendment O**'s authority reclassification, three by **Amendment Q**'s lane-declaration correction; §16.2. `counter_4.deferrals.rows` is `{}`. |
| **G5** | **CLOSED** | umbrella criterion 4's non-plan half | **Amendment H**, mechanised at `1e209e2`. |
| **G6** | **CLOSED** | runbook criterion 9's repo-wide reading | `b299978` is clause 2's ruled `src/` slice and `4f41e6e` is the pin that followed it; §16.1. 0 open debts, and 7 blocking members all `citation`. |
| **G7** | **CLOSED** | Phase 4's criterion 14, and criterion 16's fallback-cause clause | `5c19b1f` and `0f3adca`. |
| **G8** | **CLOSED** | umbrella criterion 11's `[H]` clause, read strictly | `1de067b`. |
| **G9** | **OPEN BY DESIGN** | nothing | `enhanced_consume` has no producing champion; H6's ruling is that Phase 5 ships exactly this. |
| **G10** | **CLOSED** | umbrella criterion 1's frontend change budget clause | **Amendment I**. |
| **G11** | **OPEN** | nothing this campaign's criteria assert | Two defects in cached wiki text, not in `src/` (`98351d1`). Outside this scope and gated where it sits. |
| **G12** | **CLOSED** | nothing — a live operational risk, not an unmet criterion | `19b03d7`, unblocked by **Amendment G**. |
| **G13** | **CLOSED** | runbook criterion 12 | `6549e32`. |
| **G14** | **OPEN** | runbook criterion 11's first clause | The campaign's one certification blocker, and an owed ruling. Not a lane's; §16.3 measures what it now costs and closes nothing. |

### 16.5 The re-grade

*Two gap rows move and one umbrella criterion moves with them. Everything else
in §6, §12.5 and §15 stands exactly as written.*

* **Umbrella criterion 7 — DISCHARGED, under Amendments F, K, L, M, N, O, Q and
  R.** Its named blocker was G4 and G4 is closed. §6 graded it PARTIALLY
  DISCHARGED on one sentence — *"the rows are still present and still `owed_to`
  that stage"* — and the rows are not present: `counter_4.deferrals.rows` is
  `{}`. §12.5 carried the grade forward on the same blocker and was right to,
  because on its own tip the debt was live. This line re-reads nothing. It is
  §12.5's own rule applied where §12.5 said it applies: *"a criterion graded
  short of what its own blockers say is the same defect as one graded past
  them"*, and *"both closures are recorded in the umbrella by its owner, and
  this line states their consequence."* Every act that closed G4 is an
  amendment the umbrella's owner wrote or a lane act performed under one.
* **Runbook criterion 9's repo-wide reading — met.** G6 is closed; every
  campaign occurrence satisfying `qualifies_for_investigation` has its receipt,
  and the blocking population is what §16.1 measures — every member a
  `citation`, and no open debt standing.
* **Runbook criterion 11 — NOT DISCHARGED, unchanged.** §12.5's sentence stands
  word for word: *the campaign is not certified against its own runbook while
  that clause is unread.* §16.3 measures what is left and adds a branch to the
  question; it answers none of it. What is outstanding is one decision with a
  cost and an owner, and it is the same one §12.4 named.

### 16.6 What gates section 16

Section 15 exists because section 14 was ungated and three of its figures were
wrong. Section 16 closes two gap rows and states a criterion's re-grade, so its
counts are the load-bearing ones in this report, and it ships with its gate
rather than after one.

[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
re-derives every figure this section states by running the instrument it was
measured with: §16.1's four from `standing_dissent_scan.report()`, §16.2's five
from the retirement schedule, the interpreter registry and a fresh `term_census`
run, and §16.3's seven from the verify ledger's own pass rows and coverage block.
**17** figures, the count itself among them, and R-05's red rides beside each —
`test_the_section_16_gate_fails_when_a_stated_figure_drifts` doctors the value in
a copy of the section and requires the same comparison to fail. §16.7 states no
figure at all, and §16.7 says why: a gate reading cannot be re-derived without
re-running the gate it came from, so the one place this section could carry an
ungated number is the one place it carries none.

Two things the same commit had to fix, and both are the shape section 15 was
already in. `section_15()` read from its own heading to the end of the file,
which was true until a section 16 existed and would have let one section's gate
match another section's figure. It is bounded at `## 16.` now. And §15.5's five
coverage figures were readings of *this tip* when `e4338b7` wrote them; this
pass shipped a slice group and moved them, so they are anchored at that commit
and read out of git, exactly as §15.1's six dated residues already are. The
section's text is untouched and carries one dated clause beside it.

Section 16's own figures are read **live**, because they are facts about this tip
rather than dated readings. The next pass that moves one faces the same choice
`e4338b7`'s did, and now has both answers written down: restate the figure, or
anchor it the way `SECTION_15_5_ANCHOR` does.

### 16.7 The R-01 matrix on this pass's tip

| # | Verdict |
|---|---|
| 1 | **GREEN** |
| 2 | **GREEN** |
| 3 | **GREEN** |
| 4 | **GREEN** |
| 5 | **GREEN** |
| 6 | **GREEN** |
| 7 | **GREEN** |
| 8 | **GREEN** |
| 9 | **GREEN** |
| 10 | **GREEN** |
| 11 | **GREEN** |

`plan_audit.py` (R-37) clean, and `sole_home_scan.py --check`,
`standing_dissent_scan.py --check`, `behavior_frontier.py --check`,
`migration_frontier.py --check`, `receipt_walk_schedule.py --check`,
`term_census.py --check` and `verify_backlog.py --check` all exit 0.

**What each row read is in this pass's commit bodies, not here**, for the reason
§15.8 gives and this section proved by getting it wrong first: a figure in this
section is one §16.6's gate re-derives, and a gate reading cannot be re-derived
without re-running the gate it came from. This table carried a suite count for
one commit; the count was already stale when it was written, because the commit
that wrote it declared 34 node ids of its own. That is the ungated-figure failure
section 15 exists about, reproduced inside the section that gates itself, and the
fix is the one §15.8 already ruled: verdicts here, numbers where R-01 puts them,
one commit at a time.

**No `src/` is touched in this pass and no baseline moves in it** —
`git diff --name-only 04cdfbf..HEAD -- src/` and the same over R-32's five
baselines are both empty, over the whole range. The one `src/` correction any of
this rests on is `b299978`, which landed before the review that raised the
finding, and the pin that followed it is `4f41e6e`. Both compared baselines read
`snapshot identical` on every commit here, so there is nothing for a boundary
re-capture to absorb and none is performed (R-17, R-32).

*Corrected and anchored 2026-08-17. The sentence above was a reading of
`3799bef`, the tip that wrote it, and it is false of this one: `927964c` moved
`campaign-fingerprints.json` — one of the five — inside `04cdfbf..HEAD`. The
move is legal and disclosed, Amendment R-32's fourth carve-out putting a
`tests{collected}` re-pin with the owning lane, and that commit's body and the
receipt's `tests` block carry the three facts the carve-out asks for; what was
wrong was the sentence claiming the range empty, left standing by the commit
that falsified it. It stays written for the reason this section gives about its
own wrong table, and what holds on this tip sits beside it as a property rather
than as a second reading: the `src/` half is still empty over the whole range,
no commit in the range touches both `src/` and one of the five (R-17, D-97,
criterion 10), and every commit that moved one of the five moved only
`campaign-fingerprints.json` and touched no `src/`, no gate script and neither
compared baseline. Measured over the fixed range `04cdfbf..927964c`, that commit
is the only mover — a range that ends where it ends, so this clause cannot go
stale the way the sentence above it did.
[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
runs all four over both ranges, so the next legal re-pin keeps them green and a
move outside the carve-out turns them red.*

**What is left, in one sentence.** Runbook criterion 11 is not discharged, its
one open ruling belongs to the campaign's owner, and §16.3 states what the
question now costs and the third branch nobody had written down. Everything else
in both documents is discharged, or discharged under a named amendment, with its
residue measured, gated and owned.

## 17. The certification re-review — one verdict found, four defects fixed, one decision still the owner's

*Appended 2026-08-17. Section 9's rule applies to it as to every section before
it: nothing above is rewritten, and where this pass moved a figure an earlier
section stated, that figure is anchored at the commit that stated it and read
out of git rather than restated. §16.3's seven ledger readings are anchored that
way, at `3799bef`.*

A certification review withheld sign-off with one blocker and two minors. The
blocker is that runbook criterion 11 is not discharged and cannot be discharged
by any lane — which is true, and this section does not claim otherwise. What
this pass did is everything a lane may do around it, and one thing nobody had
noticed was available.

### 17.1 The thing that was available: a verdict already rendered, never recorded

Criterion 11's first clause had a residue of three, and the review named all
three as *"prepared as startable rows in verify-backlog.json, none run"*. One of
them had been run. An R-35 verifier — a fresh read-only Opus 5 handed round
128's brief verbatim, *"plus any subsequent fix commits up to current HEAD"* —
was spawned on 2026-08-17 at HEAD `04cdfbf`, after the whole
`campaign-close-final-integration-r35` group had landed. It verified twelve
commits in its own words, returned all four criteria `DISCHARGED`, and named
five behaviours the twelve commit bodies do not mention. Its report sat in the
orchestration journal and in no artifact.

Recording it is the ledger's own admissible route, and the one it distinguishes
by name from the reconstruction it refuses: the `backfill` and `residue_sweep`
blocks transcribe *the verifier's artifact*, joined to a slice tag **by commit**
— *"a tag is covered when a verifier verified a commit that carries it"* — and
never a later reader's account of a commit body. Eight of the twelve carry the
tag; the verifier's evidence names six of them by sha while re-deriving their
corrections rather than trusting them.

Round 129 is that transcription. Coverage moves to **125** tags with a verdict
of **128** derived from commit subjects, and the residue is **3**, over a
membership one group younger: `campaign-close-final-integration-r35` left it on
a verifier's artifact and `campaign-close-certification-r2`, this pass's own
tag, took a place beside `campaign-close-certification`'s. That is the mechanism
§16.3 measured, holding exactly: recording a verdict is itself a commit, a
commit carries a tag, and a tag with no verdict is residue.

*Anchored 2026-08-17. The three coverage readings above were facts about this
tip when `407428f` wrote them, and the mechanism this paragraph describes is
exactly what moved them: the pass that appended §18 shipped a slice group of its
own, so the tag total and the residue both went up. They stay written and are
read at the commit that stated them, `git show 407428f:docs/receipts/verify-ledger.json`,
which is the branch §16.6 wrote down and §17's own preamble applies to every
section above it. §17.3's six readings of the same artifact are anchored with
them rather than one at a time, for the reason §16.3's seven were. The live
readings are in that file's coverage block, which is where §12.4 says they live.*

### 17.2 What the verifier found, and what happened to each

Five findings, four of them defects in the campaign's own closing artifacts —
each a claim a receipt made that the tree contradicted, which is the failure
shape this campaign exists to remove, arriving inside the pass that was
removing it. Round 129's findings, dispositioned: **4** fixed and **1**
documented.

| # | The finding | Disposition |
|---|---|---|
| 1 | the verify ledger's residue note states a population the backfill falsified | `fixed` — `bf5b808` |
| 2 | G14's blocker holds a value and its note says the residue does not fall | `fixed` — `bfbc33a` |
| 3 | the owed row's measurement went stale inside the lane that wrote it | `fixed` — `16ebb97` |
| 4 | the section gate pins abbreviated shas and shells out to `git show` | `documented_open` |
| 5 | the section gate's coverage claim is an enumeration, not a property | `fixed` — `e5abdbe` |

Each fix ships the gate the finding says did not exist, and each gate carries
R-05's red: a count in the residue note must sit inside a dated clause; an open
gap row's blocker may hold no count and must name a `live_figures` key that
grades that gap; the owed row's dated reading is anchored at `b02e4ca` and
re-derived out of git while its live readings are named rather than restated;
and both gated sections are now *scanned* for a bold figure nothing reads
instead of holding a list of the figures somebody remembered.

Finding 4 is documented rather than fixed, and the reason is that the
alternative is a different fragility rather than none. An amend or rebase of a
pinned anchor turns R-01 row 1 red; resolving anchors by commit subject instead
goes red on a reworded subject. What makes the trade deliberate is that every
anchor is a named constant with a comment saying what it anchors, so moving one
is an act rather than an accident — and the verifier rates the finding low
severity itself.

### 17.3 The blocker, and what is left of it

Runbook criterion 11 stands **NOT DISCHARGED**, exactly as §12.5 grades it and
§16.3 restates it, and nothing in this section supersedes that sentence.

*Clause 1 — every slice has a recorded verdict.* The residue is **3**:
`campaign-close-verify-p4-batch`, whose single commit no verifier's brief has
ever reached; `campaign-close-certification`, the previous pass's tag; and this
pass's own. [`verify-backlog.json`](verify-backlog.json) prepares **3** startable
passes and this lane ran none, for the reason it could not: R-35's verifier is
*a fresh read-only Opus 5 that has not read the plan*, and a lane that has read
the plan writing one would be the unverifiable claim about the past Phase 1
outlaws. What this lane could do was record a verdict somebody else's verifier
had already rendered, which is a transcription and not a verdict, and it is
done.

*Clause 2 — no barrier is crossed with an open `NOT DISCHARGED`.* **90**
`NOT_DISCHARGED` rows stand over the ledger's **129** passes, of which **60**
are `documented_open`. None moved in this pass and none could: re-dispositioning
a verifier's finding about the lanes being checked is the reconstruction
`what_this_ledger_does_not_hold` refuses. Round 129's four fixed rows are
*finding* rows, not criterion rows, so this clause is unmoved by them and says
so.

**What is still owed, and by whom.** [`rulings-owed.json`](rulings-owed.json)'s
`whether_criterion_11s_first_clause_binds_the_campaign_backwards` is the one
open row, and three branches now stand priced beside it rather than two: bind
the clause backwards and schedule the residue's prepared passes; read it
forwards and let the forward gate hold the next slice group; or rule that a
group's verdict may be recorded by a commit carrying that same group's tag,
which §16.3 measured is the only branch that terminates. This pass added the
input the ruler needs and did not have — the **159** commits in the range
carrying no slice tag, named in the owed row itself as part of the same
question, because whether an untagged commit is outside "every slice" or
evidence the convention was not universal is the same question the clause asks.

**A lane may not choose among the three**, and the three shortcuts stay refused
by name: manufacture a verdict, reconstruct one from the bodies of the lanes
being checked, or shrink the denominator. So the campaign is not certified
against its own runbook, the reason is one decision with an owner, and every
input that decision needs is now in one artifact a reader can open.

*Anchored 2026-08-17, with §17.1's three and for the same reason. The six ledger
readings in this subsection were facts about `407428f`; the pass that appended
§18 shipped a slice group, which moved the residue and the prepared-pass count
and left the other four where they were. All six stay written and are read at
`git show 407428f:` their artifact — `verify-ledger.json` for five and
`verify-backlog.json` for the sixth. What the anchoring does not touch is either
clause's grade: criterion 11 is not discharged, by the same two clauses, on this
tip as on that one, and §18.2 says so again without restating a figure.*

### 17.4 The two minors

**R-01 row 1's second half.** The review is right that *"collected = pinned
count + declared new"* is not dischargeable from the fingerprints receipt alone,
and this pass measured whether the route the review names — walking the
declaring lanes' commit bodies — could discharge it. It cannot. Measured over
`584071e..993f97e`, **60** commit bodies state a node-id declaration a parser
can read and **37** more mention node ids in a phrasing no parser reads, and the
parseable ones sum past the collected count, because commit prose quotes other
commits' declarations and is not a declaration format. So the arithmetic is
dischargeable by a re-pin or by re-collecting at the pin's anchor commit:
Amendment R-32 puts the first with the owning lanes, and the second needs a
worktree this lane may not create. The suite is green with `skipped` and
`xfailed` both 0.

**And this pass proved the point against itself.** Measured at `993f97e`, where
the scan above is anchored: its own declarations sum to twenty-nine and the
suite moved by thirty-one. The missing two are in `bfbc33a`,
whose body declares four node ids and enumerates five in the same sentence,
while six landed: the sixth is the parametrised live-figure check, which gained
a case when that commit added a counter to `live_figures` — a node id the tree
generated from data rather than one anybody typed. The file holds **56** node
ids at this tip. The correction is here rather than in the body, because a body
is not amendable, and it is the same finding the minor names one level in: a
declaration written as prose is checked by nobody, including the lane writing
it.

**And the half of the minor that *is* this lane's, done.** Amendment R-32's
fourth carve-out says the pin moves whenever a lane's slices declare new node
ids and that the moment is a lane's commit; this pass's slices declared some, so
the pin moved in a receipt-only commit touching no `src/`, no gate script and
neither compared baseline. No figure of it is restated here: the old value, the
new one, the tip each was measured on, the per-slice decomposition of this
pass's own declarations and the disclosure that the passes between never
re-pinned all live in [`campaign-fingerprints.json`](campaign-fingerprints.json)'s
`tests` block, which is the artifact that owns them. What the move does not do is
claim the intervening declarations as this pass's, and the block says so in its
own words. What it does is stop the pin describing a tip that no longer exists,
so the next lane's *"collected = the pinned count + declared new"* is an
arithmetic somebody can do.

**The commits outside the denominator.** Named to whoever rules, in the owed row
itself, at `d5e95f0` — with the two things a lane may not do about it written
beside it: retro-tagging a subject rewrites the history the denominator is
derived from, and declaring the untagged commits "not really slices" is the
denominator-shrinking shortcut said out loud.

### 17.5 The gaps, and the report's final table

**No gap row changes state in this pass.** G14 stays `OPEN` on the ruling it has
always named, its blocker corrected to name a counter rather than hold one; G11
stays `OPEN` on the two cached-data defects outside this campaign's scope; every
closed row stays closed. §16.4 therefore remains the report's final gap table
and this section states none, which is what the gap ledger's own rule asks for:
one place holds the state, and a second table restating it is a second home.

### 17.6 What gates section 17

[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
re-derives every figure this section states from the instrument it was measured
with — the verify ledger's coverage block and pass rows, the backlog, round
129's own finding rows, and for the node-id figures a scan of the campaign
range's commit bodies anchored at `993f97e` and a live collection of the file
they are about. **15** figures, the count itself among them, each with
R-05's red beside it, and the completeness scan §17.2's fifth finding bought
now runs over this section too: a bold figure this file does not read fails the
gate on the commit that writes it.

One thing this section forced, and it is the same thing section 16 forced when
it arrived: `section_16()` read from its heading to the end of the file, which
was right until a section 17 existed and would have let this section's figures
be matched as that one's. It is bounded at `## 17.` now.

### 17.7 The R-01 matrix on this pass's tip

| # | Verdict |
|---|---|
| 1 | **GREEN** |
| 2 | **GREEN** |
| 3 | **GREEN** |
| 4 | **GREEN** |
| 5 | **GREEN** |
| 6 | **GREEN** |
| 7 | **GREEN** |
| 8 | **GREEN** |
| 9 | **GREEN** |
| 10 | **GREEN** |
| 11 | **GREEN** |

`plan_audit.py` (R-37) clean, and `sole_home_scan.py --check`,
`standing_dissent_scan.py --check`, `behavior_frontier.py --check`,
`migration_frontier.py --check`, `receipt_walk_schedule.py --check`,
`term_census.py --check` and `verify_backlog.py --check` all exit 0.

**What each row read is in this pass's commit bodies, not here**, for the reason
§15.8 ruled and §16.7 restates: a gate reading cannot be re-derived without
re-running the gate it came from, so the one place this section could carry an
ungated number is the one place it carries none.

**No `src/` is touched in this pass and no baseline moves in it** —
`git diff --name-only 3799bef..HEAD -- src/` and the same over R-32's five
baselines are both empty over the whole range, and both compared baselines read
`snapshot identical` on every commit here.

*Corrected and anchored 2026-08-17, and the finding is a certification
reviewer's. The sentence above was a reading of `407428f`, the tip that wrote
it, and the very next commit falsified it without touching it: `927964c` moved
`campaign-fingerprints.json`, one of the five, inside `3799bef..HEAD`. The move
is legal and fully disclosed under Amendment R-32's fourth carve-out — the
paragraph above records it in this section's own words — and what was wrong is
the sentence, which is this report's prose-outruns-tree shape arriving inside
the section that records four fixes of it. So it stays written, and what holds
on this tip sits beside it as a property rather than as a second reading: the
`src/` half is empty over the whole range, no commit in it touches both `src/`
and one of the five (R-17, D-97, criterion 10), every commit that moved one of
the five moved only `campaign-fingerprints.json` and touched no `src/`, no gate
script and neither compared baseline, and both compared baselines still read
`snapshot identical`. Measured over the fixed range `3799bef..927964c`, that
commit is the only mover — a range that ends where it ends, so this clause
cannot go stale the way the sentence above it did. §16.7 carried the identical
sentence over a wider range and was falsified by the same commit, which the
review did not name and this pass's population enumeration did;
[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
gates both.*

**What is left, in one sentence.** Runbook criterion 11 is not discharged, the
one decision that could discharge it is the owner's and now has all three of its
branches, its population hole and its exact cost written in the row that asks
it — and every defect a fresh verifier found in the artifacts that say so has
been fixed and gated.

## 18. The third certification review — one minor fixed in both its copies, one decision still the owner's

*Appended 2026-08-17. Section 9's rule applies here as everywhere above: nothing
before this line is rewritten, and where this pass corrected a sentence an
earlier section states, the sentence stays written and carries a dated clause
beside it. §16.7 and §17.7 each gained one.*

A third certification review withheld sign-off with one blocker and one minor.
The blocker is that runbook criterion 11 is not discharged; §17.3 says so
already and in the same terms, so what this review adds to it is a confirmation
from a reader who had not seen that section, not a fact. The minor is a real
defect, and it is fixed in both of the places it lives rather than the one that
was named.

### 18.1 The minor, and the copy the review did not name

The review found §17.7's closing sentence — that `3799bef..HEAD` is empty over
the five baselines R-32 lists — contradicted by the tip, because `927964c` moved
`campaign-fingerprints.json` inside that range. It is right, and right about the
shape as well as the fact: the move is legal under Amendment R-32's fourth
carve-out and disclosed in that commit's body and on the receipt, so what was
wrong is the sentence, left standing by the very commit that falsified it.

R-20's second half asks for the population before the edit, and the population
is what turned one finding into two. **5** sentences in this report assert that
a commit or a range is free of moves over those five baselines: the header's
doc-only line for `067c94c`, §4's *both*-claim over `584071e..067c94c`, §15.8's
lane-scoped one, and §16.7's and §17.7's range-to-`HEAD` pair. **2** of them
qualify — both name a range ending at `HEAD`, and `927964c` sits inside both —
and the review named one of the two. §16.7 makes the identical claim over the
wider range and was falsified by the same commit. Enumerating before editing is
what found it; the other three are re-measured here and none qualifies.

Neither sentence is edited. Each gains the dated clause §16.6 named in advance
as the choice a later pass would face, and the clause is deliberately not a
second reading. It anchors one range that ends where it ends —
`04cdfbf..927964c` and `3799bef..927964c`, in which that commit is the only
mover — and states everything else as a property, which is what a `..HEAD`
sentence should have been in the first place: the `src/` half is empty over the
live range; no commit in it touches both `src/` and one of those five, which is
criterion 10 and the rule the sentence was standing in for; and every commit
that moved one of them moved only `campaign-fingerprints.json`, touching no
`src/`, no gate script and neither compared baseline. A property survives what a
reading does not — this pass's own re-pin is a legal move inside that carve-out
and the checks stay green across it, where a restated reading would have gone
stale on the commit after the one that wrote it, exactly as the sentence above
each clause did.

### 18.2 The blocker, restated and not moved

Runbook criterion 11 stands **NOT DISCHARGED**. §12.5 grades it, §16.3 restates
it at its own anchor and §17.3 states both clauses live; no figure of it is
restated here, because those sections and the two artifacts they read own them.

The review's own list of what would close it names four acts, and every one of
them is outside a lane by a rule this campaign wrote down before the question
arose. Reading the clause forwards re-reads "every slice", which umbrella
criterion 11 forbids a phase document from doing. Reading it backwards schedules
the residue's prepared passes, which is a scheduling decision with a cost and an
owner. Ruling that a group's verdict may be recorded by a commit carrying that
group's own tag is the same act on the third branch §16.3 measured. And
re-dispositioning clause 2's `documented_open` rows is a judgement about a
verifier's finding, made by a lane the finding is about — the reconstruction
`what_this_ledger_does_not_hold` refuses and §15.5 already ruled stays as filed.

What is left that a lane may do is *run* the residue's prepared passes, and
running one chooses nothing: it pays a cost either branch of the ruling can
spend. This lane could not. R-35's verifier is *a fresh read-only Opus 5 that
has not read the plan*, this lane has read them, and it has no way to put the
brief in front of one; §17.3 recorded the same limit one pass earlier and
nothing about it has changed. So this section ends where §17.5 and the report's
closing sentence already end: the campaign is not certified against its own
runbook, the reason is one decision with an owner, and every input that decision
needs sits in one artifact a reader can open.

### 18.3 The gaps

**No gap row changes state in this pass.** G14 stays `OPEN` on the ruling it has
always named, G11 stays `OPEN` on the two cached-data defects outside this
campaign's scope, and every closed row stays closed. §16.4 therefore remains the
report's final gap table and this section states none, for the gap ledger's own
reason: one place holds the state, and a second table restating it is a second
home.

### 18.4 What gates section 18

[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
re-derives every figure this section states from the thing it was measured with
— the report's own text for the enumerated population, and the gate module's
`BASELINE_CLAIMS`, `PROPERTY_RANGES` and its parametrised checks for the rest.
**4** figures, the count itself among them, each with R-05's red beside it, and
the completeness scan §17.2's fifth finding bought runs over this section too.

**6** parametrised checks carry §18.1's correction. Three read the claim's own
history over `BASELINE_CLAIMS` — that each sentence was true of the tip that
wrote it, that it is false of this one, and that the range each dated clause
names holds exactly the mover it names. Three assert the properties over
`PROPERTY_RANGES`, which is the two claimed ranges plus this pass's own. Their
reds are a seam and not a fixture: six commits that are not in the tree break
the carve-out's four conditions one at a time, break criterion 10, and touch
`src/`.

The population figure is a scan rather than a list, which is §17.2's fifth
finding applied one level up: a sixth sentence in this report claiming a range
free of baseline moves turns this red on the commit that writes it, instead of
sitting silently outside an enumeration somebody remembered.

And this section forced what sections 16 and 17 each forced when they arrived:
`section_17()` read from its heading to the end of the file, which was right
until a section 18 existed. It is bounded at `## 18.` now.

### 18.5 The R-01 matrix on this pass's tip

| # | Verdict |
|---|---|
| 1 | **GREEN** |
| 2 | **GREEN** |
| 3 | **GREEN** |
| 4 | **GREEN** |
| 5 | **GREEN** |
| 6 | **GREEN** |
| 7 | **GREEN** |
| 8 | **GREEN** |
| 9 | **GREEN** |
| 10 | **GREEN** |
| 11 | **GREEN** |

`plan_audit.py` (R-37) clean, and `sole_home_scan.py --check`,
`standing_dissent_scan.py --check`, `behavior_frontier.py --check`,
`migration_frontier.py --check`, `receipt_walk_schedule.py --check`,
`term_census.py --check` and `verify_backlog.py --check` all exit 0.

**What each row read is in this pass's commit bodies, not here**, for the reason
§15.8 ruled and §16.7 and §17.7 restate: a gate reading cannot be re-derived
without re-running the gate it came from.

**What this pass did to `src/` and to the baselines, as a property.** This
paragraph is written the way §18.1 corrected the two before it, rather than
claiming a `..HEAD` range empty a third time. Over `407428f..HEAD`: the `src/`
half is empty; no commit touches both `src/` and one of those five; and every
commit that moved one of them moved only `campaign-fingerprints.json`, touching
no `src/`, no gate script and neither compared baseline — this pass's
`tests{collected}` re-pin for the node ids it declared, inside Amendment R-32's
fourth carve-out and disclosed in its own body. The three checks §18.4 names run
over this range as over the two before it, and both compared baselines read
`snapshot identical` on every commit here.

**What is left, in one sentence.** Unchanged from §17.7's: runbook criterion 11
is not discharged, the one decision that could discharge it is the owner's, and
every defect two fresh readers found in the artifacts that say so has been fixed
and gated.

## 19. The fourth certification review — three minors closed, and the blocker's timing argument handed over

*Appended 2026-08-17. Section 9's rule applies here as everywhere above:
nothing before this line is rewritten, and where an earlier section states a
figure this pass moved, that figure stays written and is read at the commit
that stated it. §16.3's seven readings are anchored at `3799bef` and §17's
nine at `407428f`; this pass moves one of the ledger's live counters and
neither anchor with it.*

A fourth certification review withheld sign-off with one blocker and three
minors. The blocker is that runbook criterion 11 is not discharged, that no
further lane work can discharge it, and that the decision is the campaign
owner's — which is exactly what §17.3 and §18.2 already say, and this section
does not claim otherwise. What is new is in the minors, and in one sentence
the review wrote about the blocker that had never been carried to the artifact
whoever rules opens.

### 19.1 The blocker, and the one thing a lane could add to it

Runbook criterion 11 stands **NOT DISCHARGED**, by both clauses, as §12.5
grades it and §16.3, §17.3 and §18.2 restate it.

*Clause 1.* The residue is **5**: `campaign-close-verify-p4-batch`, whose
single commit no verifier's brief has ever reached; the three previous
certification passes' tags; and this pass's own, added by its first commit
rather than by a later one. [`verify-backlog.json`](verify-backlog.json)
prepares **5** startable passes and this lane ran none, for the reason every
pass since §17 has recorded: R-35's verifier is *a fresh read-only Opus 5 that
has not read the plan*, this lane has read them, and it has no way to put the
brief in front of one.

*Clause 2.* **90** `NOT_DISCHARGED` rows stand over the ledger's **129**
passes, of which **60** are `documented_open`. None moved and none could:
re-dispositioning a verifier's finding about the lanes being checked is the
reconstruction `what_this_ledger_does_not_hold` refuses.

*Anchored 2026-08-18. The five ledger readings in the two clauses above were
readings of this section's own tip when `53b792c` wrote them, and §16.6 wrote
down in advance what the next pass that moved one had to choose between —
restate the figure, or anchor it the way `SECTION_15_5_ANCHOR` does. The lane
recording the owner's ruling on criterion 11 moved two of them, by taking the
residue line its own tag owes, so they stay exactly as written and
`tests/test_campaign_close_report_figures.py` reads all five at
`git show 53b792c:docs/receipts/verify-ledger.json` through
`SECTION_19_LEDGER_ANCHOR`. The three that did not move are anchored with them
rather than left live, for the reason §17's anchor gives: a section read half
from a tip and half from git is a section no reader can date. Clause 1's
membership sentence dates the same way — "the three previous certification
passes' tags; and this pass's own" was that tip's residue, and the live list is
the ledger's own `slice_groups_without_one`. What the anchoring does not touch
is the grade: criterion 11 is not discharged, by the same two clauses, on this
tip as on that one.*

**What this pass added, and it is an input rather than an act.** The review's
first minor is a measurement about the mechanism rather than about the clause:
since round 129 every slice group to enter the residue has been a
certification pass answering a review of this very question, so the process
convened to grade the clause is now the only thing adding to what it grades.
§16.3 measured that mechanism and named the third branch — a group's verdict
may be recorded by a commit carrying that same group's tag, the only one of
the three that terminates — and both of those lived in a report section, which
is not what whoever rules opens. They are in
[`rulings-owed.json`](rulings-owed.json)'s own row now, in
`the_cost_of_deciding_late`, with the residue read through `live_figures`
rather than restated, and with what a lane may not do about each branch
written beside it: not adopt the third because it terminates, not adopt the
forward reading because the residue is inconvenient, and not stop recording
its own passes to keep the counter still, because an unrecorded pass is the
residue hidden rather than closed.

That is an argument about *when* the ruling is worth making. It is not an
answer, it chooses no branch, and the three refused shortcuts — manufacture a
verdict, reconstruct one from the bodies of the lanes being checked, shrink
the denominator — stay refused by name.

### 19.2 The counter that moved, and the cause it already carried

§5 states the migration frontier's counters as of `067c94c`, the tip the
report was written on, where counter 6's kernel value read **75**. This tip
reads **78**. Nothing is contradicted — the §5 reading is dated by the
report's own header, and the counter is a non-increasing ratchet whose bound
the tip holds with headroom — but the review is right that the movement was
unremarked wherever a reader of the closing artifacts would look, while every
other counter movement in this campaign carries a named cause.

The cause existed. **1** commit in `067c94c..HEAD` moved a migration-frontier
counter and **1** states the move in its own body: `b3a594b`, the
declared-pricing stage, whose body reads *"`docs/migration-frontier.json`
counter 6 moves 75 -> 78: the three `round(..., 6)` calls in the new
receipt"* — three calls in `apply_declared_price`'s receipt in
`survival/transitions.py`, spelled as `reprice_dynamic_resistance`'s own
receipt spells its. R-36 put the regenerated receipt in that commit, which is
what made the move a diff at all.

What did not exist is anything requiring it, so the property is asserted now:
every commit after the report's tip that moves one of these counters states,
in its own body, the counter and the value it moved from to the value it moved
to. The movement population is derived — a movement is a value the receipt
records differently from the commit before it — because a check ranging over
an authored list would be green about the movements somebody remembered. A
future move that arrives unremarked is red on the commit that lands it.

### 19.3 G11's scheduled home

G11's two cached-wiki-text defects are correctly outside this campaign's
scope, and that is exactly what left them unowned: the row named a blocker and
no home. Both entries name one now, in the artifact that owns them, and it is
a route that runs rather than a promise. `data/` has one writer, so no lane
may fix either in place; `patch_update.py run` is the only act that rewrites
the text, and its rebuild step already re-runs the two consumers the entries
name — `build_effect_catalog.py`, whose `_text` puts `simpleDescription`
first, and `build_receipts.py`, which reads the atomized item domain. The run
prints one line per open entry now, so the operator is told on the day the
lever is in their hand instead of being expected to have read a receipt, and
the gate asserts the schedule in both directions: every open entry names a
route that exists, and the named route really reads the artifact. Scheduling
is not fixing; both entries stay open and G11 stays `OPEN`.

### 19.4 The gaps

**No gap row changes state in this pass.** G14 stays `OPEN` on the ruling it
has always named and G11 stays `OPEN` on the same two defects, its note
gaining the dated clause that names where the work now lives. §16.4 therefore
remains the report's final gap table and this section states none, for the gap
ledger's own reason: one place holds the state, and a second table restating
it is a second home.

### 19.5 What gates section 19

[`tests/test_campaign_close_report_figures.py`](../../tests/test_campaign_close_report_figures.py)
re-derives every figure this section states from the instrument it was
measured with — the verify ledger's coverage block and pass rows, the backlog,
a fresh `migration_frontier` scan, the receipt `067c94c` left behind, and the
movement derivation in
[`tests/test_migration_frontier.py`](../../tests/test_migration_frontier.py).
**10** figures, the count itself among them, each with R-05's red beside it,
and the completeness scan §17.2's fifth finding bought runs over this section
too: a bold figure this file does not read fails the gate on the commit that
writes it.

This section's ledger figures are read **live** rather than anchored, which is
the choice §16.6 wrote down. They are facts about this tip, and this pass
moves one of them itself; the next pass that moves another faces the same
choice with both answers already written down.

One thing §19.6's closing paragraph does deliberately, and it is §18.5's
choice repeated rather than a new one. It is written in the *property* form —
what holds over the live range — and not in the spelling §18.4's scan counts,
because it makes no claim that a range is free of baseline moves; it says the
opposite, that this pass moved `campaign-fingerprints.json` inside a carve-out
and names it. Spelling it as a claim would have added a sixth site to a
population §18.1 enumerated and turned that section's gate red on a sentence
that asserts nothing §18.1 was about.

And this section forced what 16, 17 and 18 each forced when they arrived:
`section_18()` read from its heading to the end of the file, which was right
until a section 19 existed. It is bounded at `## 19.` now.

### 19.6 The R-01 matrix on this pass's tip

| # | Verdict |
|---|---|
| 1 | **GREEN** |
| 2 | **GREEN** |
| 3 | **GREEN** |
| 4 | **GREEN** |
| 5 | **GREEN** |
| 6 | **GREEN** |
| 7 | **GREEN** |
| 8 | **GREEN** |
| 9 | **GREEN** |
| 10 | **GREEN** |
| 11 | **GREEN** |

`plan_audit.py` (R-37) clean, and `sole_home_scan.py --check`,
`standing_dissent_scan.py --check`, `behavior_frontier.py --check`,
`migration_frontier.py --check`, `receipt_walk_schedule.py --check`,
`term_census.py --check` and `verify_backlog.py --check` all exit 0.

**What each row read is in this pass's commit bodies, not here**, for the
reason §15.8 ruled and §16.7, §17.7 and §18.5 restate: a gate reading cannot
be re-derived without re-running the gate it came from.

**What this pass did to `src/` and to the baselines, as a property.** Written
the way §18.1 corrected the two sentences before it, rather than claiming a
`..HEAD` range empty a fourth time. Over `407428f..HEAD`: the `src/` half is
empty; no commit touches both `src/` and one of those five; and every commit
that moved one of them moved only `campaign-fingerprints.json`, touching no
`src/`, no gate script and neither compared baseline — this pass's
`tests{collected}` re-pin for the node ids it declared, inside Amendment
R-32's fourth carve-out and disclosed in its own body. The three checks §18.4
names run over this range as over the two before it, and both compared
baselines read `snapshot identical` on every commit here.

**What is left, in one sentence.** Unchanged from §17.7's and §18.5's:
runbook criterion 11 is not discharged, the one decision that could discharge
it is the owner's — who now has all three branches, the population hole, the
exact cost and the argument for deciding soon in the row that asks the
question — and every defect four fresh readers have found in the artifacts
that say so has been fixed and gated.
