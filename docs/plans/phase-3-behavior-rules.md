# Phase 3 — Item Behaviour as a Closed Rule Union

**Prerequisites:** Phase 0 (0A + 0B) and Phase 2 complete; Phase 1 merged — its resolver reads the tag-claims this phase authors.
**Decisions owned:** **D-40…D-52 except D-45** (Phase 1's), plus **D-101** — the ruling that the compiled score kernel categorically cannot represent a `damage_modifier`, and the empty-compiled-lane declaration that follows from it. Split halves consumed here: D-44 binds Phase 5's rename, D-47's audit change is 0A's, D-49's counter is declared in 0A and Phase 3 keys seven of the nine surviving memos, D-101's compiled-lane criterion is Phase 4's, and **D-63's third schema bump is this phase's** — 3.8's coverage flip takes `CAPABILITY_SCHEMA_VERSION` to 3, with 1 and 2 owned by Phase 0 and every later bump by Phase 4.
**Cross-phase authority:** [umbrella contract](2026-08-08-silent-failure-campaign.md) (the decision table, `[H]` items H4/H5, the pair-vs-walk authority rule) and the [campaign runbook](silent-failure-runbook.md) (verification matrix, golden protocol, performance protocol, lane/worktree rules). Numbers that more than one phase depends on live there and are not restated here.
**Worktree lane:** L4, alone within the serial chain — it rewrites `item_support_effects.py`, which no other chain lane may touch, and it owns `src/app.py` for the coverage flip.

## Goal

Every item and keystone behaviour is a frozen `BehaviorRule` of a closed 18-family union, holding live `ValueRef`s and a `SourceReceipt`, interpreted by exactly one interpreter per family per engine lane — so an undeclared or uninterpreted behaviour is automatically **withheld with a named receipt**, never priced as zero.

## Decisions

### Vocabulary and closure

- **The vocabulary is `BehaviorRule`, never "atom" (D-44).** `atomizer.Atom`, `atomizer_domains`, and `rotation_resolver`'s "TYPED atoms" are three live meanings already; a fourth reproduces the "three things named champions" quirk against repo rule 1.
- **Phase 3 exports `EngineLane`; Phase 1 exports `ClaimLane` (D-45).** Two new `src/calculator/` modules must not both export `Lane`.
- **`RuleFamily` is closed at 18 and the tag map over `item_effects._KNOWN_EFFECT_TYPES` is total and single-valued.** Closure is a test, not a convention: a new `_KNOWN_EFFECT_TYPES` member or a new `ActionKind` fails collection until it is mapped. Verified at HEAD: 38 tags, 123 `ITEM_EFFECTS` entries (every tag observed, no unused member), 19 `ALLY_ITEM_EFFECTS` entries, 19 `ActionKind`s, 11 packet kinds over **29** `kind=` sites (28 literal, plus the runtime-computed one at `item_support_effects.py:742`, which D-50 splits into two declared packets) and 29 `source=` sites in `item_support_effects.py`, and **every `DefenseSource` construction in `defensive_effects.py`** — the counting rule stated so the figure is reproducible: 25 at HEAD, being the 17 module-level `_*_SOURCE` bindings plus the 8 inside `_ANNUL_SOURCES` (3) and `_OPENING_DEFENSE_SOURCES` (5). **The producer count is derived, never typed**: `len({site.source for site in packet_sites(...)})` over Phase 1's `packet_sites` — otherwise "25 producers" and Phase 1's "29 packet sites" are two numbers for one population with no stated mapping. **The defensive count is derived the same way**, by the closure test over the module's own constructions, so no integer here is a second thing to maintain.
- **Ten of the 38 tags are dispatched on by no engine, and they are declared, not deleted, in this phase.** Measured: **four are dead** — read nowhere in `src/` (`conditional_attack_speed`, `shield_reduction`, `target_state`, `target_attack_speed_aura`); **six are self-referential** — read only by `item_coverage.py`'s own claim (`defensive_start`, `stat_conversion`, `sustain`, `target_mitigation`, `target_threshold_health`, `target_threshold_shield`) while the behaviour itself is reached by item name in `defensive_effects.py`/`stats.py`, so the tag exists to justify the prose that cites it. This four/six split, with its members, is the authority; the umbrella's H4 row quotes it and the two must not disagree. Deleting or re-pointing them is **H4**, the human's. Phase 3's fail-closed default maps all ten into families with an explicit reason each and carries them on the frontier; the name-site migration below converts the self-reference into a real dispatch as a side effect, which is why H4's recommended answer and this phase's direction agree.
- **No callable, `dict`, `Any`, or open string survives in a `BehaviorRule` *policy* field** — every policy axis resolves to a closed union or a `ValueRef`. Two exceptions are written into the criterion rather than left to make it quietly false. (a) D-52: the `_COMPILERS` / `INTERPRETERS` registries themselves — dispatch keyed by a closed enum, values are module-level `def`s (never lambdas or closures), totality asserted by `validate_registrations()`. (b) The `str`-typed fields that are **identifiers and citations, not policy** — `owner` and `mechanic_id`, `SourceReceipt`'s three citation fields, and the reason strings on `ReceiptOnly` and `zero_policy` — each named in the assertion. *Why name them: a criterion that must be waived on first contact with this phase's own Shape block is exactly what D-52 forbids.*

### The delta/pool kernel

- **Seven amp *chain slots*, not four, and the chain order is declared.** Verified at `damage.py:9889-9903` for the outer five calls (Shadowflame → Expose Weakness → First Strike → Press the Attack → `_apply_damage_amplifiers`) and at `damage.py:9227-9293` for the two inside it: general amps (additive among themselves) → Command → Hypershot. `lane_chain_rank` is an explicit integer and `AMP_CHAIN_ORDER` — the compiled sequence — is asserted against a frozen tuple, because today nothing stops a refactor reordering the chain and moving every mixed build's number. *These seven chain slots are **not** Phase 4's seven authority moves; the two sets overlap but neither contains the other, so each document names its own.*
- **`Activation` carries `LivePredicate`; Shadowflame is not forced into a window.** Its predicate reads `pools.health` mid-simulation (`damage.py:1905-1909`); it is the one amp whose pool cannot be precomputed, and the algebra must not pretend otherwise. It declares `requires_live_pool=True` and a test asserts no interpreter precomputes a live-predicate pool.
- **`Consumption` is an orthogonal axis on `Activation`: `PERSIST | NEXT_EVENT_ONLY | N_EVENTS(k)`.** Dream Maker's Blue Dream Bubble (`item_support_effects.py:757-777`, `damage_reduction=True, next_event_only=True`, no `owner`) is the sixth `damage_modifier` producer and is expressible in neither Phase 3's activation union nor Phase 4's `Stacking` without it. It declares `NEXT_EVENT_ONLY`; **its authority is `COUPLED_ONLY`, settled in 0B** and verified there (no pair-engine pricer for Blue Dream Bubble exists in `src/`) — Phase 3 models it, and declaring `SPLIT` here would be rejected by 0B's owner-iff-`SPLIT` check.
- **`magnitude` is a four-member union** (`Fixed | RampPerSecond | TargetBonusHealthScaled | RampPerStack`) — exactly the shapes the five `amp_fraction` closures in `_compile_damage_amplifier` (`item_effects.py:4560-4639`) implement. This union *is* the removal of `DamageAmplifierEffect.amp_fraction: Callable`.
- **Keystones enter the catalog with the amps.** First Strike and Press the Attack are `delta_amp` declarations over a `RUNE_EFFECTS` `ValueRef`; `_certified_ledger` becomes the `CERTIFIED_ONLY` pool constructor. CLAUDE.md rule 5 extends the no-literals rule to keystones, so an items-only union would leave two runtime amp producers outside it.

### The four bespoke amps — authority and migration

Authority itself is a field on Phase 2's `MechanicCapability` and the *moves* are ruled in the umbrella; Phase 3 declares the rule shape, fills `values` and `compilability`, and asserts the two agree. Each of the seven amp sites is one commit.

- **Horizon Focus Hypershot ships first as the kernel canary.** `PAIR_ONLY`, declared: its exclusion set is "the trigger ability's own damage", a pair-local rotation fact, and coupled emits nothing. Expected exact no-op — if the canary moves a number, the kernel is wrong, not the mechanic.
- **Imperial Mandate Command is declared once, for both engines, as `TriggerWindow(immobilize, merge=EXTEND, boundary=OPEN_CLOSED)`.** The walk's multiplicative-per-immobilize behaviour is the divergence; `EXTEND` is the wiki reading the pair engine already implements (`damage.py:9296-9323`). The authority move to `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` is Phase 4's and is blocked on **H2**; Phase 3 does not move it.
- **Bloodsong Expose Weakness freezes its divergence behind a `DivergenceReceipt`.** Pair is `ExcludeTrigger`/`COARSE_ROW` with no authored events; walk is `TriggerWindow`. They are not numerically equivalent, and unifying them inside a slice labelled a pure refactor would hide a semantic correction under a zero-diff claim. Phase 4 corrects it with the Command slice.
- **Shadowflame Cinderbloom lands last, and the Liandry reprice is extracted in its own prior commit.** The max-health repricing of the Liandry burn key rides inside `_calculate_shadowflame_bonus` (`damage.py:1888-1903`) and is an unrelated mechanic; carried along, the Shadowflame commit silently owns it and its diff is unattributable. Shadowflame's authority move is Phase 4's, last of seven.
- **General amps, First Strike and Press the Attack are pure migrations** — identical pool, attribution and typing — and are expected zero-diff on both baselines.

### Values, receipts and refresh

- **`ValueRef.registry` is a three-member union from day one: `ITEM_EFFECTS | ALLY_ITEM_EFFECTS | RUNE_EFFECTS` (D-46).** Phase 1's **`EvidenceRegistry`** literal carries the same three members plus `ITEM_INPUT_OPTIONS`, which `OptionSchema` needs and `ValueRef` must not have. The two names stay distinct exactly as D-45 keeps `ClaimLane` and `EngineLane` distinct; there is no Phase 1 symbol called `ValueRegistry`.
- **A frozen declaration may hold references, never numbers.** `Const` is structural only — counts, caps, ranks, booleans — and a reflective test asserts every non-integral float field is a `ValueRef` and every integral one is in `_STRUCTURAL_EFFECT_KEYS`. `ValueRef.get()` routes through `required_effect_value` / `ally_item_effect_value` / the rune accessor, so rule 5's fail-loud behaviour survives with item-and-key context.
- **The refresh proof mutates the cached JSON, not the registry (D-48).** `refresh_item_effects()` rebuilds `ITEM_EFFECTS` from `data/`, so a monkeypatched registry value is overwritten by the parsed one — that test proves liveness but cannot distinguish "holds a reference" from "was reconstructed". One rule per family is proven this way.
- **Interpreter memos key on `data_registry.data_version()` (D-49), never on object identity alone.** The counter is **declared in 0A** and Phase 3 consumes it; Phase 3 keys the **seven** non-rotation survivors and Phase 5 keys the two rotation memos, which together are the nine `refresh_item_effects()` does not clear. The existing identity re-check (`item_effects.py:4698-4711`) is the pattern; a counter is what stops the eleventh derived memo being the one patch day forgets. `ALLY_ITEM_EFFECTS` is hand-authored and refresh-*inert* (D-47) — four of the six `damage_modifier` mechanics read their numbers from it — so the catalog's receipts must be audited by `scripts/patch_update.py` (the 0A half of D-47), not assumed live.
- **Every rule resolves a `SourceReceipt(url, revision_id, revision_timestamp)` or the catalog fails at import.** Resolution order: the owning registry entry's own `source_url`/`source_revision_id` → the family's declared constant → raise. `defensive_effects.DefenseSource` is deleted into it; `scripts/full_entry_audit.py` and `scripts/item_umbrella_audit.py` consume catalog receipts instead of re-deriving them.

### Topology, lanes and compilability

- **The catalog is modelled on `rune_effects._KEYSTONE_COMPILERS` + `resolve_keystone`** — the one existing compile-fresh, fail-closed registry in the repo. Inventing a second registry idiom for the same job is the drift this campaign exists to prevent.
- **`interpreters/` is one module per family, never one dispatch file**, each owning its family's test front door — otherwise the phase ships an 18-branch god module and trips the derived front-door check (D-95). `value_ref.py`, `item_behavior.py`, `item_behavior_catalog.py` and `interpreters/__init__.py` each name their own test front door too; 22 new modules with 18 declared doors would grow Phase 1's set-equality-gated frontier.
- **Walk-lane interpreters are compiled to kernel data; `survival/` never imports `interpreters/`.** `RECEIPT_WALK` and `COMPILED_SCORE_WALK` interpreters run at *build* time, emitting value-typed fields the kernel already understands — the same device Phase 4 uses for `LiveAmp`. The dependency stays one-way `interpreters/ → survival/`, and a source assertion pins that no module under `survival/` imports `interpreters` or `item_behavior_catalog`. *Why: `Interpreter.apply(...)`'s ellipsis hides the phase's real cycle risk — an interpreter that touches `SurvivalAction`/`TransitionContext` and is called from `survival/transitions.py` closes a loop the acyclicity proof for `item_behavior.py` does not cover.*
- **Lane membership is derived, never hand-listed, and the assertion is on resolved values (D-41):** no container in `src/` outside `interpreters/` whose members are all names in `data/items.json`. A tuple, set literal or list defeats the syntactic version. Counter 1 supersedes `test_damage_engine_does_not_dispatch_on_item_names` (D-42), which only inspects `ast.Compare` and passes today while `damage.py`'s 15 sites are all `ast.Call`.
- **`Compilability` is a per-*rule* field, not a per-family lane predicate (D-43).** `COMPILED_WALK_UNREPRESENTABLE_ITEMS` (`survival/compile.py:68`) holds 16 item-level reasons, three of which are conservatism notes rather than representability facts (`Doran's Blade`, `Doran's Ring`, `Fimbulwinter`); a family predicate cannot reproduce it — withholding `stat_conversion` would withhold 23 entries and `sustain` 8. Phase 3 owns the field; Phase 4 consumes it. **The per-owner fold is declared, not left to the caller**: `compilability_for(owner)` returns `ReceiptOnly` if any of the owner's rules is `ReceiptOnly`, with the reasons concatenated in declaration order, and `Compilable` only when every rule is. Consumers wanting rule granularity read the rules; the fold exists so a per-item legacy set has a per-item successor.
- **The hand set is replaced by derivation-beside-legacy, then flipped in a one-symbol commit (D-98).** The derived receipt lands next to `COMPILED_WALK_UNREPRESENTABLE_ITEMS` with an asserted set-equal delta before either is deleted, so the change is revertible.
- **D-101 is this phase's, and both H5 branches are specified.** The compiled score kernel categorically cannot represent a `damage_modifier` today (`unrepresentable_template_receipt` returns `support_kind=<kind>` for anything but `shield`/`heal`, and `add_support_templates` raises on it). **If H5 is descoped** — a ruling the umbrella records, never this document — every `delta_amp` rule declares `ReceiptOnly` with that named reason and every amp holder falls back with a receipt. **If H5 is scoped**, it lands as its own stage after Phase 4's S7 with its own equivalence fixture; Phase 3 still ships `ReceiptOnly` for every `delta_amp` **in either branch**, and the flip to `Compilable` is that stage's one-symbol commit under D-98. Phase 3 never claims compiled coverage it does not have, and it is complete for both branches of a binary the umbrella says cannot be defaulted.

### Fail-closed coverage and reachability

- **`item_coverage.item_model_coverage` stops branching on names and computes status from declarations.** `withheld` (a declared family has no interpreter in a needed lane) and `review_pending` (described effects, no declaration) become automatic; the ten hand registries collapse to two — the reviewed `NO_RUNTIME_BEHAVIOR` prose the UI needs, and `_REVIEW_ISSUE_REFS`. Three of the ten (`_BLOCKED_REASONS`, `_CALCULATION_ALLOWED_BLOCKED`, `_PARTIAL_BLOCKED_REASONS`) are already empty at HEAD — two dicts and one `frozenset()` (`item_coverage.py:60`), so the assertion is emptiness, never `== {}` — and are asserted empty before deletion, so the honest count is seven real registries plus three empties. **Its signature and return type both change** — `item_model_coverage(name: str, needed: frozenset[EngineLane]) -> ItemCoverage` — so every caller moves in the same commit: `src/app.py:1033, :1081` (which serialize it straight into the public payload), `item_coverage.py:609, 689, 712, 717, 739`, `participant_timeline.py:700`, and `tests/test_item_coverage.py`. `src/app.py` is L4's for this flip, and because the serialized coverage payload changes, **3.8 bumps `CAPABILITY_SCHEMA_VERSION` to 3** — the third value of D-63's chain, after 0A's 1 and C4's 2. Phase 4's S9 owns the next bump; this document states no value but its own.
- **The `NO_RUNTIME_BEHAVIOR` set is a ratchet, not an escape hatch.** It is committed to `docs/behavior-frontier.json`, diff-gated by set equality, each member carrying a `SourceReceipt` and a reviewed reason, and its size is **non-increasing** from the measured pre-phase value. *Why: Counter 3's target is `declared ≥ 142 − |NO_RUNTIME_BEHAVIOR|`, so an unbounded reviewed-nothing set drives the counter to zero with the migration barely started.*
- **`UtilityDimension` is the closed enum over `item_coverage._UTILITY_DIMENSIONS`' distinct dimension strings — 43 keys, **29 distinct values** — and it is the single home**: at 3.8 Phase 1's `coverage_evidence.UTILITY_DIMENSIONS` becomes a projection of it and `_UTILITY_DIMENSIONS` is deleted, which is the fifth declared handoff Phase 1 lists. D-09 deleted `survival/actions.py`'s `utility_kind` and `state["utility_effects"]` in Phase 0A as dead state; Phase 3 must not resurrect a vocabulary for that field. The coverage-claim dimensions are a live, serialized surface and are a different thing with the same word in it.
- **Every intermediate slice interprets what it declares in the same commit, and any new withholding reason extends `champion_optimizer_matrix.EXPECTED_WITHHOLDING_PREFIXES` in that same commit (D-23, D-96)** — otherwise `pytest` is green while `acceptance_matrix.py` and the optimizer matrix are red in CI. `EXPECTED_WITHHOLDING_PREFIXES` is a gate script, not a receipt, so R-32 does not reach it; in-slice coverage moves land against the committed classification receipt plus `docs/receipts/expected-coverage-diff-<slice>.json` (R-36), which is what keeps D-96's same-commit rule and R-32's no-receipt-in-a-semantic-commit rule from deadlocking.
- **A withheld item is excluded from candidate generation and named in the response's `withheld[]`** (D-23) — never dropped silently and never scored zero. The per-request exclusion count is published and pinned by `champion_optimizer_matrix`.
- **Reachability is checked in both directions (D-51):** a declared marker reaches its consumer, *and* every interpreter branch is reachable from some declaration. Verified motivating cases exist in both directions — `enhanced_consume` (zero champions across the roster) and the `"invulnerability"`/`INVULNERABLE` spelling split between `participant_timeline.py:1953` and `actions.py`.
- **Redemption's `kind="damage"` packet gets a `secondary_target` declaration and Moonstone's runtime-computed `kind` becomes two declared packets (D-50).** A kind computed at runtime cannot be statically resolved by Phase 1's `PacketSource` or assigned a family.

### Frontier, ordering and gates

- **The frontier's four counters and their exclusion lists are committed to `docs/behavior-frontier.json` and diff-gated by set equality (D-40, R-36).** A frontier whose exclusions live only inside the tool that measures it can be driven to zero by editing the exclusions. **The counters are this document's, class `PRIOR` until `scripts/behavior_frontier.py` lands at 3.1, and re-measured on that commit — they appear in no other document.** Counter definitions, baselines and targets:

  | # | Counts | Baseline | Target | Retires at |
  |---|---|---|---|---|
  | 1 | Runtime item-name dispatch sites | **282** across 13 modules (the per-module tally in *Edited files* sums to it) | 0 | 3.4–3.7 |
  | 2 | Claim-prose sites — name-keyed container members outside `interpreters/` | **191** (`item_coverage` 188, `bis` 3) | ≤ the reviewed `NO_RUNTIME_BEHAVIOR` reason count | 3.8 |
  | 3 | Undeclared `ITEM_EFFECTS` + `ALLY_ITEM_EFFECTS` entries | **123 + 19** | 0 | 3.2–3.7 |
  | 4 | Uninterpreted declared `(family, lane)` pairs | n/a at baseline | 0 for `PAIR_ENGINE` and `RECEIPT_WALK`; every `COMPILED_SCORE_WALK` gap a named, tested fallback receipt | 3.9 |

  Class C (declarative homes, **600**) and Class D (**14** non-behavioural) are the committed exclusion sets. Counters **5–7 are Phase 4's** and live in `docs/migration-frontier.json`; nothing here reports them.
- **Counter 1 is measured over `src/**/*.py` by glob, minus the committed exclusions** — never over a fixed module list. `interpreters/` is exempt only for containers keyed by `RuleFamily`, never by item name. A negative test adds a name-dispatch site in a **new** module and asserts Counter 1 rises. *Why: "no site remains in any of the 13 baseline modules" is dischargeable by creating a fourteenth.*
- **Migration order is ruled, and the steps are numbered `3.1`…`3.9` because Phase 1 hands work to `3.8` by name:** `3.1` skeleton → `3.2` amps → `3.3` shred → `3.4` strike families → `3.5` defence families → `3.6` `ally_packet` → `3.7` residual families → `3.8` coverage flip → `3.9` exit verification. The amps go first because they are the campaign's named diagnosis, are self-contained, and prove the kernel before the bulk; `ally_packet` goes last among the migrations because it is the largest and most cross-engine and benefits from every earlier slice's tooling.
- **The `ally_packet` migration (3.6) lands as four commits by producer group — heals/shields · stat buffs · utility/quest · actives.** 132 name sites in one commit is unrevertible.
- **The Cesàro approximation is declared, not changed:** `magnitude=RampPerStack(..., model=CESARO_APPROX)`. `docs/math-foundations.md §2.3` calls re-tuning it a balance change, so making it visible is the whole intervention.
- **The coupled golden is the gate for the defence and `ally_packet` migrations; the plain golden is structurally blind to them (D-93).** Golden calls only `pipeline.run_fight` — no roster, no coupled walk, no `score_only`. A slice whose only cited gate is golden has no gate. All eleven rows of the runbook's verification matrix apply to every commit; golden is never re-captured inside a semantic slice (D-97).

## Shape

### New files

| Path | Responsibility |
|---|---|
| `src/calculator/value_ref.py` | Live references into the three number registries, plus `SourceReceipt` and `receipt_for` — the campaign's one home for both. Stdlib + `item_effects`/`rune_effects` accessors only. Front door: `tests/test_value_ref.py`. |
| `src/calculator/item_behavior.py` | `RuleFamily`, `BehaviorRule`, `EngineLane`, `Compilability`, and every closed policy union. Leaf: imports `value_ref` and `ability_spec` only, so `damage.py`, `survival/*`, `defensive_effects.py` and `item_support_effects.py` can all depend on it without a cycle. |
| `src/calculator/item_behavior_catalog.py` | Shapes, not numbers: the tag→family map, the per-family compilers, fresh compilation from the registries, `validate_catalog()`. |
| `src/calculator/interpreters/__init__.py` | The `(family, lane)` registry, lane derivation, bidirectional reachability, `validate_registrations()`. |
| `src/calculator/interpreters/<family>.py` × 18 | One interpreter per family, each with its own test front door. |
| `scripts/behavior_frontier.py` + `docs/behavior-frontier.json` | The machine-counted frontier and its committed, reviewed exclusion lists. |
| `tests/test_interp_<family>.py` × 18, `tests/test_behavior_declaration_acceptance.py`, `tests/test_behavior_frontier.py`, `tests/test_behavior_catalog.py` | Per-family behaviour, the synthetic both-engine property, the frontier gate, closure and reachability. |

### Edited files

`item_effects.py` (loses `amp_fraction`, `DamageAmplifierEffect`, `CommandAmpEffect`/`command_amp_effect`, the `hypershot_amp` accumulator; keeps sole ownership of numbers) · `rune_effects.py` (two keystone amps become declarations) · `damage.py` (7 amp functions and 15 name sites) · `item_support_effects.py` (132) · `defensive_effects.py` (77, and `DefenseSource` deleted) · `survival/compile.py` (18, and the unrepresentable set) · `pipeline.py` (15) · `survival/transitions.py` (7) · `participant_timeline.py` (5) · `roster_composition.py` (4) · `stats.py` (3) · `survival/receipt_state.py` (2) · `ally_effects.py` (2) · `survival/actions.py` (1) · `optimizer.py` (1) · `item_coverage.py` + `bis.py` + `src/app.py` (the coverage flip and its two payload call sites).

Those thirteen per-module counts sum to Counter 1's 282 baseline; the file's own line count is deliberately not stated, because the migration changes it on its first commit. `data_registry.py` is **consumed, not edited** — 0A declares `data_version()`.

### Type and function chain

```python
# value_ref.py — a declaration holds references; numbers stay in their registries
ValueRegistry = Literal["ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS"]
class ValueRef(registry, owner, key):        .get() -> float          # live read, raises naming owner+key
class LevelValueRef(registry, owner, min_key, max_key, scale):  .get(level: int) -> float
class DerivedValueRef(op: ADD|MUL|MIN|MAX|RATIO, operands):      .get(level: int | None) -> float
StructuralReason = Literal["count", "cap", "rank", "flag", "unit_scale"]  # closed; why a raw
                                                                 # number is legal in a declaration
class Const(value: float, reason: StructuralReason)              # counts, caps, ranks, booleans only
class SourceReceipt(url, revision_id, revision_timestamp)
def receipt_for(registry: ValueRegistry, owner: str) -> SourceReceipt   # resolve or raise; no unsourced rule

# item_behavior.py — the closed unions
class RuleFamily(Enum)     # strike: on_hit_strike charged_strike spellblade cast_proc periodic active_cast
                           #         secondary_target
                           # pricing: delta_amp resistance_shred crit_profile damage_routing
                           # defence: opening_defense threshold_defense combat_state reactive
                           # rest:    sustain stat_derivation ally_packet
class EngineLane(Enum)     # PAIR_ENGINE RECEIPT_WALK COMPILED_SCORE_WALK DEFENSE_RESOLVER STAT_RESOLVER
Compilability = Compilable | ReceiptOnly(reason: str)
Activation    = Always | AbsoluteWindow(start, end) | TriggerWindow(trigger, duration, merge, boundary)
              | AfterTrigger(trigger, strict) | ExcludeTrigger(trigger, isolation)
              | LivePredicate(probe, cmp, threshold)          # Shadowflame; requires_live_pool
class Consumption(Enum)    # PERSIST | NEXT_EVENT_ONLY | N_EVENTS(k)   — Dream Maker's axis
Magnitude     = Fixed | RampPerSecond | TargetBonusHealthScaled | RampPerStack(model=...)
class Pool / Attribution / Typing / Subject (Enum)
class DeltaAmpRule(pool, activation, consumption, magnitude, attribution, typing, subject, lane_chain_rank)
class BehaviorRule(family, owner, mechanic_id, payload, compilability, receipt, zero_policy)
    #  zero_policy: Disposition (ability_spec, 0A) + reason.  Required here; on
    #  damage_entry/simple_damage it is discharged by D-24's ruled exception — one
    #  declared default (MEASURED) at their single construction layer,
    #  champions/slotlib.py, overridable per call, so the 384 champion call sites
    #  are not edited.  Leaves produced by neither are enumerated in the
    #  committed zero-policy-frontier set with an issue ref, asserted non-growing (D-24).
    #  owner and mechanic_id are identifiers, not policy — criterion 6 names them.
def validate_rule(rule: BehaviorRule) -> None            # structural only; no imports, no data/ read

#  The interpreters/ -> survival/ contract, declared here because item_behavior.py is the one
#  module both packages may import — a name in a cross-package signature needs a home.
class KernelField(NamedTuple):
    """One value-typed field a build-time interpreter emits for the kernel to consume:
    the compiled form of a rule, carrying no program type and no callable."""
    name: str; value: float | int | bool | str; lane: EngineLane; rule_id: str
@dataclass(frozen=True, slots=True)
class BuildContext:
    """What an interpreter may read at build time: level, the owner's registry entry key,
    and the data_version the memo keys on (D-49).  No walk state, no SurvivalAction."""
    level: int; owner: str; data_version: int

# item_behavior_catalog.py — shapes compiled fresh from the registries
TAG_FAMILY: Mapping[str, RuleFamily]                     # total and single-valued over the 38 tags
_COMPILERS: Mapping[RuleFamily, Compiler]                # module-level defs, keyed by a closed enum
def behavior_rules(owner: str) -> tuple[BehaviorRule, ...]      # fresh, never memoized across data_version
def declared_owners() -> frozenset[str]
def undeclared_owners() -> frozenset[str]                # feeds Counter 3 and review_pending
def validate_catalog() -> None                           # called at import; raises BehaviorCatalogError

# interpreters/__init__.py — one interpreter per family per lane
class Interpreter(Protocol):  FAMILY: RuleFamily;  LANES: frozenset[EngineLane]
    def compile(self, rule: BehaviorRule, ctx: BuildContext) -> tuple[KernelField, ...]
    #  Build-time only.  Walk-lane interpreters emit value-typed fields the kernel already
    #  understands; nothing under survival/ imports this package, source-asserted.
INTERPRETERS: Mapping[tuple[RuleFamily, EngineLane], Interpreter]
def lanes_for(family: RuleFamily) -> frozenset[EngineLane]
def compilability_for(owner: str) -> Compilability
    #  Replaces COMPILED_WALK_UNREPRESENTABLE_ITEMS.  Fold over the owner's rules:
    #  ReceiptOnly wins, reasons concatenated in declaration order; Compilable only if all are.
@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    """D-51's two directions as data: declarations whose marker reaches no interpreter,
    and interpreter branches no declaration reaches.  Empty tuples are the pass condition."""
    unreached_declarations: tuple[str, ...]; orphan_branches: tuple[str, ...]
def reachability_report() -> ReachabilityReport          # author->interpreter and interpreter->author
def validate_registrations() -> None                     # totality, authority agreement, no orphan branch

# item_coverage.py — status computed, not claimed
def item_model_coverage(name: str, needed: frozenset[EngineLane]) -> ItemCoverage
    #  modeled | modeled_state | stats_only | withheld(reason) | review_pending — the last two automatic

# scripts/behavior_frontier.py — the receipt
def scan(root: Path) -> FrontierReport
    #  Counters 1-4 over src/**/*.py by glob, minus the committed exclusions, plus the
    #  Class C/D exclusion sets and the NO_RUNTIME_BEHAVIOR ratchet.  Counters 5-7 are
    #  Phase 4's migration_frontier.py and are not reported here.
def main(argv) -> int                                    # --write refreshes the receipt, --check gates it
```

## Success criteria

Every criterion below holds simultaneously on one commit, with the runbook's eleven-row verification matrix green on that commit.

1. `behavior_frontier --check` reports **Counter 1 = 0** over `src/**/*.py` by glob minus the committed exclusions — not over a fixed module list — and a negative test that adds a name-dispatch site in a new module makes the counter rise. **Counter 2** is at or below the reviewed `NO_RUNTIME_BEHAVIOR` reason count.
2. **Counter 3 = 0**: each `ITEM_EFFECTS` entry and each `ALLY_ITEM_EFFECTS` entry resolves to at least one `BehaviorRule` or an explicit reviewed `NO_RUNTIME_BEHAVIOR`, where that set is committed, set-equality gated, per-member sourced and reasoned, and **non-increasing** from its measured pre-phase size — so the target reads `declared ≥ (registry size) − |NO_RUNTIME_BEHAVIOR|` and cannot be reached by reviewing the backlog into silence.
3. **All 38 tags, all 19 `ActionKind`s, every support producer (derived from `packet_sites`, not typed), every `DefenseSource` construction in `defensive_effects.py` (derived the same way — 25 at HEAD under the counting rule stated in *Vocabulary and closure*), and both the secondary-target and utility paths map into the 18 families** — asserted by the closure tests, which fail on a new tag, a new kind or a new defensive source.
4. **Counter 4 = 0 for `PAIR_ENGINE` and `RECEIPT_WALK`.** Every `COMPILED_SCORE_WALK` gap is a `ReceiptOnly` rule with a named reason and a test that observes the fallback receipt — no gap is silent, and none is a zero.
5. `docs/behavior-frontier.json` is committed, its Class C, Class D and `NO_RUNTIME_BEHAVIOR` sets are diff-gated by set equality, and the counters in it were produced by the script on that commit — it moves **with** the slice that moves a counter, which R-36 permits and R-32 does not reach.
6. No `BehaviorRule` **policy** field is a callable, `dict`, `Any`, or open string — every policy axis resolves to a closed union or a `ValueRef` — asserted reflectively over every field of every compiled rule. The only `str`-typed fields are the identifiers (`owner`, `mechanic_id`), `SourceReceipt`'s three citation fields, and the reason strings on `ReceiptOnly` and `zero_policy`; each is **named in the assertion**, as D-52 requires of the `_COMPILERS`/`INTERPRETERS` exception, so the criterion is never waived on contact.
7. Every non-integral float in every declaration is a `ValueRef`; every integral one is in `_STRUCTURAL_EFFECT_KEYS`; every rule carries a `zero_policy` naming one of the four dispositions, and every `damage_entry`/`simple_damage` carries one through **D-24's ruled exception** — the single declared default (`MEASURED`) at the one construction layer, `champions/slotlib.py` (`:391`, `:600`), overridable per call, so the 384 call sites across 143 champion modules are deliberately **not** edited and no champion sweep is implied; a test asserts the default lives only at that layer. **The exception's guard ships with it**: a source assertion over `champions/` forbids a `.get(key, <literal>)`-shaped fallback from feeding a damage formula — rule 5's no-stale-literal discipline extended to champion inputs — so a zero produced by an unwired stack count or option fails loud instead of being stamped `MEASURED` by the default. The `zero-policy-frontier` set for leaves produced by neither is committed, issue-reffed and asserted non-growing.
8. One rule per family passes the refresh proof: mutate the cached JSON, call the refresh, re-run a fight without re-importing, and the number moves.
9. Every rule resolves a `SourceReceipt`; `defensive_effects.DefenseSource` has zero occurrences in `src/`.
10. The synthetic both-engine acceptance test is green for `delta_amp`, `ally_packet` and `threshold_defense`: a declaration-only item is priced correctly by the pair engine, applied by the receipt walk to other participants and not the holder, either matched or explicitly receipted by the compiled walk, and raises rather than returning zero on the light-tuple path — with a source assertion that no file outside the fixture and `interpreters/` names the synthetic item.
11. Deleting any one of the 18 interpreters flips its items to `withheld` with a named reason and withholds the result — never prices zero. One negative test per family.
12. `validate_catalog()` and `validate_registrations()` raise at import for a declared family with no interpreter, an interpreter branch no declaration reaches, and a rule whose `subject` contradicts its capability's declared `authority`.
13. `COMPILED_WALK_UNREPRESENTABLE_ITEMS` has zero occurrences in `src/`, and the commit that deleted it is preceded by a commit in which the derived `compilability_for` and the legacy set were asserted set-equal.
14. `item_coverage` computes `withheld` and `review_pending` from declarations; the eight derived registries have zero occurrences and the three already-empty ones were asserted empty before deletion; `item_model_coverage`'s new signature is adopted at **all eight `src/` call sites** — `src/app.py:1033, :1081`; `item_coverage.py:609, 689, 712, 717, 739`; `participant_timeline.py:700` — **plus every call site in `tests/test_item_coverage.py`**; `CAPABILITY_SCHEMA_VERSION` bumped in 3.8 **to 3** because the serialized coverage payload changed, and to no other value — the chain and its later owners are D-63's; Phase 1's classification receipt, `coverage_evidence.UTILITY_DIMENSIONS` (now a projection of `UtilityDimension`) and `docs/item-umbrella-audit.json` are re-captured with an enumerated diff and no numeric change.
15. The seven amp chain slots landed one commit each, Hypershot first with zero diffs on both baselines, the Liandry extraction discharged in its own commit before Shadowflame, and Bloodsong carrying a `DivergenceReceipt`; `test_amp_chain_order_is_declared()` pins `AMP_CHAIN_ORDER` against the frozen seven-element tuple.
16. Every `delta_amp` rule declares `ReceiptOnly` with the compiled-kernel reason and the phase's compiled-lane claim reads "declared empty, fallback receipted" — **in both H5 branches**, because scoping H5 adds a later stage rather than relaxing this. The criterion is discharged by the declaration, never by an unstated absence, and this document does not record H5's disposition: the umbrella does.
17. Golden and coupled-golden diffs are zero for every slice **except Shadowflame** — Bloodsong *freezes* its divergence behind a `DivergenceReceipt`, which is zero-diff by definition, and Phase 4 corrects it. Shadowflame carries its own explanation and an oracle receipt for every leaf the runbook's investigator rule qualifies. **Expected qualifying occurrences: 0 for every slice; Shadowflame declares its own count before its baseline is read (R-20).**
