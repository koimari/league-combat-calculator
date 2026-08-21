# Phase 0 — Gate Hardening and Semantic Corrections

*Entry phase of the [Silent-Failure Campaign](2026-08-08-silent-failure-campaign.md). Gate commands,
golden protocol, bench fingerprints and residual, the investigator rule, the instrument signatures,
lanes and barriers are single-sourced in the [Campaign Runbook](silent-failure-runbook.md) — this
document links them and never restates their numbers or their function signatures.*

*Decisions owned: **D-01…D-14, D-90, D-93, D-94, D-99, D-100**, plus the 0A halves of the split
decisions **D-47** (the `patch_update.py` audit), **D-49** (`data_version()`'s declaration), **D-63**
(the derived phase list at version 1, bumped to 2 by C4) and **D-68** (every float-`phase` repoint).
Consumed but not owned: D-96 and D-97 (runbook protocol), D-98 (Phase 2), D-101 (Phase 3).*

*Prerequisite: **barrier B0.5** — Phase 5's `cast_dependency` leaf merges before C6, which imports
`orderable_slots` and `expand_user_order` from it. Nothing else in Phase 0 waits on anything.*

## Goal

Every gate the campaign leans on measures what it claims (slice 0A, zero numeric change in `src/`),
and every semantic defect the later phases would otherwise inherit is corrected first (slice 0B):
tuple/event-view starvation (C1), the three Abyssal Mask defects with the untyped cross-participant
damage-modifier declaration that rides them (C2–C4), the divergent immobilize set (C5), and the
silent `Q2` drop on custom cast orders (C6). The open float arming priority is 0A's, not 0B's — it
moves no number.

## Decisions

**Gate hardening (0A) — no commit here may move a number.** Slices are numbered `0A.1`…`0A.10`; the
runbook cites them by number, so the numbering is part of the contract.

- **0A.1 — The corpus gate is fixed first and alone (D-94, D-100).** `tests/test_e9_corpus.py`
  asserts every non-legacy receipt on every run, with no selection standing between the corpus and
  the engine, and `scripts/repin_corpus.py --check` is the single writer of
  `data/practice-corpus/scenarios.json` (R-21). *Why: a selection that can empty out passes by
  asserting nothing, and one derived from repository history cannot be evaluated on the shallow
  checkout CI takes.*
- **0A.2 — Golden gains an instrument and a *second* baseline, never a widened first one (D-93).**
  `fingerprint`, `compare --report` and `capture-coupled [--exact]` are new subcommands and `metadata`
  takes its counts from the same function that prints them; `scripts/golden_coupled_baseline.json` is
  captured separately through the roster path, covering all six `damage_modifier` producers, both
  ledger shapes, and one Catalyst roster. **`cross_participant_authorities()` is created here, in
  0A.2, not at C2**: R-10 captures this baseline before 0B's first edit and `capture_coupled` reads
  the producer set from it (R-12), so at 0A the function is a derivation over the six
  `kind="damage_modifier"` construction sites — which needs no `Authority` declarations to exist —
  and C2 later fills its `Authority` values and adds the owner-iff-`SPLIT` check that reads them.
  The coupled scenario set additionally names the two **Syndra cast-order pin scenarios** —
  `syndra_custom_order` (requested `["Q","W","E","R"]`) and `syndra_derived_order` (no `cast_order`),
  sharing one parameter set (L18, Q5/W5/E5/R3, 600 AP, 10 ability haste, 12 s deterministic, target
  10000 HP with zero armour and zero MR) captured at splinters ∈ {39, 60, 120} — because the splinter
  count is load-bearing and a pin without that axis is ambiguous. **The scenario definition is the one
  home of the parameter set and the committed baseline entries are the binding home of the totals**:
  criterion 14 and Phase 5's criteria 6 and 11 run these scenarios by name and read the baseline,
  retyping nothing, which retires the bespoke shared-fixture module an earlier draft created at B0.5
  and value-filled at C6 — a second hand-maintained pinning mechanism beside golden. It also makes
  C6's qualifying population non-empty by construction.
  **`fingerprint` counts the numeric sections only** — its
  domain is the runbook's, and excluding `metadata` is not an optimization but the fix: two of its
  keys are wall-clock floats that move on every capture. *Why: the receipt figure and every consumer's
  figure must be one number by construction — the campaign carried a hand-written scenario-entry figure
  that reproduces under no definition, and this document does not restate it (umbrella criterion 4) —
  and `golden_snapshot.py` calls only `pipeline.run_fight`, so
  it is blind to every defect 0B fixes.*
- **0A.3 — Bench counters ride the search context; monkey-patching is banned.** One `WorkCounters`
  threaded through the optimizer, plus `--isolate`, `--no-compiled`, `allocation_probe` and a fourth
  scenario (`syndra_mandate_3champ`) whose main authors a `cc_kind`. *Why: three of the four
  fingerprint families the campaign gates on have no producing tool today; R-01 rows 8, 11 and 13 have
  no command without them; and no existing scenario authors an immobilize, so the instrument cannot
  see the headline correction.*
- **0A.4 — `TransitionRank` is an ordinal `IntEnum`; `legacy_phase` is its float projection (D-05,
  D-06).** `legacy_phase(rank) -> float` returns today's float and stays what every sort key consumes
  until Phase 4 deletes it; it is deliberately many-to-one — **at 0A, eight producing rank names onto
  five distinct floats** (`LATE_BARRIER`/`REACTIVE` both 0.5; `DEBUFF_ARM`/`RECOVERY`/`UTILITY_ARM` all
  1.0), becoming nine names onto six once C4 adds `AURA_ARM −0.5` — and must be non-decreasing over
  declaration order. **The projection is total**: the producer-less `TERMINAL` member is declared last
  and projects to `math.inf`, so the monotonicity assertion covers every member with no exception and
  the one rank no producer emits still has a defined float. **Every float-`phase` write consumes it in the same commit
  (D-68), and the surface is six sites, not two**: `program/compile.py:314` (the `phase` argument to
  `action_key`), `:608`, `:837` (element 2 of an inline sort tuple), `:944`, `:1001`
  (thorns), and `participant_timeline.py:2767` — the five compiler sites were spelled in
  `survival/compile.py` when 0A repointed them and moved with the one constructor at Phase 4 S4. *Why: today's phases include -0.5 and 0.5, which
  no `IntEnum` member can hold, and only a non-decreasing many-to-one projection keeps 0A's ordering
  byte-identical; split across commits — or applied to two of six sites — the compiled path silently
  desyncs from the walk and only the equivalence suite can see it.*
- **0A.5 — `_priority` as an open float is deleted in 0A**; its three producers
  (`item_support_effects.py:503`, `:1043`, `participant_timeline.py:3172`) name ranks instead, **and
  its one reader dies with them** — `participant_timeline.py:1948-1949` is
  `float(event.get("_priority", 0.0)) if "_priority" in event else …`, a silent default that would
  outlive the producers and quietly re-admit the hatch. *Why: an escape hatch letting any producer
  write any float makes a named ladder decorative — two shields ride 0.5, after damage, while the
  ladder gives shields -1.0.*
- **0A.6 — The published phase list is derived from the enum; the schema version bumps only when the
  published list changes (D-63).** 0A derives `PARTICIPANT_LEDGER_CONTRACT["phases"]` through a
  `public_phase` label per rank, reproducing today's six names byte-for-byte at
  `CAPABILITY_SCHEMA_VERSION == 1`; C4's `AURA_ARM` publishes a seventh phase and *that* commit bumps
  to 2 — the first two values of D-63's chain, whose two later bumps belong to Phase 3's 3.8 flip and
  Phase 4's S9 and are not this document's. One of the six published names —
  `death_or_terminal_cutoff` — is produced by no transition, so `TransitionRank` carries a producer-less
  `TERMINAL` member whose only job is to carry it: the ninth member at 0A and the tenth after C4's
  `AURA_ARM`, declared last so `legacy_phase`'s `math.inf` projection keeps the ladder monotonic; a
  test asserts no producer can emit `TERMINAL`. *Why: 0A is defined as behaviour-free, a bump with an
  unchanged payload teaches clients the version means nothing, and a derivation that silently drops a
  published name is the same failure one layer down.* Note the direction this creates: `capabilities.py`
  has zero intra-package imports today and gains its first, into `survival/actions.py`. It is acyclic —
  nothing under `survival/` imports `capabilities` — but it points the public-schema module at the
  kernel, which is the price of deriving the list rather than hand-listing it, and it is stated here
  rather than discovered at implementation.
- **0A.7 — `data_version()` is declared in `data_registry.py` (D-49).** A monotonic counter bumped by
  `write_runtime_cache`, with no reader in 0A. *Why: L4 and L6 are live at once and both need to key
  memos on it, so a counter either lane declares is a counter the other cannot use; `data_registry.py`
  is a zero-intra-package-import leaf and an unread counter moves no number, so 0A is the only
  conflict-free home — exactly D-05's argument for `TransitionRank`.*
- **0A.8 — Dead state and the dead entry point go in 0A (D-09, D-10):** `apply_transition`
  (`transitions.py:1588`, zero callers) with its two exports; `SurvivalAction.utility_kind`,
  `_UTILITY_KINDS`, the `state["utility_effects"]` write (`transitions.py:950`) and its initializer
  (`receipt_state.py:103`), all write-only; the unused `_has_catalyst` import. *Why: `utility_kind` is
  permanently `""` because `ActionKind` is not a `str` enum, and merging six later phases around dead
  code in the two modules they all rewrite costs more than deleting it once.*
- **0A.9 — The equivalence suite's required item set is derived, not hand-listed:** fixtures cover
  every member of the tuple-incapable set and every `damage_modifier` producer, with ally-holder rung
  variants. *Why: the current 13-item vocabulary (`tests/test_survival_kernel.py:113-130`) contains
  zero `damage_modifier` producers, and a hand list would re-create the very failure at issue.*
- **0A.10 — The plan documents are gated like source (R-37).** `scripts/plan_audit.py` plus
  `tests/test_plan_audit.py` and the committed `docs/receipts/decision-inventory.json`: every
  `file:line` citation in `docs/plans/*.md` is verified against its adjacent quoted fragment, both
  golden-figure prongs run here (value match on retired literals and live receipt counts; proximity
  markers for everything else), and the decision inventory is diff-gated against the umbrella's
  manifest. *Why: the campaign machine-checks every `src/` claim and exempted its own plans — which
  hold dozens of measured counts and citations verified once at `1274615` and rotting since; three of
  rev 2's own corrections were instances of that one gap, and one instrument closes the class instead
  of patching instances.*
- **Ratchet and receipts (D-47, D-99), landed across 0A.2 and 0A.3:** a per-file, non-decreasing
  pylint gate over every file a slice touches, recorded with the fingerprints in
  `docs/receipts/campaign-fingerprints.json`; and `ALLY_ITEM_EFFECTS` enters
  `scripts/patch_update.py`'s audit. *Why: CI's real gate is `--fail-under=9`, so an average that many
  small clean modules raise hides a degrading hotspot; and `ALLY_ITEM_EFFECTS` is hand-authored and
  refresh-**inert**, worse than stale on patch day.*

**Semantic corrections (0B) — one correction per commit, no exceptions.** The six commits are
labelled `C1`…`C6`; the runbook (R-30) and Phase 5 (P5-b, P5-c) cite them by label, so the labelling
is part of the contract. Expected qualifying occurrences (R-20) are stated per commit below.

- **C1 — One predicate answers the tuple question (D-01, D-02, D-03).** `pipeline.py:994` consults
  `has_event_view_support_items`; `has_event_scan_support_items` loses its only call site and is left
  with **zero callers** until Phase 2's P2c deletes the callable — the damage/takedown scan gating
  inside `derive_item_support_effects` is `names & CC_TRIGGER_ITEMS` / `& TAKEDOWN_SCAN_SUPPORT_ITEMS`
  / `& DAMAGE_TRIGGER_ITEMS` at `item_support_effects.py:300-304` and never calls the helper. Reject
  the union variant (verified: drops Echoes of Helia) and the widened-tuple variant (leaves
  `_event_id`, both scans, and the crash). Solstice Sleigh is tuple-incapable and enters by
  derivation, not by a test pinning its `healthRegen` coincidence; Fimbulwinter stays because
  `_event_id` exists only on enriched rows and dropping it disarms the fail-closed
  `support_trigger_link` raise at `program/compile.py:914`. *Why: smallest diff, no schema change — the fix is to make two gates name one predicate.*
  **Expected qualifying occurrences: 0 on the three legacy bench scenarios, unbounded-but-enumerated
  on `syndra_mandate_3champ`, which is the only one authoring a `cc_kind`.**
- **Starvation raises at one site, not per scanner, and the public path never reaches it:**
  `derive_item_support_effects` raises when **handed `damage_events_tuple` rows directly** for a
  declared event-view holder, naming item and stream. After C1 no public request can produce that
  input — every tuple-incapable holder gets dict rows — so the raise is a programming-error tripwire,
  not a user-facing outcome, and Phase 2 proves its unreachability rather than contradicting it.
  *Why: Echoes of Helia's missing guard (`item_support_effects.py:797-804`) is a latent
  `AttributeError`, and a projection that cannot answer is a programming error — Phase 2 re-types this
  one raise as `ProjectionStarvation` (D-25), so Phase 0 must not invent that vocabulary.*
- **C2 — `Authority` keys the cross-participant machine check; `all_sources` does not (D-07).** Every
  `damage_modifier` packet declares one of the five `Authority` members, and `owner` is present
  **iff** `SPLIT`. The check lives in `_packet`, the one construction site for all six producers. The
  full five-member enum is declared in 0A in `ability_spec.py` beside `DamageClass`/`AttackClass`,
  because 0B itself declares `PAIR_ONLY` (Horizon Focus) and `COUPLED_AUTHORITATIVE` (Force of Nature
  — the umbrella's re-ruled Steadfast row — and Bloodsong) mechanics, and `trigger_stream.py` — the umbrella's eventual re-export home — does not
  exist until Phase 2. *Why: keying on `all_sources=True` passes Dream Maker, Black Cleaver and
  Bloodletter's Curse by construction — three of the six never set it.*
- **Dream Maker is `COUPLED_ONLY` and declares no `owner`, settled — not "verify at
  implementation".** Verified: no pair-engine pricer for Blue Dream Bubble exists in `src/`, and
  `item_coverage.py:175` already records "Dream Maker affects an ally, not the item holder's TDD." It
  rides C2. *Why: `SPLIT` would demand an owner skip for a half that does not exist, and C2's
  owner-iff-`SPLIT` check would reject the declaration on the same commit that made it.*
- **Abyssal Mask is three commits, in order — C2, C3, C4:** `owner` first (the pair engine keeps
  `magic_amp`; the walk stops re-amping the holder to 1.12²), then the class restriction, then
  `AURA_ARM`. *Why: they partially cancel — C2 and C3 remove a spurious 1.12, C4 adds amp at t=0 — so
  batched, the net delta is unexplainable.* Because C2 and C4 both move the holder's `t = 0.0` magic
  leaves, their allowlists **overlap on exactly those leaves**, enumerated in advance in both (R-30);
  the criterion is that each commit's differing leaves are declared before the baseline is read, not
  that the three sets are disjoint. **Expected qualifying occurrences: declared as a qualifying
  population per R-20's second half** — for each of C2/C3/C4, the coupled-baseline leaves matching
  holder magic (C2), non-holder physical/true into a cursed enemy (C3) and `t = 0.0` (C4), enumerated
  from the committed `golden_coupled_baseline.json` **before the slice's first `src/` edit**, with the
  per-scenario size written into this line and into the commit body. A qualifying leaf outside the
  enumerated population stops the slice. *Why not a `≥ 1` floor: a lower bound makes no occurrence
  unexpected, so R-20's stop can never fire — on the three most numerically active corrections in the
  campaign.*
- **C3 — `damage_classes: frozenset[DamageClass]` and `attack_classes: frozenset[AttackClass]`, both
  required, no default, empty banned (D-04).** The vocabulary lives in `ability_spec.py` beside
  `CC_KIND_VOCABULARY` (declared in 0A, consumed here), `_PART_DAMAGE_TYPES` becomes a projection of
  `DamageClass`, and both untyped branches consume them — `transitions.py:1263` (reduction) and
  `:1276` (multiplier). Abyssal declares `{MAGIC}` × all attack classes (Wiki: *"from all sources"*).
  *Why: empty-means-all is a silent default in a campaign whose thesis is that silent defaults kill,
  and the reduction branch is as untyped as the multiplier one.* Note the import consequence, because
  a later phase asserts on it: `survival/actions.py` has **zero** intra-package imports today and this
  gives it its first, to `ability_spec` — a stdlib leaf, so no cycle, but the "no new import edge into
  `survival/`" reading is wrong and Phase 2's "first intra-package import" is its second.
- **`is_attack_or_spell` versus "from all sources" is characterized, not fixed here.** Abyssal's
  widening is expressed through `attack_classes`; if the walk's gate still makes the halves
  non-disjoint, the divergence ships behind a sentinel. *Why: silently widening a gate inside a commit
  labelled "add a typed field" is a second correction riding the first.*
- **C5 — Force of Nature consumes the shared predicate (D-08):** the 5-member literal at
  `survival/actions.py:501-502` becomes `ability_spec.IMMOBILIZING_CC_KINDS` (15 members), pinned by a
  source assertion. *Why: "one predicate, one home"; Force of Nature is in
  `COMPILED_WALK_UNREPRESENTABLE_ITEMS`, so the blast radius is receipt-walk numbers only.*
  **Expected qualifying occurrences: 0 on both baselines (no bench or golden scenario holds FoN with
  a non-slow immobilize); every effect is shown by fixture.**
- **C6 — Custom `cast_order` stops deleting recast slots (D-11).** The shape check stays
  champion-agnostic in `_validate_request_values`; the permutation check moves to
  `FightParams.validate_for_champion` against `cast_dependency.orderable_slots(...)`; expansion calls
  `cast_dependency.expand_user_order`, which reinserts each live recast slot immediately after its
  parent. **Both functions are imported from the leaf Phase 5 merged at B0.5** — C6 declares neither.
  **The literal existed twice** — once in `pipeline.py`'s `_validate_request_values` and once in
  `scenario.py`'s loadout parser, the same test on the roster/coupled request path, which
  `golden_coupled_baseline.json` covers. Both go, or a Syndra order containing `Q2` is still rejected
  on the path the campaign's own new baseline exercises. *(Both spellings are deleted by C6, so this
  bullet deliberately carries no `file:line` citation to them; `tests/test_custom_cast_order.py`
  source-asserts both absences instead.)* *Why: a public parameter silently dropping a
  whole damage row is a correction, and `capabilities.py` already marks `cast_order` `supported=False`,
  so no user surface regresses.*
  **Expected qualifying occurrences: 0 on pair-engine golden; on the coupled baseline, declared by
  measurement before the mutation (R-20).** Pair-engine golden is structurally 0 —
  `golden_snapshot.py` builds every `FightParams` with `cast_order=None`, so no snapshot row can gain a
  recast slot. The coupled count is not knowable by inspection, because C6's whole effect is to add rows
  that do not exist in the pre-change tree, so C6 declares its **qualifying population** first: the
  scenarios in the committed `golden_coupled_baseline.json` that request a custom `cast_order` for a
  champion holding a `recast_of`-stamped slot, enumerated from that file **before the slice's first
  `src/` edit** and written into this line and the commit body with its per-scenario breakdown. A
  qualifying leaf outside that enumerated set stops the slice and is investigated.
- **`recast_of` on the parsed ability entry is the single authority for recast parentage, and a kit
  slot that is neither orderable nor a declared recast is a hard error.** Syndra's `Q2` gains the stamp
  in C6 — verified missing today, while Ambessa (`ambessa.py:226`) and Camille (`camille.py:128`)
  carry it and `rotation_resolver.py:627-629` already derives its edge from it. **The name-based
  fallback at `rotation_resolver.py:630-631`** — `if "Q" in corpora and "Q2" in corpora: add("Q","Q2",
  "recast", …)`, which fires for any champion holding both slots — goes with it, or the next unstamped
  recast slot is masked and the fail-closed half never fires. *Why: the synthesis named a
  `RECAST_PARENT_SLOT` authority that does not exist, and hand-tabling a fact `recast_of` already owns
  is the failure this campaign kills. `champions/syndra.py` is L6's; L1 owns **the stamp alone** for
  this one commit under the runbook's symbol-scoped carve-out, and `rotation_resolver.py:630-631` is
  L6's to delete in the same barrier window.*
- **Deferred semantics ship as sentinels, zero `src/` change, each naming its decision id in its
  failure message (D-12, D-13, H3):** no two overlapping Command windows across the registered sweep;
  the `start < t <= end` expiry divergence (`damage.py:9313-9323` versus the walk); `is_attack_or_spell`
  versus "from all sources"; first-defender attachment; Abyssal range and death conditions;
  `support_value` unit mixing. *Why: a correction with no reachable fixture is a declaration wearing a
  correction's clothes — a sentinel turns the precondition into a gate, so Phase 3's `merge=EXTEND` is
  provably zero-diff and the next person to add a champion reads a campaign message.*
- **Nothing is re-baselined inside Phase 0 (D-97, D-98).** Each correction lands against the committed
  baselines plus an allowlist of expected coupled-golden leaf paths with oracle receipts; the
  tuple-gate flip is one symbol; re-capture happens once, at the phase boundary. *Why: reverting one
  correction must never require reverting a multi-megabyte blob.*
- **Commit order is part of the contract:** 0A entirely precedes 0B; 0A.1 precedes everything; within
  0B, C1 precedes C2/C3/C4; and C6 waits on B0.5. *Why: the tuple-gate change decides which ledger
  shape the Abyssal fixtures run under, so landing it later would silently re-interpret their expected
  values; and C6 imports two functions Phase 5 owns.*

Anything not ruled here inherits the umbrella's decision table and the runbook. Phase 0 makes no
registry moves, introduces no module boundaries, and re-opens no `[H]` decision.

## Shape

| File | Responsibility in this phase |
|---|---|
| `scripts/repin_corpus.py` *(new)* | The corpus's staleness anchor and its one writer |
| `scripts/golden_snapshot.py` + `golden_coupled_baseline.json` *(new)* | `fingerprint`, `compare --report`, `capture-coupled`, and the roster-path baseline golden cannot be |
| `scripts/bench_coupled_optimizer.py` | Counters, residual, rung histogram, isolation, cc scenario |
| `scripts/pylint_ratchet.py` *(new)*, `scripts/patch_update.py` | Per-file score gate; `ALLY_ITEM_EFFECTS` enters the audit |
| `docs/receipts/campaign-fingerprints.json` *(new)* | Pinned pre-change instrument readings |
| `src/calculator/ability_spec.py` | `DamageClass`, `AttackClass`, `Disposition`, `Authority` — the campaign's four closed vocabularies, in the one dependency-free leaf. Declared in 0A, consumed in 0B and after |
| `src/calculator/item_support_effects.py` | Packet validation against `Authority`, the starvation raise, `cross_participant_authorities()` |
| `src/calculator/pipeline.py` | Tuple gate predicate; cast-order validation split, expansion call site |
| `src/calculator/scenario.py` | The roster path's copy of the same cast-order permutation literal |
| `src/calculator/data_registry.py` | `data_version()` — the monotonic counter, no reader in 0A |
| `src/calculator/work_counters.py` *(new)* | `Rung`, `WorkCounterSink`, `record_rung` — the counter vocabulary 0A.3's harness sink satisfies. It declares what a sink looks like and which rung priced an evaluation; nothing in it counts anything |
| `src/calculator/optimizer.py` | The sink threaded through `_PurchaseSearch` and `use_compiled_walk` threaded to the score path — the seam that makes R-24's "never a monkey-patch" implementable. Inert unheld: every counting site is one `is None` test and `use_compiled_walk` defaults to the compiled routing |
| `src/app.py` | `OPTIMIZER_INSTRUMENTATION` — the one request-path seam the bench installs its sink through, empty in production, so the counters CI reads come out of the shipped path rather than a patched copy of it |
| `src/calculator/survival/actions.py` | `TransitionRank`, class fields, shared immobilize predicate |
| `src/calculator/survival/transitions.py` | Class-gated modifier application; two deletions |
| `src/calculator/survival/{compile,receipt_state,__init__}.py` | Rank-consuming phases and sort keys; dead state |
| `src/calculator/participant_timeline.py` | Arming ladder consumes ranks; `_priority` producer and reader retired; the counted pair-fight wrapper and the rung histogram's three recording sites |
| `src/calculator/capabilities.py` | Phase list derived from the enum; version bump with `AURA_ARM` |
| `src/calculator/champions/syndra.py` | `Q2` stamps `recast_of="Q"` — this symbol only, at C6 |
| `scripts/plan_audit.py` *(new)* + `docs/receipts/decision-inventory.json` *(new)* | The plan-document gate: citations, golden-figure prongs, decision inventory (R-37, 0A.10) |

Instrument signatures (`repin_corpus.py`, `golden_snapshot.py`, `bench_coupled_optimizer.py`,
`pylint_ratchet.py`) are the [runbook](silent-failure-runbook.md)'s Shape block and are **not** repeated
here; Phase 0 builds exactly what that block declares. Only `src/calculator/` signatures follow.

```python
# src/calculator/ability_spec.py — closed vocabularies, dependency-free leaf, all declared in 0A
class DamageClass(Enum): ...        # MAGIC | PHYSICAL | TRUE
class AttackClass(Enum): ...        # BASIC_ATTACK | ABILITY | OTHER
class Disposition(Enum): ...        # MEASURED | STRUCTURAL_ZERO | WITHHELD | STARVED
class Authority(Enum): ...          # PAIR_ONLY | SPLIT | COUPLED_AUTHORITATIVE
                                    # | COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW | COUPLED_ONLY
def part_damage_types() -> frozenset[str]:
    """The string projection of DamageClass, replacing the _PART_DAMAGE_TYPES literal."""

# src/calculator/item_support_effects.py — packets declare who prices what
def _packet(*, attacker, target, time, kind, source, amount: float = 0.0,
            duration: float = 0.0, target_scope: str = "one_teammate",
            **fields) -> dict[str, Any]:
    """Unchanged call shape, keyword names included; a damage_modifier packet missing
    Authority or classes now raises beside the existing finite/non-negative checks."""
def require_event_view(result: Mapping[str, Any], names: Collection[str]) -> None:
    """Raise, naming item and stream, when a declared event-view holder is handed tuple rows."""
def cross_participant_authorities() -> Mapping[str, Authority]:
    """The source of truth the owner-iff-SPLIT check reads, and the producer set
    capture_coupled reads until P2a repoints it at CAPABILITIES (R-12).  One row per
    producer.  Created in 0A.2 as the producer-set derivation over the six
    kind="damage_modifier" construction sites (no Authority declarations needed);
    C2 fills the Authority values.  Retired by Phase 2's P2c."""

# src/calculator/survival/actions.py — one ordered transition vocabulary
class TransitionRank(IntEnum):
    """Dense ordinals in ordering order; the only phase vocabulary after 0A.  Carries a
    producer-less TERMINAL member so the published list keeps death_or_terminal_cutoff."""
def legacy_phase(rank: TransitionRank) -> float:
    """Today's float for one rank — many-to-one, total, non-decreasing over declaration
    order; TERMINAL is declared last and projects to math.inf.  Deleted in Phase 4."""
def public_phase(rank: TransitionRank) -> str:
    """The published phase name a rank belongs to; capabilities derives its list from this."""
class SurvivalAction(NamedTuple):
    """Gains rank, damage_classes, attack_classes; loses utility_kind."""
def survival_action_from_event(event, phase, subject_index, index_of, *,
                               subject_id="", aidx=-1) -> SurvivalAction:
    """Unchanged signature; additionally resolves rank and classes.  The _priority read is
    the caller's — participant_timeline.py:1948-1949 — and dies there, not here."""

# src/calculator/survival/transitions.py — one predicate decides applicability
def _modifier_applies(modifier: Mapping[str, Any], action: SurvivalAction) -> bool:
    """Owner skip plus damage/attack class match — consulted by both modifier branches."""

# src/calculator/capabilities.py
def _ledger_phases() -> list[str]:
    """PARTICIPANT_LEDGER_CONTRACT['phases'], derived from TransitionRank via public_phase."""

# src/calculator/data_registry.py
def data_version() -> int:
    """Monotonic, bumped by write_runtime_cache; the one thing every derived memo keys on."""

# src/calculator/work_counters.py — what the optimizer needs of a counter sink.
# The concrete sink is the runbook Shape block's WorkCounters dataclass, which lives in
# the harness; this module declares only the shape it satisfies, so src/ never imports
# scripts/ and an uninstrumented request pays one "is None" test per site (R-24).
class Rung(StrEnum): ...            # COMPILED | RECEIPT_WALK_GATE
                                    # | RECEIPT_WALK_CANDIDATE | SEARCH_POISONED
class WorkCounterSink(Protocol):
    """Three mutable counters plus a rung histogram; no methods, because a sink is data.
    public_evaluations is deliberately absent: the optimizer's own response publishes it,
    so no counting site in src/ can disagree with the figure the harness reads."""
def record_rung(sink: WorkCounterSink | None, rung: Rung) -> None:
    """Attribute one coupled evaluation to the engine that priced it, or do nothing."""

# src/calculator/pipeline.py — a custom order may no longer lose a slot.
# orderable_slots and expand_user_order are IMPORTED from cast_dependency (Phase 5's leaf,
# merged at B0.5).  Phase 0 declares neither; it deletes both permutation literals and calls them.
```

## Success criteria

Each is separately falsifiable and separately revertible; the eleven shared gates are R-01 in the
[runbook](silent-failure-runbook.md) and are not restated.

1. `scripts/repin_corpus.py --check` passes on a commit that changes only a comment in `src/`, and
   `tests/test_e9_corpus.py` is green on it without re-probing. Writer and both readers resolve the
   anchor through one `anchor_src_sha` call, source-asserted.
2. `golden_snapshot.py fingerprint` reproduces the counts recorded in
   `docs/receipts/campaign-fingerprints.json`; a test asserts the snapshot's `metadata` carries the
   same values from the same function, that `fingerprint`'s excluded key set equals
   `COMPARE_EXCLUDED_PROVENANCE`, and that no `docs/plans/*.md` file states a golden leaf or entry
   count — under R-37's `plan_audit.py` (retired literals pinned in the instrument, live counts read
   from the receipt, standalone-integer match plus the proximity-marker prong, with a committed
   collision allowlist), never an invented regex.
3. `scripts/golden_coupled_baseline.json` shows at least one differing leaf for each of the six
   `damage_modifier` producers when that producer's packet is suppressed, and `compare` is clean at
   the Phase 0 tip.
4. `bench --fixed-work --isolate --json` emits all four counter families, the residual, a four-state
   rung histogram, wall and `allocation_probe` for four scenarios, one of whose mains authors a
   `cc_kind`; `--no-compiled` runs from the same entry point. The measured residual is **recorded
   beside** the 87/28/34 prior with a one-line divergence cause and is **not asserted equal** to it —
   R-07 forbids gating an instrument on the value it exists to measure. `--isolate` is the mode the
   committed fingerprints used.
5. `TransitionRank` is the only phase vocabulary: no float `phase` or `_priority` literal survives
   outside `legacy_phase` — the six migrated sites are `program/compile.py:314, :608, :837, :944,
   :1001` and `participant_timeline.py:2767`, the first five having moved out of
   `survival/compile.py` with the one constructor at Phase 4 S4 — the string `"_priority"` has zero occurrences in
   `src/`, and a test asserts `legacy_phase` is total over the enum and non-decreasing over declaration
   order with **no member exempted**, `TERMINAL` included: it is declared last and returns `math.inf`,
   so a member added without a float, or added out of order, fails rather than falling through a
   carve-out.
6. `PARTICIPANT_LEDGER_CONTRACT["phases"]` is computed from `TransitionRank` through `public_phase`,
   equalling today's six names byte-for-byte at `CAPABILITY_SCHEMA_VERSION == 1` before C4 and seven
   at version 2 after it, with `tests/test_capabilities.py` pinning both sides and one test asserting
   no producer emits `TERMINAL`.
7. Compiled-vs-receipt fixtures exist for every member of the tuple-incapable set
   (`EVENT_VIEW_SUPPORT_ITEMS` at Phase 0; `trigger_stream.tuple_incapable_items()` after Phase 2,
   which re-points this criterion in P2c) and every `damage_modifier` producer plus ally-holder rung
   variants, with the required set computed from the registries, so a new producer without a fixture
   fails the suite.
8. A score-only fight for an Imperial Mandate, Bandlepipes, Fimbulwinter, Solstice Sleigh **or Echoes
   of Helia** holder delivers its packets through the public path — none of them starves, which is
   what C1 buys. `derive_item_support_effects` **handed `damage_events_tuple` rows directly**, bypassing
   the gate, raises a named starvation error instead of `AttributeError`. Solstice Sleigh's protection
   is asserted to come from the derived event-view set and *not* from `_has_item_health_regen`; a
   source assertion forbids `has_event_scan_support_items` in `pipeline.py`'s tuple gate; and after C1
   the callable has zero callers in `src/`, which Phase 2's P2c turns into a deletion.
9. Every `damage_modifier` packet carries an `Authority`, `owner` is present iff `Authority ==
   SPLIT`, and the check reads `cross_participant_authorities()` rather than any flag — a producer
   setting `all_sources=False` and omitting `owner` under `SPLIT` still fails.
10. Dream Maker declares `COUPLED_ONLY` with no `owner`, and a test asserts no pair-engine pricer for
    Blue Dream Bubble exists, so the declaration cannot silently become wrong.
11. Abyssal Mask lands as three commits — C2, C3, C4 — each **declaring its differing leaves in an
    allowlist before the baseline is read**, with an oracle receipt per qualifying leaf: holder magic
    falls from ×1.2544 to ×1.12; a non-holder's physical and true damage into a cursed enemy loses its
    12%; damage at exactly `t = 0.0` gains it. C2's and C4's allowlists **overlap on the holder's
    `t = 0.0` magic leaves** and the overlap is enumerated in both — the three sets are not disjoint
    and were never going to be, because R-30 says these corrections partially cancel. Pair-engine
    golden shows zero diffs in all three.
12. A packet or `SurvivalAction` built with absent or empty `damage_classes`/`attack_classes` raises,
    and both the reduction and multiplier branches consult one predicate.
13. All fifteen `IMMOBILIZING_CC_KINDS` grant Force of Nature's stacks, a slow still grants one, and
    a source assertion forbids a second immobilize literal in `survival/`.
14. **C6 is pinned by a timeline, not a scalar.** Syndra at level 18, ranks Q5/W5/E5/R3, 600 AP, 10 AH,
    12 s deterministic, target 10000 HP with zero armour and zero MR, splinters at the module default
    (120), requested as `["Q","W","E","R"]`, yields `breakdown["Q2"]["casts"] == 1` and a cast timeline
    read off the **public `cast_timeline` list** (`public_response.py:249`) as
    `[(c["time"], c["slot"]) for c in result["cast_timeline"]]`, which measures
    `[(0.0,"Q"),(0.0,"W"),(0.0,"E"),(0.25,"R"),(5.0,"Q"),(7.273,"W"),(10.0,"Q")]` before the fix — the
    scalar beside it is the 0A capture's, not a figure this document owns — and must gain `(0.0,"Q2")`
    after it. *No breakdown row carries a
    `cast_times` field: `breakdown["W"]` holds `casts`, `damage_by_type`, `damage_type`, `name`,
    `total_damage`, `total_raw`, and C6 adds no payload field, so a `cast_times` assertion would be
    undischargeable.* **The timeline
    is asserted to differ from Phase 5 c6's derived timeline**; if the two are identical the pin
    scenario uses a requested order for which they are not, because a criterion that both the fix and a
    fall-through to the derived order satisfy is not a criterion. The parameter set lives once, in the
    **`syndra_custom_order` scenario definition of 0A.2's coupled scenario set**, and the scalar
    total's binding copy is that scenario's committed `golden_coupled_baseline.json` entry — this suite
    and Phase 5's criterion 11 run the named scenario and read the baseline, retyping nothing. The
    figures quoted above are the measured pre-fix values the 0A capture pins; C6's declared diff (the
    `Q2` rows and the totals they move) is enumerated in its allowlist and re-captured into the
    baseline at the phase boundary under the standard allowlist-and-receipt machinery (R-17). There is
    no bespoke Syndra pin fixture: an earlier draft created one at B0.5 and value-filled it at C6 —
    a second hand-maintained pinning mechanism beside golden, retired by 0A.2's scenario rule.
    A kit slot that is neither orderable nor a declared recast raises rather than being dropped;
    Syndra's `Q2` carries `recast_of="Q"`; and the same request through the roster path
    (`scenario.py`) is accepted, not rejected. **C6's qualifying population is enumerated from the
    committed `golden_coupled_baseline.json` before the slice's first `src/` edit and pinned in its
    `Expected qualifying occurrences` line and commit body** (R-20); pair-engine golden's 0 is asserted
    from `golden_snapshot.py` passing `cast_order=None`, not assumed; and a coupled leaf qualifying
    outside the enumerated population fails the slice rather than being absorbed.
15. Six sentinels are present, green, and each names its decision id in its failure message; **each
    also asserts its own population size against a pinned non-zero number** (D-26) — the
    Command-overlap sentinel covers the whole registered-champion sweep, whose Mandate-plus-authored-
    `cc_kind` population must be non-empty or the sentinel is green over nothing and Phase 3 inherits
    an assumption wearing a gate's clothes.
16. The deletion frontier is exactly: `apply_transition` and its two exports; `utility_kind`,
    `_UTILITY_KINDS`, `state["utility_effects"]`; the `_has_catalyst` import; `_priority` as an open
    float — **its three producers migrated and its reader at `participant_timeline.py:1948-1949`
    removed**, with `"_priority"` asserted to have zero occurrences in `src/`; **both**
    `sorted(cast_order) != ["E","Q","R","W"]` literals (`pipeline.py:693`, `scenario.py:264`); the
    name-based Q→Q2 recast fallback at `rotation_resolver.py:630-631`; and
    `has_event_scan_support_items` as the tuple gate's predicate — the callable survives with zero
    callers until Phase 2's P2c deletes it, and this document does not claim it survives *for*
    anything. Each absence is source-asserted, one dispatch ladder remains in `survival/`, the
    deletion commits show zero diffs on both baselines, and nothing else in `src/` is removed here.
17. Neither baseline is re-captured inside a correction commit; the single re-capture at the phase
    boundary carries a receipt per qualifying leaf under the runbook's investigator rule, and
    `docs/receipts/campaign-fingerprints.json` holds the pre-change golden and coupled fingerprints,
    the four-scenario bench JSON, the pytest `{collected, skipped, xfailed}` triple,
    `corpus.non_legacy_count`, and per-file pylint scores for every file Phase 0 touched.
18. **One roster fixture makes Command's deletion fail on a number.** A Mandate holder plus an ally
    plus an authored stun, whose expected total differs from the same roster's no-Command total, so
    deleting `_apply_command_amp` or dropping the coupled pricer turns the suite red on an arithmetic
    assertion — not only on an evidence member in Phase 1 or a source assertion in Phase 2. This is
    the number-level half of the umbrella's success criterion 2 and it is Phase 0's, because Phase 0
    is where the fixture becomes reachable.
