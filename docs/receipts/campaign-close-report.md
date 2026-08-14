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
