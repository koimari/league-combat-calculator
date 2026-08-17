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
