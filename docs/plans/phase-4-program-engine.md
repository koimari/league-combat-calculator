# Phase 4 — Immutable Programs and One Walk

Part of the [Silent-Failure Campaign](./2026-08-08-silent-failure-campaign.md); every gate command, counter
baseline, golden protocol and agent lane is defined once in the [Campaign Runbook](./silent-failure-runbook.md).
Prerequisites: [Phase 0](./phase-0-gates-and-corrections.md), [Phase 2](./phase-2-trigger-bus.md) and
[Phase 3](./phase-3-behavior-rules.md) complete. Decisions owned: **D-60…D-72**, D-38's remaining **nine**
adequacy clauses, D-68's `legacy_phase` deletion, **every `CAPABILITY_SCHEMA_VERSION` bump after Phase 3's
3.8 flip** (D-63's chain: 0A lands 1, C4 takes 2, 3.8 takes 3, S9 takes 4), and D-101's compiled-lane criterion
(Phase 3 owns the ruling). Carve and Vile Decay are blocked on **H1**, Command on **H2**, and the
compiled-amp lane is shaped by **H5** — all three rulings are recorded in the umbrella's `[H]` table, not
here; this document reads them.

## Goal

One coupled simulation: immutable logical `PairEvent`/`RoutedEvent` programs compile through a single
constructor into the existing `SurvivalAction`/`ScoreLedger` kernel, one walk per pass produces one outcome
ledger, and score, breakdown, survival, TDD and receipt are five projections of it that re-run no arithmetic.

## Decisions

### Layering and identity

- **`program/` is the logical layer, `survival/` stays the kernel, and the dependency is one-way
  `program → survival`.** *`program/` answers "what happened and to whom", `survival/` answers "what that does
  to state" — and the hot loop must never dispatch on a logical type.*
- **References are two-layer**: the four logical references — `SurvivalAction.trigger_event_id`,
  `deferred_batch_id`, `event_id`, `defy_trigger_id`, the kernel's only `str | None` fields — become
  `EventId`, compiled references are the action's integer slot, and `event_id_text` runs once, in the receipt
  view. Redirect linkage is not among them: it lives on the context (`transitions.py:216 redirect_children`),
  not on the action. *Keeps program types out of the kernel tuple, deletes four `str | None` fields and every
  string compare from the walk, and keeps public ids byte-identical. Supersedes "EventId everywhere".*
- **`EventId = (Origin, ordinal)`, `Origin` a closed four-member union**; fan-out is
  `DerivedOrigin(parent, role)`, never a string suffix; `PairEvent.sequence` is required. *Identity is
  positional string concatenation today, so numbering is order-derived; `_pair_packet`'s raise becomes a type
  invariant.*
- **The payload union is closed — 11 families, 5 riders — and an undeterminable family raises
  `UnclassifiedEvent(origin, source, fields_present)`**; no `Any` payload, no `**kwargs`, no callable field.
  *The campaign's one invariant: an uncomputed number must never look like a computed zero.*
- **`Provenance` is an authoring invariant, not a runtime record.** Its construction rules
  (`priced_by == PAIR_ENGINE ⟹ applies_to == ALL_EXCEPT_HOLDER`; `damage_classes`/`attack_classes` required,
  no default) make Abyssal's missing-owner and untyped-amp defects unconstructible; it compiles to flat
  fields on `SurvivalAction` — the class fields 0B added, and **`holder: int`, which this phase introduces
  at S1**, the stage that turns every kernel reference into an integer slot, in the same commit that deletes
  the legacy `owner: str`. The kernel field is a plain `int`; `PIdx` is the `program/`-side narrowing of the
  same roster index and stays out of `survival/`, or the annotation alone would invert this phase's one-way
  dependency. *An invariant belongs where it can be violated — at authoring — not in the hot tuple; and the
  holder field is named here because nothing before this phase creates it: `owner: str` is what 0B's owner
  skip reads, and it is on this phase's deletion frontier.*
- **A live predicate compiles to a value-typed `LiveAmp` field the kernel evaluates by tag.** *The only way
  Shadowflame reads live pools inside the walk without `survival/` importing `program/`.*

### Ordering and outcomes

- **`TransitionRank` is consumed as landed in Phase 0A/0B, never re-introduced.** Every float-`phase` write
  already consumes it — 0A repointed all six sites under D-68 — so Phase 4's only ordering deletion is
  `legacy_phase` itself, and the one ordering *change* is S6's split of `DEBUFF_ARM`/`RECOVERY`/`UTILITY_ARM`.
  *0A already made the enum the one phase vocabulary (D-05/D-06); re-introducing it would rewrite a landed
  commit, and deleting the projection while the compiler still consumed a collapsed float would make S2 a
  semantic stage wearing a pure one's label.*
- **The sort key stays eight elements in D-67's exact order** — verified `len(action_key(...)) == 8`.
  *`participant_order` contributes two components; any `PIdx`-ification that collapses them silently reorders
  simultaneous events, which is why the shape is pinned rather than the concept.*
- **`OutcomeLedger` is a third kernel-side ledger (`survival/outcome_state.py`), not a program type**, with
  write-once fields and `AdjustmentReason.HOLDER_HEALTH_GATE` (Knight's Vow) as the only way a later transition
  revises an earlier one. *Layering — and the one live case is a kernel gate, so a second reason must be argued.*
- **The receipt projects at end-of-walk**; `records_annotations`/`records_event_fields` become verbosity flags
  on one ledger, hot-path skips intact. *Input and output share a channel today, which is why the two adapters
  are structurally different rather than merely differently-observing.*

### View semantics

- **`ViewTag` has exactly two members, `THEORETICAL` and `APPLIED`; "requested" is not a tag.** The ladder is
  requested → priced → applied: requested is a program node carrying no number, priced is the pair engine's
  pre-coupling authoring, applied is what the coupled walk delivered. *Tagging a non-number would re-open the
  zero-versus-absent confusion this campaign exists to close.*
- **A sum may never mix views, and `THEORETICAL` is never an optimizer objective and never feeds BIS** —
  enforced by construction in the view layer, not by review. Two further rules close the double-count that
  "no mixed sums" leaves open: **`view_tags` declares exactly one `ViewTag` per `(mechanic, EngineLane)`**,
  and **for every `(mechanic, subject, event_id)` at most one `APPLIED` contribution exists across all
  producers** — a uniqueness test on the `OutcomeLedger`. For each
  `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` mechanic a roster fixture asserts the applied total equals the
  coupled contribution **alone**, and drops to zero-with-receipt — never to the preview — when the coupled
  interpreter is removed. *Why: forbidding a `THEORETICAL`+`APPLIED` sum does not forbid two `APPLIED`
  contributions for one mechanic on one subject, which is what keeping `_apply_command_amp` alive beside a
  new coupled pricer sets up.*
- **Dispositions are an algebra the views consume, not an annotation they maintain (D-72).**
  `Quantity` — `Measured(float) | StructuralZero(reason) | Withheld(receipts) | Starved(field,
  producer, reason)` — lands in `ability_spec.py` beside `Disposition` at S3, wrapping `OutcomeLedger`
  reads (pure: `Measured` wraps the same floats, and `Disposition` survives as the tag projection).
  Propagation is `Quantity.__add__`: any `Withheld` operand makes the sum `Withheld` naming its
  members, `StructuralZero` folds as 0.0, `Measured` folds only with `Measured`/`StructuralZero`, and
  a `Starved` quantity raises `ProjectionStarvation(field, producer, reason)` on first read,
  preserving D-25's single catch. The kernel is untouched — raw floats inside the walk, `Quantity`
  where leaves are born. *Why: without the type, the propagation row, the starved-read rule and the
  map/leaf agreement below are a shadow type system maintained by tests — annotation plus discipline
  emulating what one `__add__` gives structurally, at a permanently higher gate count.*
- **`disposition` and `ViewTag` serialize as one parallel `dispositions` map per payload, keyed by
  leaf path and produced only by `serialize_leaf` over `Quantity`.** A bare JSON number cannot carry a
  field, so S9's backward-compatible wire shape is a sibling block: each of the three payloads gains a
  `dispositions` map whose values are `{disposition, view_tag}`. `serialize_leaf` emits the leaf and
  its map entry in one call and is the only producer of either, so leaves and map cannot drift; the
  payload-schema test's two-way key-set equality (map keys = present numeric leaves ∪ withheld paths)
  is a backstop behind the single writer, not the mechanism. A `MEASURED` or `STRUCTURAL_ZERO` leaf
  stays a bare number, and `static/js/app.js` — which renders every stat card, score and breakdown
  from bare numeric leaves (architecture.md) — renders them unchanged, pinned by test. **A `WITHHELD`
  leaf is absent from the payload while its map entry remains, carrying the receipt** — the
  propagation row makes withheld *totals* reachable on `/api/calculate`, so this is ruled rather than
  discovered at implementation: `static/js/app.js` takes **exactly one budgeted change, at S9** — a
  shared withheld-marker rendering helper — so an absent-with-receipt leaf renders as a named refusal,
  never a blank, a zero or `NaN`. *Why ruled here: an unruled wire shape gets invented per endpoint at
  implementation, and the UI is the consumer no earlier draft budgeted.*
- **A view reads only `Program` and `WalkResult` and re-runs no arithmetic.** *Makes "score mode and receipt
  mode agree" structural instead of tested, which is what lets `_score_with_search_context`'s bespoke ~150-line
  assembly be deleted rather than mirrored.*
- **Five views, one per consumer shape**: `calculate.py:154` takes receipt+breakdown+survival+tdd,
  `optimizer.py:257` score, `bis.py:680` score+breakdown, `app.py` serializes the receipt — and the receipt view
  is the only producer of public event dicts.
- **`SumPlan` is a declared ordering over a *set* of `EventId`**, uniqueness asserted across the fresh, base and
  signature panels. *`accumulate_support_values` unions three sources with only a comment preventing a double
  count.*

### Routing and authority

- **Every event carries a `RoutePolicy`, `resolve_route` is total and fail-closed, and the 12 disclosure-only
  labels become `RouteAnnotation`s on a resolved route.** *They are not scopes; the live `TODO(issue #142)`
  says so.*
- **Command routes to `TriggerTarget`, the hardcoded first-defender scan is deleted, and `CcScope` is authored
  beside `cc_kind`, `Unreviewed` failing closed to `SingleTarget` on the pair defender plus a disclosure naming
  the ability.** *Today's `AllHitByThisCast(∞)` is an accident of running the rotation once per defender; H2.*
  **If H2 lands before S7, `CcScope` takes the sourced value and Command's authority moves in that same
  commit. If it does not, the umbrella's `[H]` table records H2 as *deferred, default shipped* and Command's
  capability row carries the `[H]` id** — the default is legitimate, but it ships as a recorded ruling, not as
  an unremarked fall-through.
- **Seven authority moves, one mechanic per commit:** Hypershot (canary, `PAIR_ONLY`, expected no-op) →
  Abyssal Unmake (declaration-only; its three corrections landed in 0B) → Bloodsong (retires the frozen
  `DivergenceReceipt`) → Command → Carve → Vile Decay → **Shadowflame last**. Carve and Vile Decay hold for
  H1, Command for H2; **the other four ship regardless**. *Each move has its own golden footprint and must be
  individually revertible.* These seven authority moves are **not** Phase 3's seven amp chain slots — the two
  sets overlap and neither contains the other, so neither document says "the seven amps" unqualified.
- **Carve and Vile Decay keep the Cesàro pair preview as `THEORETICAL`.** *`docs/math-foundations.md §2.3` calls
  re-tuning that approximation a balance change; dropping the preview inside an authority move makes it one by
  accident.*
- **Shadowflame is `LivePredicate(HealthBelowRatio)` — never a window, never a duration — and its bonus is an
  `AmpBonus` rider on its triggering `Damage` event, read before absorption.** *A rider dies with its host,
  which is the whole fix for a spell-shielded or post-death trigger still emitting a bonus.*
- **Arming dedupe is declared per mechanic, not assumed.** Every dual-sided mechanic declares
  `HolderStacking = IDEMPOTENT_AURA | PER_HOLDER` — the second of the two fields this phase writes on the
  shared `MechanicCapability`, `view_tags` being the other, both required with no default, the enum declared
  beside `Pairing` in `trigger_stream.py` so the registry keeps its single intra-package import; the
  arm-time key is `(subject, mechanic_id)` for `IDEMPOTENT_AURA` and `(subject, mechanic_id, holder)`
  otherwise, and a dropped duplicate emits a `dedupe` receipt row rather than vanishing. Abyssal is
  `IDEMPOTENT_AURA`; Command's value is H2-blocked and fails closed to `PER_HOLDER`. `arm_key` is the only
  arming dedupe in `src/`. *Two Abyssal holders arm two modifiers on one subject today — but a flat
  `(subject, mechanic_id)` key would silently drop a second Imperial Mandate holder's contribution, which is
  the incident's own shape mandated by a criterion. Cross-holder stacking is ruled nowhere else: D-12 rules
  only repeat-Command within one holder.*

### Representation, fallback and passes

- **The program is built before any representation choice**; `score_only` selects which fields the compiler
  reads, never which events exist. *The Mandate incident was an event that never reached the compiler, so
  fail-closed could not fire.*
- **Four rungs, and the two failure rungs mean different things.** A roster-held `ReceiptOnly` mechanic
  selects `RECEIPT_WALK` once, deterministically, at context setup — a representation choice with a named
  cause; `SearchPoisoned(reason)` is reserved for a genuine search-invariant *error*. *One ally's
  `damage_modifier` degrades the whole request today, and a three-rung histogram would read as uniform fallback
  with no cause.*
- **If H5 is descoped — the umbrella's `[H]` table records that ruling, this document does not write it —
  the compiled lane declares empty coverage for `damage_modifier`:** every amp holder is a receipted
  `RECEIPT_WALK`, and **no criterion in this phase asserts a compiled amp.**
  *`unrepresentable_template_receipt` rejects the kind categorically; asserting a compiled amp would be this
  campaign committing its own failure mode. If H5 is scoped, teaching the kernel timed, typed damage modifiers
  is its own stage after S7 with its own equivalence fixture — not a relaxation of these criteria.* Until the
  umbrella records a disposition, criterion 16's H5 clause is unresolvable and the phase does not exit.
- **Catalyst becomes `CrossPassDependency(max_passes=2)`:** the program is rebuilt per pass, the walk is never
  re-entered recursively, caches and search context stay live across passes, `IncompleteDependency` replaces the
  untyped `ValueError`, and its `Compilability` flips only on a pass-2-compiled-equals-pass-2-receipt proof.
- **Producer order is derived from the capability graph, not declared; Phase 4 writes exactly two fields on the
  shared `MechanicCapability`, and no third: `view_tags` and `holder_stacking`,** per the umbrella's field-
  ownership table, which is the single answer to who writes what there. *Three phases writing disjoint fields
  is what stops this campaign shipping three registries; a hand-declared producer tier would be a fourth
  writer, and deriving the order is what keeps that field from existing. `holder_stacking` is a per-mechanic
  fact and belongs on the shared declaration; `Provenance` carries per-event authoring facts and must not
  become a second home for it.*

### Caches, precision, migration

- **A cache key is a value derived from the object the cache serves, and the served value is immutable**; every
  cache declares `invalidated_by` including `data_version`, and `id()` survives only as a fast path in front of
  a value key.
- **Rounding is presentation**: one registry, `program/precision.py`, owns every `(field, digits)` pair, the
  logical program carries unrounded floats, and `CutoffPolicy.ROUNDED_DEATH_TIME` is a named policy.
  **Its gate is scoped to `program/`.** The kernel's measured 118 `round(` sites — `survival/transitions.py`
  72, `receipt_state.py` 38, `compile.py` 6, `accumulate.py` 1, `score_state.py` 1 — are frontier counter 6, a
  declared non-increasing count driven down by S3 moving receipt-field rounding into the end-of-walk
  projection. *Gating `survival/` at zero instead would force `survival/ → program/precision`, inverting this
  phase's own one-way dependency; and 72 of those sites write receipt fields inside the kernel, which is
  precisely what S3 exists to relocate. It is exactly the quirk a pure refactor loses silently.*
- **Strangler stages — the ordering is the design, not a schedule.** No stage mixes a pure refactor with a
  semantic correction; pure stages show zero diffs on both baselines and identical counters. **Each stage
  declares its own wall baseline** (`cassiopeia_5champ`, best-of-3, isolated), captured at the stage's first
  commit and written to `campaign-fingerprints.json` before its second — R-28's "the stage's declared
  baseline" is declared here or nowhere.

  | Stage | Kind | Content | Wall baseline |
  |---|---|---|---|
  | S1 | pure | `EventId`/`Origin`; logical references typed, kernel references become integer slots — including `owner: str` → `holder: int`, the field `Provenance` later compiles into | declared at S1c1 |
  | S2 | pure | delete `legacy_phase` — the two inline sort keys already consume `TransitionRank` (landed 0A) | declared at S2c1 |
  | S3 | pure | `OutcomeLedger`; end-of-walk projection; the rounding registry lands; receipt-field rounding leaves the kernel; `Quantity` lands beside `Disposition` (D-72) wrapping ledger reads — pure because `Measured` wraps the same floats | declared at S3c1 |
  | S4 | pure | `Program` + the one `compile_program`; both legacy `SurvivalAction` builders deleted | declared at S4c1 (+ `allocation_probe`) |
  | S5 | pure | projection satisfaction replaces all **ten** tuple clauses (derivation beside legacy, then flip) | declared at S5c1 |
  | S6 | semantic | `DEBUFF_ARM`/`RECOVERY`/`UTILITY_ARM` split — **payload-neutral: all three keep their existing `public_phase` label, asserted, so no schema bump**; if the split ever publishes a new phase name it takes D-63's next value, 4, and S9's becomes 5 | declared at S6c1 |
  | S7 | semantic ×7 | the seven authority moves, one commit each, in the order ruled above | declared at S7c1 |
  | S8 | enabling | `CrossPassDependency`; Catalyst de-recursed | declared at S8c1 |
  | S9 | pure | the five views; bespoke score assembly deleted; `disposition` and `ViewTag` published through the one `serialize_leaf`; `app.js`'s withheld-marker helper; `CAPABILITY_SCHEMA_VERSION` → **4**, one past Phase 3's 3.8 bump to 3 | declared at S9c1 |
  | S10 | cleanup | deletion frontier driven to target | declared at S10c1 |

- **Frontier counters 5–7 are this phase's**, committed with their exclusion lists to
  `docs/migration-frontier.json` and diff-gated by set equality (D-40, R-36): **5** `SurvivalAction`
  construction expressions outside `program/compile.py` (baseline 9, target 1 — the issue-#171 fast
  constructor at `survival/actions.py:601` is the declared survivor); **6** `round(` outside the precision
  registry (baseline 118 in `survival/`, 0 in `program/`, non-increasing); **7** `id()`-keyed caches whose key
  is not derived from the served value, over `src/calculator/{survival,program}` and `stats.py`, with the
  baseline **measured by the script on its first run** rather than typed — the naive count depends on whether
  an object-identity guard beside the value counts, and `champions/`'s two are out of scope and named on the
  frontier. *A frontier whose exclusions live inside the tool that measures it can be driven to zero by
  editing the exclusions.*
- **Deletion frontier owned here:** `legacy_phase`, `owner: str` (deleted at S1, replaced there by
  `holder: int` — no phase before this one creates that field), the four `str | None` reference fields,
  `survival_action_from_event`, `WalkCompiler`'s duplicated dict/tuple branches, `_packet_typed_actions` +
  `packet["_typed"]`, `pipeline.py`'s ten-clause tuple predicate, `_score_with_search_context`'s result
  assembly, and the first-defender scan. Phase 0A's deletions (`apply_transition`, `utility_kind`,
  `_has_catalyst`, `_priority`, every float `phase` literal) and Phase 2's five name sets are **not** Phase
  4's, and `COMPILED_WALK_UNREPRESENTABLE_ITEMS` is Phase 3's per-rule `Compilability` (D-43) that Phase 4
  only consumes.
- **`LATE_BARRIER` is a preserved defect, and it is named as one.** Two shields ride `0.5` — after damage —
  while the ladder gives shields `-1.0`; 0A preserved that byte-identically under the name `LATE_BARRIER`.
  S6 does not correct it. It is a committed `preserved_defect` row on the migration frontier with an issue
  ref, so a named defect on nobody's schedule is at least a counted one.

## Shape

New package `src/calculator/program/` — the logical layer:

| File | Responsibility |
|---|---|
| `identity.py` | `PIdx`, the `Origin` union, `EventId`, the one event-id string producer |
| `events.py` | the closed payload union, riders, `PairEvent`, `RoutedEvent`, `UnclassifiedEvent` |
| `route.py` | `RoutePolicy`, `RouteAnnotation`, total fail-closed subject resolution |
| `build.py` | engine results + support templates → `PairProgram` → `Program`, per pass |
| `amp.py` | `Provenance` and the coupled-lane interpreter for Phase 3's `delta_amp` declarations |
| `compile.py` | the **only** `SurvivalAction` constructor; program cache keys |
| `rung.py` | the four-state ladder and its histogram |
| `caches.py` | roster/actor/params fingerprints and every `invalidated_by` declaration |
| `precision.py` | the rounding registry, `SumPlan`, `CutoffPolicy` |
| `dependency.py` | `CrossPassDependency` and the pass driver |
| `walk.py` | `walk()` — the one kernel call site, returning `WalkResult` |
| `views/` | `score.py`, `breakdown.py`, `survival.py`, `tdd.py`, `receipt.py` |

New beside the kernel: `survival/outcome_state.py`. New gates: `scripts/migration_frontier.py`,
`docs/migration-frontier.json`, `tests/test_program_structure.py` (one-walk invariant, view purity, frontier
counters). **Each of the 17 new modules names its own test front door** — `tests/test_program_<module>.py`
for the **eleven** `program/*` modules the table above enumerates, `tests/test_program_views.py` for the five
`program/views/*` modules, `tests/test_outcome_state.py` for the kernel ledger — because Phase 1's
`FRONT_DOOR_FRONTIER` is set-equality gated and 17 undeclared modules would break it in the phase that added
them. (`program/__init__.py` and `program/views/__init__.py` are outside the count: criterion 18's
denominator is `src/calculator/**/*.py` **minus `__init__.py`**.) **The views' one
test file is a front door for all five only because it binds each submodule as a symbol** — `from
src.calculator.program.views import score, breakdown, survival, tdd, receipt` — which is exactly what
Phase 1's rule requires of a package import; `from src.calculator.program import views` imports the
package and would leave five modules undeclared behind one mention, the prose-covers-everything shape
this campaign kills. Phase 4 also **closes six of that frontier's ten members** (`survival/{accumulate,
actions, compile, receipt_state, score_state, transitions}`). Changed: `survival/actions.py` (`owner: str`
and the four `str | None` reference fields deleted, `holder: int` and `LiveAmp` added), `survival/compile.py`,
`survival/transitions.py` (rank comparisons only; kernel bodies untouched), `survival/accumulate.py` (one
`SumPlan`), `survival/receipt_state.py` (loses annotate-during-walk), `participant_timeline.py` (composition
and orchestration only), `pipeline.py` (projection satisfaction), `trigger_stream.py` (this phase's two
`MechanicCapability` fields and the `HolderStacking` enum, nothing else — L2 has long merged; runbook
ownership map), `capabilities.py` (schema 4, `ViewTag`
published, phase list still derived), `ability_spec.py` (the `Quantity` algebra beside `Disposition` —
D-72, a sequential handoff after L2 merges; runbook ownership map), `static/js/app.js` (S9's
withheld-marker rendering helper — this phase's only UI commit; measured leaves stay bare numbers and
their unchanged rendering is pinned by test). Preserved untouched: `shield_ledger`, `run_survival_walk`,
`ScoreLedger`,
`build_states`, `finalize_states`, `CoupledSearchContext`, `_SignaturePanel`, every pair/panel cache.

```python
# program/identity.py
PIdx = NewType("PIdx", int)                      # roster index; id strings never enter the walk
MechanicId = NewType("MechanicId", str)          # Phase 2's CAPABILITIES key — one spelling, not a
                                                 # third name for MechanicCapability.mechanic
Origin = PairOrigin | SupportOrigin | ReactiveOrigin | DerivedOrigin
class EventId(NamedTuple):
    origin: Origin; ordinal: int
def event_id_text(event: EventId) -> str
    """The only producer of a public event-id string; byte-identical to today's four f-strings."""

# program/events.py
EventPayload = (Damage | Recovery | Barrier | TemporaryHealth | Revive | CombatState
                | SpellShield | StatBuff | DamageModifier | OnHitMagic | Utility)
Rider = Execute | Defer | Redirect | Wound | AmpBonus
class PairEvent:    # frozen: id, time, sequence, rank, payload, riders, route — authored, unrouted
class RoutedEvent:  # frozen: id, subject, source, time, rank, payload, riders — what compiles
def payload_from_packet(packet: Mapping[str, Any], *, origin: Origin) -> EventPayload
    """Classify one authored packet into the closed union, or raise UnclassifiedEvent."""

# program/route.py
RoutePolicy = (SelfOnly | Holder | PairDefender | AllOpponents | AllTeammates | SelfAndAllTeammates
               | SelfAndOneTeammate | OneTeammate | ExplicitTargets | TriggerTarget)
def resolve_route(policy: RoutePolicy, ctx: RouteContext) -> tuple[PIdx, ...]
    """Total, fail-closed subject resolution; closes issue #142 for item packets too."""

# program/amp.py — interprets Phase 3 declarations; declares no rule vocabulary of its own
class Provenance:   # frozen: holder: PIdx, priced_by, applies_to, damage_classes, attack_classes
    """Construction rules make the missing-owner and untyped-amp defects unconstructible.
    Compiles to SurvivalAction.holder — a plain int slot S1 adds in place of owner: str —
    plus the class fields 0B added.  PIdx narrows the index here, never in survival/."""
def modifier_events(rule: DeltaAmpRule, trigger: Trigger, holder: PIdx) -> tuple[PairEvent, ...]
    """Compile one declared delta_amp into armed DamageModifier events for the coupled lane."""
def arm_key(subject: PIdx, mechanic: MechanicId, holder: PIdx, stacking: HolderStacking
            ) -> tuple[PIdx, MechanicId] | tuple[PIdx, MechanicId, PIdx]
    """The exactly-once dedupe key.  IDEMPOTENT_AURA drops holder from the key; PER_HOLDER
    keeps it (D-66).  A dropped duplicate emits a `dedupe` receipt row.  Both branches are
    written because PER_HOLDER is Command's fail-closed default and therefore the live path:
    a signature that can only express the aura key silently dedupes a second Mandate holder
    away — the incident's own shape — and makes criterion 10's two-holders-arm-two half
    unimplementable."""

# program/build.py
@dataclass(frozen=True, slots=True)
class CapabilityView:
    """A frozen projection of trigger_stream.CAPABILITIES — program/'s only reader of
    compilability, view_tags and holder_stacking.  Values, never callables."""
class Projection(Enum): ...   # SCORE | RECEIPT — which fields the compiler reads, never which events exist
@dataclass(frozen=True, slots=True)
class ParamPatch:
    """The per-pass parameter overrides CrossPassDependency feeds pass 2; frozen, and the
    only way a later pass differs from its predecessor."""
def pair_program(result: Mapping[str, Any], origin: PairOrigin, caps: CapabilityView) -> PairProgram
    """One attacker x defender fight as immutable events; sequence required, ids not order-derived.
    ``result`` is one engine result, typed exactly as Phase 2 types authored_triggers' input —
    not a new EngineResult name for the same object."""
def derivation_order(caps: CapabilityView) -> tuple[MechanicId, ...]
    """Producer order derived from the capability graph; a cycle raises DerivationCycle."""
def build_program(actors, pairs, caps, *, pass_index: int, patch: ParamPatch | None) -> Program
    """The whole fight, frozen, routed and ranked — before any representation choice."""

# program/rung.py + program/compile.py
Rung = CompiledFast | CompiledFull | ReceiptWalk(reason) | SearchPoisoned(reason)
def select_rung(program: Program, projection: Projection, caps: CapabilityView) -> Rung
    """Once per candidate, or once per search for a roster-held ReceiptOnly mechanic."""
def compile_program(program: Program, *, projection: Projection) -> tuple[SurvivalAction, ...]
    """The one SurvivalAction constructor in src/."""
class ProgramKey(NamedTuple): ...                                 # the roster/actor/params
                                                                  # fingerprint triple caches.py declares
def program_key(program: Program) -> ProgramKey                   # value keys, never id()

# program/walk.py -> the unchanged kernel; program/dependency.py drives the passes
Ledger = ScoreLedger | ReceiptLedger | OutcomeLedger               # the three kernel-side ledgers
def walk(program: Program, ledger: Ledger) -> WalkResult
    """Compile, run run_survival_walk once, freeze (states, outcomes, coverage, rung)."""
def run_passes(program: Program, deps: Sequence[CrossPassDependency], ledger) -> WalkResult
    """Rebuild the program per pass; never re-enter the walk; raise IncompleteDependency."""

# survival/outcome_state.py — the third ledger, beside score_state.py / receipt_state.py
class OutcomeLedger:
    def write(self, action: SurvivalAction, **fields: Any) -> None   # write-once per field
    def adjust(self, adjustment: Adjustment) -> None                 # ordered, reasoned
    def get(self, action_slot: int) -> Outcome                       # applied/absorbed/to_health/overkill

# program/views/__init__.py — ViewTag's home; every view takes exactly (Program, WalkResult)
class ViewTag(Enum): ...                            # THEORETICAL | APPLIED
def serialize_leaf(path: str, q: Quantity, tag: ViewTag) -> LeafOut
    """The only producer of a payload leaf AND its dispositions entry (D-72).
    Measured/StructuralZero emit the bare number plus the entry; Withheld emits no
    number and an entry carrying the receipt; Starved has already raised on read."""
def score(program, result) -> Score                 # optimizer scalar + ordering audit
def breakdown(program, result) -> Breakdown         # per-attacker rows
def survival(program, result) -> SurvivalRows       # takes program too, per criterion 3
def tdd(program, result) -> TddRows                 # the THEORETICAL / APPLIED pair
def receipt(program, result) -> PublicTimeline      # the only event-dict producer; emits the
                                                    # parallel `dispositions` map (leaf path ->
                                                    # {disposition, view_tag}); leaves stay bare
```

## Success criteria

Additional to the eleven per-commit gates in the [runbook](./silent-failure-runbook.md), which gate every stage.

1. **One walk.** Exactly one `run_survival_walk(` call site in `src/`, inside `program/walk.py` (baseline two);
   one `/api/calculate` request or one optimizer candidate evaluation invokes `walk()` exactly `len(passes)`
   times, asserted by a runtime counter on `WorkCounters`; and a fixture asserts the `WalkResult` feeding the
   score view and the receipt view of one request is the **same object** (`is`), not an equal one. *Without
   the last two clauses, building one program for the score projection and a second for the receipt
   projection satisfies "one call site, one walk per pass" while keeping today's two invocations under new
   names.*
2. **One constructor.** `SurvivalAction` construction expressions outside `program/compile.py` = **1**
   (baseline 9; `grep -c "SurvivalAction("` returns 11 because it also matches the class statement and a
   docstring). The one survivor is `survival/actions.py:601`'s `_ACTION_DEFAULT_ROW`, the issue-#171 fast
   constructor that criterion 17 names as the declared performance fallback — declaring it here is what keeps
   criteria 2 and 17 from being mutually exclusive. All seven `survival_action_from_event` call sites and
   `WalkCompiler`'s duplicated branches are gone.
3. **View purity.** An AST assertion shows no module under `program/views/` — **nor any `src/` function in a
   view's call graph** — performs arithmetic on ledger values; each view's inputs are exactly `Program` and
   `WalkResult`; and a runtime fixture over the four bench scenarios asserts every numeric field a view emits
   is bit-identical to a leaf already present in `WalkResult`/`Program`. *A path-scoped purity check is
   satisfied by moving the arithmetic to `program/view_math.py` and calling it.*
4. **No mixed-view sums, and no double-applied ones.** Every serialized numeric field carries exactly one
   `ViewTag` — through criterion 5's `dispositions` map, never as a field on the bare number;
   `view_tags` holds exactly one tag per `(mechanic, EngineLane)`; at most one `APPLIED`
   contribution exists per `(mechanic, subject, event_id)` across all producers, asserted as a uniqueness test
   on the `OutcomeLedger`; folding differently-tagged sources is a construction error; retagging a field
   `THEORETICAL` makes the optimizer and BIS paths fail rather than silently score it.
5. **Public schema.** `CAPABILITY_SCHEMA_VERSION` is **4** at the phase tip — S9's value in D-63's chain,
   one past Phase 3's 3.8 bump to 3, and the only bump this phase makes unless S6 publishes a new phase
   name, in which case S6 takes 4 and S9 takes 5 —
   `PARTICIPANT_LEDGER_CONTRACT["phases"]` is derived from `TransitionRank` and never hand-listed, and
   **every numeric leaf of the `/api/calculate` payload — score, breakdown, survival, tdd and timeline —
   is covered by exactly one entry in that payload's parallel `dispositions` map** (leaf path →
   `{disposition, view_tag}`, produced only by `serialize_leaf` over `Quantity` — the serialization
   ruled in *View semantics*; `MEASURED`/`STRUCTURAL_ZERO` leaves stay bare numbers, and a `WITHHELD`
   leaf is absent with its receipt-bearing entry present, rendered by `app.js`'s withheld-marker
   helper); **a numeric leaf with no map entry, or a map entry naming neither a present leaf nor a
   withheld path, fails the payload-schema test — a backstop behind the single writer, not the
   mechanism.**
   **The same holds for every numeric leaf of the `/api/bis` (`app.py:1296`) and `/api/optimize`
   (`app.py:1331`) payloads, which the score view produces** — otherwise every criterion here passes while
   the two largest numeric surfaces serve undispositioned zeros, and D-23 covers only their `withheld[]`
   and exclusion count. This
   is where the umbrella's criterion 1 is discharged.
6. **Identity.** `event_id_text` is the only producer of a public event-id string, byte-identical to the four
   legacy formats across the coupled baseline; `SurvivalAction` carries zero `str | None` reference fields
   **and no `owner: str`** — the owner skip reads the plain-`int` `holder` slot introduced by S1 in the same
   commit that deletes the string field, so no commit in the phase leaves the kernel with both or with
   neither, and `PIdx` has zero occurrences under `survival/`.
7. **Ordering.** Zero float `phase` literals in `src/` (0A drove them to zero; this criterion re-asserts it);
   `legacy_phase` deleted; the sort key is **eight** elements in D-67's order.
8. **S6's diff is bounded by prediction** — same-timestamp aura-vs-damage, debuff-vs-recovery, stat-buff and
   on-hit-magic reorderings only, each with a named fixture, each predicted before the baseline is read, with
   its **expected qualifying-occurrence count declared in advance** (R-20). The three **non-pure** stages
   state theirs — S6 and S7 are semantic, S8 is enabling, per the stage table: S6 and each of S7's four
   landing commits declare a per-scenario count; S8 declares 0. Pure stages declare 0 by definition.
9. **Routing.** `resolve_route` is total and fail-closed for item packets as well as champion packets; the
   first-defender scan has zero occurrences; a Command mark routes to `TriggerTarget`; an `Unreviewed` `CcScope`
   resolves to `SingleTarget` on the pair defender and emits a disclosure naming the ability.
10. **Arming dedupe is declared and correct in both directions.** `holder_stacking` is a required,
    defaultless field on `MechanicCapability` — one of exactly two this phase writes there — carrying a
    `HolderStacking` for every dual-sided mechanic and `None` for every other, structurally validated at
    import like `pair_of`, so a dual-sided declaration that omits it fails to construct rather than
    inheriting a guess; one test per mechanic shows two holders of an `IDEMPOTENT_AURA` arming **one** modifier
    with a `dedupe` receipt row, and two holders of a `PER_HOLDER` mechanic arming **two**; `arm_key` is the
    only arming dedupe in `src/`, asserted by source scan. *(There is no `unique` cache flag to delete —
    `grep -rnE '"unique"|\bunique\s*=' src/` finds only `item_source._RIOT_BARE_LABELS` and SQLAlchemy
    columns, so a criterion asserting its absence could never fail.)*
11. **Authority declared for all seven authority moves. Four land** — Hypershot, Abyssal, Bloodsong,
    Shadowflame; Command, Carve and Vile Decay each carry their blocking `[H]` id in the capability row
    rather than a guessed ruling. Hypershot's canary commit shows zero diffs on both baselines.
12. **Shadowflame.** Its bonus is a rider — a spell-shielded, state-blocked or post-death trigger emits none,
    shown by fixture; the predicate is read before absorption; contribution rises in a multi-attacker roster,
    and a downward diff carries its own oracle receipt.
13. **Catalyst.** Zero recursive `build_participant_timeline` calls in `src/`; pass 2 runs with caches and
    search context live; `IncompleteDependency` replaces the untyped `ValueError`; its `Compilability` is
    unchanged unless a pass-2 compiled-equals-receipt fixture is green.
14. **Caches and precision.** Every cache declares `invalidated_by` and a test proves the declared set covers
    every field its value reads; frontier counter 7 (`id()`-keyed caches whose key is not derived from the
    served value, over `src/calculator/{survival,program}` and `stats.py`) is **0** against the baseline the
    script measured on its first run, with `champions/`'s two named on the frontier as out of scope;
    `packet["_typed"]` has zero occurrences; `round(` outside `program/precision.py` = **0 within `program/`**,
    while `survival/`'s count is counter 6, non-increasing from 118; `SumPlan` ids are unique across the three
    panels — each event summed once, the ordering declared, and a cross-panel repeat recorded rather than
    silently folded twice; and per-attacker totals are asserted **bit-exact** against
    `scripts/golden_coupled_exact.json` (R-13's `capture-coupled --exact`), since golden compares at two
    decimals and no other instrument emits unrounded totals.

    > **Clause history (S10, 2026-08-13).** The bit-exactness clause read "asserted **bit-exact** on the four
    > bench scenarios against `scripts/golden_coupled_exact.json`". The words *on the four bench scenarios*
    > were removed and replaced by the note below, in commit `7430805`. Recorded here, in the criterion, and
    > not only in that commit's body: a criterion that moved inside the slice being graded on it is invisible
    > to anybody who reads the criterion afterwards, and this campaign's subject is the claim whose past
    > cannot be checked. The clause is **not** discharged over the set it now leaves unnamed — the gap is the
    > escalation row below, and it inverts on the day the capture happens.
    >
    > **The scenario set that sentence names is not the set the instrument holds**, and the divergence is a
    > dated, gated row on `docs/receipts/escalated-defects-P4-S10.json` rather than a restatement here. The
    > exact baseline's scenarios are R-12's — derived from the `damage_modifier` producer set, both ledger
    > shapes and one Catalyst roster — and none of them is one of the four bench scenarios this criterion
    > names. Adding them is a write to one of R-32's five baselines, which is the integration agent's and not
    > an implementation lane's; the escalation names exactly that, so the gap is carried by an artifact
    > instead of by a sentence a lane rewrote to match what it could reach.
15. **Tuple predicate.** All **ten** adequacy clauses are gone from `pipeline.py` — the nine Phase 4 owns plus
    Phase 2's derived one — replaced by projection satisfaction, with `HEALING_RULE_CHAMPIONS` carried by a
    `ChampionSlotOwner` capability, `target_threshold_health_heal` (and its mirror at `damage.py:9955`)
    expressed as a declared adequacy condition, and stat-derived adequacy expressed as `requires_fields`; the
    derivation landed beside the legacy predicate with an asserted zero delta before the one-symbol flip.
16. **Fallback fully accounted.** The rung histogram accounts for 100% of evaluations in all four bench
    scenarios; `SearchPoisoned` appears only for genuine invariant errors, never for a declared roster
    mechanic — which requires the ladder to have a production path at all, so every member of `program/rung`'s
    union is constructed in `src/` and every histogram key is `counter_label` of a decision rather than a
    label chosen beside one.

    > **Clause history (S10, 2026-08-13 and 2026-08-14).** This criterion read: "every `damage_modifier`
    > holder reports `RECEIPT_WALK` with a named receipt; no criterion in this phase asserts a compiled amp
    > under the umbrella's recorded H5 disposition — and if the umbrella records no disposition this criterion
    > is not dischargeable and the phase does not exit; `SearchPoisoned` appears only for genuine invariant
    > errors, never for a declared roster mechanic." Commit `7430805` replaced the amp half with the two-stage
    > reading below and added the production-path clause above; commit `7868927` made that added clause true,
    > which it was not when it was written — `CompiledFull` had zero construction sites in `src/` on the
    > commit that introduced the sentence requiring them. Both moves are recorded here rather than only in
    > those commit bodies, for the reason criterion 14's note gives: an acceptance target that moved inside
    > the slice being accepted is invisible to the next reader of the target. The half that has never moved
    > is "**with a named receipt**".

    The amp clause is **read in two stages, and the umbrella says which**. Its H5 row records the disposition
    verbatim: *"Phase 4's criterion 16 is read under this scoped ruling — through S7 it reads exactly as
    written, no criterion of that phase asserting a compiled amp and every `damage_modifier` holder reporting
    `RECEIPT_WALK` with a named receipt, and it is re-read against the compiled lane only **once the new
    stage's flip lands**, on the evidence of that stage's equivalence fixture rather than on this ruling
    alone."* That flip landed at stage `P4-S7H5`, whose own wall row and
    `docs/receipts/expected-golden-diff-P4-S7H5-kernel.json` record it, so **the second reading is the live
    one**: a `damage_modifier` the H5-extended kernel represents compiles, on the evidence of that stage's
    equivalence fixture, and a `damage_modifier` it still cannot represent reports `RECEIPT_WALK` **with a
    named receipt** — the reason being a receipt rather than a log line is the half that does not move
    between the two readings. Restating it here is executing the umbrella's own instruction, not writing a
    descope: this document may not author an H5 disposition and does not, and if the umbrella had recorded
    none the criterion would still be undischargeable and the phase would not exit.

    > **"With a named receipt" is discharged at the decision, not at the histogram**, and that is a scope this
    > criterion states rather than leaves to be discovered. Both failure rungs *require* a reason — one
    > without it is unconstructible — and `tests/test_amp_kernel.py` reads each declining producer's receipt
    > off its declared `HolderStacking`. What no reader receives is the reason: the counter sink is five
    > fields and none of them is a string, so the published histogram names the rung and its scope and never
    > which declaration refused. Publishing it is a sixth field on L0's harness contract, which is why it is a
    > dated row on `docs/receipts/escalated-defects-P4-S10.json` and not a sentence here.
17. **Performance neutrality.** Pure stages are identical on all four counter families, the residual, the winner
    and the score; wall best-of-3 isolated stays within +10% of **that stage's own declared baseline** in
    `campaign-fingerprints.json`; S4's `allocation_probe` peak stays within its 15% margin — and if S4 cannot
    hold the ratchet the declared fallback is to keep `compiled_damage_action` as the compiler's inner loop and
    treat the program as a build-time-only artifact, never to relax the gate.
18. **Frontier.** `scripts/migration_frontier.py` reports counters 5–7 at their stage targets, its exclusions
    and the `preserved_defect` rows (including `LATE_BARRIER`) live in `docs/migration-frontier.json`, and
    set-equality on that file is a gate. The receipt moves with the slice that moves a counter (R-36).
    **Front doors close and none open:** Phase 1's `front_door_report` resolves every new module this phase
    adds that its denominator counts (`src/calculator/**/*.py` minus `__init__.py`) — the five
    `program/views/*` among them, and those five only because their shared test file **binds each as a
    symbol**, not because it mentions the package — so `FRONT_DOOR_FRONTIER` loses exactly the six
    `survival/` members this phase closes and gains nothing, checked by the set-equality gate Phase 1 ships.
19. **Dispositions propagate through sums — structurally.** Propagation is `Quantity.__add__` (D-72),
    unit-tested over the full member × member matrix including the `Starved`-read raise; a source
    assertion shows no view or ledger read folds disposition-bearing values outside the algebra; and
    **one roster fixture with a `WITHHELD` component remains as the end-to-end backstop**, asserting
    every total reading it is itself `WITHHELD` and names the member. *Without the type, five measured
    components and one withheld one sum to a `MEASURED` total that quietly counted the withheld member
    as zero — the incident re-created at the aggregate, fully compliant with every per-item criterion;
    with it, that failure is unrepresentable rather than merely tested-for.*
