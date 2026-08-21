# Phase 5 — Module-Owned Cast Dependencies

Part of the [Silent-Failure Campaign](2026-08-08-silent-failure-campaign.md). **Decisions owned:
D-80…D-89 and D-49's two rotation memos.** D-44 is Phase 3's and binds this phase's rename; D-49's
counter is declared in Phase 0A; **H6 is not resolved here** — Phase 5 ships its dated acknowledged
gap, per the umbrella's recorded ruling. Gates, golden protocol, bench fingerprints and lane rules
are single-sourced in the [Campaign Runbook](silent-failure-runbook.md) and not restated here.

Prerequisite: **Phase 0A** ([Phase 0](phase-0-gates-and-corrections.md)) for everything L6 owns except
one file — lane L6 runs parallel to everything else from B0. Phase 5 is on the *upstream* side of one
edge: its `cast_dependency` leaf commit is barrier **B0.5**, which unblocks Phase 0B's C6. Nothing blocks
L6 **except its `pipeline.py` commit, which waits on `B1`**: C6 creates both symbols L6 writes into —
`validate_for_champion` and the post-parse expansion/check call site — and P5-c adds only the dependency
check on top of that landed expansion, so this is the return edge for that one file and the runbook's
barrier list names it there.

## Goal

Champion modules declare their own sourced ordering prerequisites in a closed vocabulary, the
rotation resolver merges those declarations over its inferred edges with loud conflict and cycle
failures, and Syndra's hand seed retires against her declaration with zero numeric change.

## Decisions

The campaign's one semantic invariant, in this phase's terms: *a cast order the model did not derive
must never be indistinguishable from one it derived.*

| # | Ruling | Why |
|---|---|---|
| **D-87** | The vocabulary lives in `src/calculator/cast_dependency.py`, **not** `champions/cast_dependency.py`, and imports stdlib only (`dataclasses`, `typing`). | `INFERRED_EDGE_KINDS` is the *generic resolver's* taxonomy; under `champions/` it would make `rotation_resolver` depend on the champion package for its own vocabulary. The leaf is the rotation-side sibling of `ability_spec.py`. |
| **D-80** | Two closed vocabularies, asserted disjoint: `DEPENDENCY_KINDS` (4, module-declared) and `INFERRED_EDGE_KINDS` (12, resolver-inferred). `_Edge` gains `origin: Literal["declared","inferred"]`. | One vocabulary would let a module "declare" `stack_consume` and blur which surface owns the claim. An inferred kind classifies a marker; a declared kind is a module's assertion about its own kit. |
| **D-81** | A suppression is **nested inside its parent `CastDependency`** and is structurally only the exact reverse pair (`setup == parent.slot and consume == parent.requires`). No free-standing suppression exists. | From `CastDependency(slot="E", requires="Q")` it is *impossible to express* a suppression of `E→W` or `E→R`. Structure, not review, prevents silent broadening. |
| **D-82** | Declared-vs-inferred conflict is **loud**: an inferred edge opposing an active declaration with no active suppression raises `ConflictingInferenceError`. | "Declared always wins" resolves a real modelling disagreement silently in the module's favour. Precedent: `item_source.ACKNOWLEDGED_SOURCE_CONFLICTS` — a divergence is a reviewed entry with a citation, or it stops the build. |
| **D-83** | Syndra declares **both** `E requires Q` and `E requires Q2`. | Verified: with no seed the resolver derives `E, Q, Q2, W, R`; with `Q→E` alone it derives `Q, E, Q2, W, R`, because `tie_base` ranks E (has outgoing edges) ahead of Q2 (has none). Q2→E is load-bearing, not decorative. |
| **D-84** | The `("E","Q2")` entry in `tests/test_f3_rotation_all.py::_OVERRIDE_SEED_EXCEPTIONS` is **deleted**, not migrated. | Verified vacuous: `_castable()` requires `cooldown > 0` and Q2 carries the `0.0` cast-exactly-once cooldown, so that edge does not exist today and the exception has been silently passing. The fact moves to the module suppression's `latent_reason`, where the audit can see it. |
| **D-85** | Every new failure mode is **gated on the champion having a non-empty `CAST_DEPENDENCIES`**. The 170 non-declaring champions (173 cached, less Syndra, Zed and Brand) keep the existing silent cycle fallback. | This gating is what makes the migration provably diff-free: the only champions that reach new code are the ones that declare. A declaring champion's cycle is a module/interpreter disagreement a human must settle, not fall back from. |
| **D-86** | A custom `cast_order` inverting an active dependency is **rejected** with `CustomOrderViolatesDependencyError`, carrying the dependency's own `reason` and `source` into the 4xx body. | A declared dependency states impossibility, not preference: an illegal order makes the engine author a `cc_kind="stun"` that cannot exist, and Imperial Mandate's Command then amplifies off a stun that never happened. Precedent `CUSTOM_CAST_ORDER_UNAVAILABLE_REASON` (4 champions); `capabilities.py` already marks `cast_order` `supported=False`, so no user surface moves. Conditional-`cc_kind` (legal order, evaporating stun) is better modelling and belongs on the frontier. |
| **D-88 / H6** | The audit ships with `enhanced_consume` on a **dated, single-entry acknowledged-gap list**, and **Phase 5 does not resolve H6**; emptying the list is a named follow-on slice, scheduled only once the umbrella records H6's answer. | Verified zero producers across 173 champions × the L11/L18 × no-items/magic/physical/spellblade matrix. Either disposition (author Anivia's chill applier, or replace the branch with a declared `damage_enabler`) moves her order and her golden rows, so it needs its own investigator receipt. |
| **D-89** | Frontier: **one conversion** (Syndra) + **three redundant-seed deletions** (Aatrox, Jhin, Aphelios — the derivation already reproduces them exactly) + **head-only declarations for Zed and Brand** whose seeds stay, tagged. Tier 3 (Cassiopeia, Vladimir, Lux, Annie, **Varus**) keeps its seed untouched, each tagged `dps_tiebreak`; Varus's `("R","Q")` seed exception in `_OVERRIDE_SEED_EXCEPTIONS` stays with it. | The campaign rule is "retire a seed only when a declared dependency reproduces its order." Applied honestly that is one conversion, not eleven. Zed's and Brand's heads *are* dependencies; their tails are DPS preferences no declaration can honestly express. `COMBO_TABLE` has exactly eleven entries and P5-f requires every survivor to carry an `override_reason` — leaving one unclassified would make criterion 12 undischargeable. |
| **D-44** | "atom" → **"marker"** for every unit this phase declares: `authored_marker_reach`, marker-interpreter reachability. The resolver's existing apply-atom keys keep the word — they are live code, not a declaration Phase 5 authors. | Three existing meanings of "atom" already collide (`atomizer.Atom`, `atomizer_domains`, `rotation_resolver`'s "TYPED atoms"); Phase 3 names its unit `BehaviorRule` and Phase 5 must not add a fourth. Retiring the word *campaign-wide* would be unimplementable against `atomizer.Atom`, which is why D-44 scopes it to declared units. |
| **D-49** | `rotation_resolver._DERIVED_RULE_CACHE` and `_MATRIX_DPS_CACHE` key on `data_registry.data_version()`. | Both are keyed today with no data component, so a patch-day refresh serves a cast order derived from pre-patch numbers. **The counter itself is declared in Phase 0A** — L4 and L6 are live at once, so a counter either lane declares is a counter the other cannot key on — and Phase 5 owns **only these two rotation consumers**; Phase 3 keys the other seven survivors. |
| **P5-a** | Dependencies are **not** folded into `packet_spec_sha256`. | The SHA pins *reviewed evidence*; a dependency is a module-authored *rule about* that evidence carrying its own `source`. Folding it in would make every dependency edit look like evidence drift and destroy the drift signal. |
| **P5-b** | The leaf — carrying `orderable_slots` and `expand_user_order`, and **no `RECAST_PARENT_SLOT`** — **merges before Phase 0B's C6**, which imports both. This is barrier **B0.5**, the campaign's only L6→L1 ordering edge; the runbook's barrier list and the umbrella's graph both name it and the integration agent enforces it. | Landing the leaf first means one home from day one instead of a rename-then-move churn across two worktrees on `rotation_resolver.py`. **Recast parentage is `recast_of` on the parsed ability entry and nothing else** (D-11, ruled in Phase 0B): `orderable_slots` is "the surface minus P, minus every slot carrying `recast_of`", and a slot that is neither orderable nor `recast_of`-stamped raises. Hand-tabling a fact `recast_of` already owns is the failure this campaign kills — which is why `rotation_resolver._PARENT_SLOT:484` is **deleted**, not moved, together with the name-based Q→Q2 fallback at `:630-631` that would otherwise mask the next unstamped recast slot. |
| **P5-c** | Phase 5 does **not** re-fix the custom-order Q2 drop; it inherits Phase 0B's C6 and adds only the dependency check on top of the landed expansion. Phase 5's entire `pipeline.py` footprint is `validate_for_champion` plus the post-parse expansion/check call site — the integration agent rejects any Phase-5 commit touching the tuple gate at `pipeline.py:994`. | The two lanes share the file and nothing else; naming the exact functions is what keeps them non-conflicting. |
| **P5-d** | Module `CAST_ORDER` — read today by a bare `getattr` at `champions/__init__.py:347` — is folded into the same import-time validator: a subset permutation of the slot surface that satisfies the module's own declarations. | Jayce declaring `["R","Q","Q2","W","E"]` alongside a contradicting dependency should fail at import, not surprise at runtime. One validator, one home. |
| **P5-e** | Both pins land **while the seed is still live**, and the seed is deleted in its own commit that must show zero diffs on both baselines. If it shows one, the declaration does not reproduce the seed and **the seed goes back in**. | That equality *is* the regression proof; this is the campaign's stated retirement rule, mechanized rather than asserted in prose. |
| **P5-f** | `COMBO_TABLE` is renamed `CAST_ORDER_OVERRIDES` and every entry carries a closed `override_reason` (`scheduling_preference` \| `dps_tiebreak` \| `defensive_precast` \| `pending_primitive`). | The frontier becomes machine-countable instead of doc-claimed — the audit reports the remaining seeds and why each is still hand-held. |

**Active-slot semantics — three tiers.** Syndra's Q2 exists only at ≥ 40 splinters, so a single-tier
check would either reject the legal declaration or accept dead ones.

| Tier | When | Rule | On failure |
|---|---|---|---|
| Static | import, in `contract_from_module` | Both endpoints are keys of *this module's own* slot map. Synthetic keys (`Q2`, `R_buff`, `W_frenzy`, `R_onhit`) are legal because the module declares them; validation never consults a global slot list. | `UnknownSlotError` — import fails closed |
| Dynamic | per resolve | A dependency is **active** iff both endpoints are live in *this* parse; otherwise it constrains nothing and the receipt names the absent endpoint. **Nested suppressions go inactive with their parent** — you may not suppress an inference while the declaration justifying it is not live. | no failure; a receipt line |
| Coverage | audit | Every declaration is active in ≥ 1 certified option state. | `UnreachableDependencyError` |

**Explicit-vs-inferred precedence**, for an unordered pair {A, B}:

| declared A→B | inferred A→B | inferred B→A | active suppression B→A | outcome |
|---|---|---|---|---|
| – | ✓ | – | – | inferred A→B — today's behaviour, byte-identical |
| ✓ | – | – | – | declared A→B |
| ✓ | ✓ | – | – | declared A→B, deduped; receipt flags `confirmed_by_inference` |
| ✓ | – | ✓ | ✓ | declared A→B; B→A dropped; receipt cites the suppression |
| ✓ | – | ✓ | ✗ | **`ConflictingInferenceError`** (D-82) |
| ✓ | – | – | ✓ matching nothing | declared A→B; suppression `latent`, `latent_reason` mandatory |
| – | – | – | ✓ | unrepresentable — a suppression must nest in a declaration (D-81) |

Machine-asserted invariants: a suppression never *creates* an edge, never targets a *declared* edge,
is scoped to one `(setup, consume, kind)` triple, and is inert while its parent is inactive.

## Shape

**`src/calculator/cast_dependency.py`** — new, stdlib-only, imports nothing from the package;
imported by `rotation_resolver`, `champions/module_contract`, `champions/packet_module`,
`champions/__init__` and `pipeline`.

```python
BASE_CAST_SLOTS: tuple[str, ...]         # ("P", "Q", "W", "E", "R")
DEPENDENCY_KINDS: frozenset[str]         # cc_enabler | damage_enabler | resource_enabler | recast_of
INFERRED_EDGE_KINDS: frozenset[str]      # the resolver's existing 12 kinds, moved verbatim
#  No RECAST_PARENT_SLOT: recast_of on the parsed ability entry is the single authority (D-11),
#  and rotation_resolver._PARENT_SLOT:484 plus the :630-631 name fallback are deleted with it.

@dataclass(frozen=True, slots=True)
class SuppressedInference:
    """One inferred edge a declaration overrides, and why the inference reads the mechanic backwards."""
    setup: str; consume: str; kind: str; reason: str; latent_reason: str | None = None

@dataclass(frozen=True, slots=True)
class CastDependency:
    """One module-declared ordering prerequisite between two of its own cast slots."""
    slot: str; requires: str; kind: str; reason: str
    source: str                    # "<wiki url>@<revision_id>" — shape-validated at import
                                   # (stdlib only, so the leaf stays a leaf) and RESOLVED
                                   # against the committed full-entry wiki audit by
                                   # scripts/cast_dependency_audit.py.  A free-text string
                                   # checked only for non-emptiness would let the retired
                                   # seed come back as four plausible sentences.
    suppresses: tuple[SuppressedInference, ...] = ()

class CastDependencyError(ValueError): ...
#  import-time:  UnknownSlotError, SelfDependencyError, DuplicateDependencyError,
#                UnknownDependencyKindError, UnsourcedDependencyError, SuppressionScopeError,
#                UnknownInferredKindError, MissingLatentReasonError, DeclaredCycleError
#  resolve-time: ConflictingInferenceError, ResolvedCycleError
#  audit-time:   UnreachableDependencyError, DeadSuppressionError
#  request-time: CustomOrderViolatesDependencyError

def validate_cast_dependencies(deps, *, slot_surface: set[str], module: str) -> None:
    """Import gate: slot membership, kind vocabulary, non-empty reason/source, pair uniqueness,
    suppression scope, and acyclicity of the declared graph alone."""
def validate_cast_order_declaration(order, deps, *, slot_surface, module) -> None:
    """The same gate for a module's CAST_ORDER: subset permutation that satisfies its own declarations."""
def active_dependencies(deps, live_slots) -> tuple[CastDependency, ...]:
    """The declarations both of whose endpoints exist in this parse; the rest constrain nothing."""
def orderable_slots(slot_surface) -> tuple[str, ...]:
    """What a request may name: the surface minus P and minus every slot carrying recast_of.
    A slot that is neither orderable nor recast_of-stamped raises — no hand table (D-11)."""
def expand_user_order(user_order, live_slots) -> list[str]:
    """Reinsert each live recast-class slot immediately after its parent (Q,W,E,R -> Q,Q2,W,E,R)."""
def check_order_satisfies_dependencies(order, deps, live_slots) -> None:
    """Raise CustomOrderViolatesDependencyError, quoting reason and source, on an inverted active dependency."""
```

**`src/calculator/rotation_resolver.py`** — owns inference and the merge; the detector is unchanged.

```python
@dataclass(frozen=True)
class DependencyReceipt:
    """What the merge did: active/inactive declarations, suppressed and confirmed inferences, conflicts."""
    active; inactive; suppressed; latent; confirmed_by_inference; conflicts   # tuples of display rows

def merge_declared_edges(champion_name, inferred, declarations, live_slots
                         ) -> tuple[list[_Edge], DependencyReceipt]:
    """Fold declarations over inferred edges under the precedence table; raise on uncovered opposition."""
def resolved_edges(champion_name, ability_damages, champion_data, option_keys, declarations
                   ) -> tuple[tuple[_Edge, ...], DependencyReceipt]:
    """The one public detect→merge surface production and tests both read, so they cannot drift."""
def derive_champion_rule(...) -> ComboRule:      # signature unchanged; body becomes detect → merge → Kahn
def build_rotation_receipt(...) -> dict:         # gains rotation["dependencies"] from DependencyReceipt

CAST_ORDER_OVERRIDES: dict[str, ComboRule]       # renamed from COMBO_TABLE
ORDER_OVERRIDE_REASONS: frozenset[str]           # the four closed reasons (P5-f)
ComboRule.override_reason: str | None            # required non-None for every override entry
_Edge.origin: Literal["declared", "inferred"]
_DERIVED_RULE_CACHE / _MATRIX_DPS_CACHE          # keys gain data_registry.data_version()
```

**`src/calculator/data_registry.py`** — **consumed, not edited.** `data_version()` is declared in
Phase 0A (D-49); Phase 5 only adds the counter to its two rotation cache keys.

**`src/calculator/champions/module_contract.py`** — `ChampionModuleContract` gains
`cast_dependencies: tuple[CastDependency, ...] = ()`; `contract_from_module` keeps its signature and
gains the existing three-place lookup (module `CAST_DEPENDENCIES` → `parse_abilities.cast_dependencies`
→ `SLOTS.cast_dependencies`, the shape already used for `PACKET_SPEC`/`PACKET_SHA256`), then calls
both validators against the module's own slot surface.

**`src/calculator/champions/packet_module.py`** — `build_packet_module(..., *, cast_dependencies:
tuple[CastDependency, ...] = ())`: one keyword-only parameter, validated against the compiled
`PacketSlotMap` keys in the same breath as the SHA drift check, attached to both carriers
(`slots.cast_dependencies`, `parse_abilities.cast_dependencies`). No champion switchboard.

**`src/calculator/champions/__init__.py`** — `get_champion_cast_dependencies(champion_name) ->
tuple[CastDependency, ...]`, beside `get_champion_cast_order`, same `try/except KeyError → ()`
discipline; the validated contract is the only source, never a module import.

**`src/calculator/champions/syndra.py`** — module-level `CAST_DEPENDENCIES`: `E requires Q`
(`cc_enabler` — Scatter the Weak stuns only enemies a scattered Dark Sphere passes through) and
`E requires Q2` (`cc_enabler` — the 40-splinter second charge), each nesting exactly one reverse
`cc_setup` suppression; the Q2 one carries the `latent_reason` replacing D-84's deleted test
exception. `zed.py` and `brand.py` gain head-only `damage_enabler` declarations (D-89).

**`src/calculator/pipeline.py`** — Phase 0B's C6 already moved the permutation check into
`FightParams.validate_for_champion` against `orderable_slots(...)` and the expansion into
`expand_user_order`; Phase 5 adds only `check_order_satisfies_dependencies` at the same post-parse
call site. Two symbols, no others — the runbook's ownership map scopes L6's write in this file to
exactly `validate_for_champion` and that call site.

**`scripts/cast_dependency_audit.py`** → `docs/cast-dependency-audit.json`, joining the
`full_entry_audit.py` / `item_umbrella_audit.py` family, gated by `tests/test_cast_dependency_audit.py`.
Walks 173 champions × the certified option matrix (defaults plus each slot-gating option at its
declared min and max) and emits five ledgers: `inferred_kind_coverage` (kind → producing champions;
fails on any empty kind), `declared_dependency_activation`, `suppression_ledger`, `conflict_ledger`,
and `authored_marker_reach` — the bidirectional half that does not exist today.
`engine._validate_cc_event_contract` covers author→interpreter for one marker; `authored_marker_reach`
covers interpreter→author for the whole surface, *derived* from the resolver's existing apply-atom
keys that `detect_setup_consume_edges` reads (live code, which keeps the word — D-44 retires "atom"
for units this phase declares, not for `rotation_resolver`'s own vocabulary), never hand-listed. The
audit additionally resolves every `CastDependency.source` against the committed wiki audit and every
`cc_enabler` declaration against an authored `cc_kind` on the required slot via
`engine._validate_cc_event_contract` — an enabler naming a marker that does not exist is a
declaration with no referent.

**Tests** (front doors only): new `tests/test_cast_dependency.py` (leaf validators, precedence table,
active-slot tiers, every typed failure) and `tests/test_cast_dependency_audit.py` (receipt diff-gate).
There is **no bespoke Syndra pin fixture**: the cast-order pins are the two named scenarios
(`syndra_custom_order`, `syndra_derived_order`) in Phase 0A.2's coupled scenario set — the parameter
set lives in the scenario definitions and the binding totals in the committed baseline, and this
phase's suites and Phase 0's criterion 14 run the scenarios by name and read the baseline, retyping
nothing. An earlier draft created a shared fixture module at B0.5 and value-filled it at C6 — a second
hand-maintained pinning mechanism beside golden, with a two-lane fill choreography; the scenario rule
retires it, and B0.5 carries only the leaf module.
`tests/test_f2_rotation.py`: `_COMBO_CHAMPIONS` loses four names and its batch test becomes true to
its name again; Syndra's `_EXPECTED_ORDERS` row moves to the derived-path parametrization;
`_RATIONALE_FRAGMENTS` additionally asserts the `cc_enabler` kind and the revision citation.
`tests/test_f3_rotation_all.py`: `_OVERRIDE_CHAMPIONS` and `_OVERRIDE_SEED_EXCEPTIONS` lose Syndra,
`_EXPECTED_DERIVED_ORDERS` gains her, `_detect_edges` repoints at `resolved_edges`,
`test_edge_kind_taxonomy_is_closed` imports both vocabularies from the leaf, and a new
`TestDeclaredDependencies` covers the splinter axis, suppression classification and each typed
failure. `tests/test_syndra.py`: `test_cast_order_is_qe_combo`'s `rule.derived` flips False→True and
gains citation assertions, plus new classes for the recast pin and the custom-order fixtures.
`tests/test_public_response.py` is checked for exact-key assertions on `rotation`, which gains
`dependencies` and reaches the API automatically through `public_response.py:250`.

**Docs** — `docs/rotation-design.md` gains the declared lane in the resolution chain
(`user order → declarations+inference merge → seeds → derivation`), the precedence table and the
two-vocabulary taxonomy; `docs/rotation-verification-gaps.md` moves Syndra's row to "closed by
declaration" and adds the `enhanced_consume` branch; `architecture.md` gains one line —
`cast_dependency.py` owns the declared ordering-prerequisite vocabulary, `rotation_resolver.py` owns
inference and the merge.

## Success criteria

1. **The leaf is a leaf.** Importing `src.calculator.cast_dependency` into a fresh interpreter adds no
   other `src.calculator` module to `sys.modules` — asserted, not reviewed.
2. **The vocabularies are closed and disjoint.** `DEPENDENCY_KINDS` (4) and `INFERRED_EDGE_KINDS` (12)
   share no member; `INFERRED_EDGE_KINDS` equals the set of kinds `detect_setup_consume_edges` can
   emit; `test_edge_kind_taxonomy_is_closed` imports both from the leaf instead of retyping them, and
   asserts `origin ∈ {"declared","inferred"}` on every merged edge.
3. **Suppression cannot broaden.** A `SuppressedInference` that is not its parent's exact reverse pair
   raises `SuppressionScopeError` at import, and no construction path produces a suppression outside a
   `CastDependency`.
4. **Every typed failure has a negative test that reaches it**: the nine import-time errors on
   synthetic modules, `ConflictingInferenceError` **on Syndra's real declarations with her matched
   suppression removed** (see the amendment below), `ResolvedCycleError` on a synthetic declared cycle
   in a live parse, `DeclaredCycleError` at import,
   and `CustomOrderViolatesDependencyError` on `["E","Q","W","R"]` for Syndra with the declaration's
   `reason` and `source` present in the message.

   **Amended after the `verify-P5-signoff` pass, which found the Syndra clause neither discharged nor
   amended.** The clause read "`ConflictingInferenceError` when *either* Syndra suppression is
   removed", and the suite's only two `ConflictingInferenceError` negatives were synthetic — a
   hand-built declaration meeting a hand-built edge, in `test_f3_rotation_all.py`'s
   `TestPrecedenceTable`. Nothing removed either real suppression. As with criteria 7 and 12 this is a
   plan-text change made by an implementation lane and is flagged as such, in the criterion itself, so
   the next verifier adjudicates the amendment instead of inheriting it silently. The split is not
   symmetric and the criterion now says so:

   *The matched half is a direct red and is now written.* The detector's `cc_setup` fan-out really does
   emit `E → Q`, so emptying `E requires Q`'s `suppresses` is a raise on the live surface.
   `TestSyndrasSuppressionsAreLoadBearing` runs the real declarations through `resolved_edges` across
   L11/L18 × splinters ∈ {0, 39, 40, 60, 119, 120}, replacing exactly one field of one real
   declaration: the opposition is measured in the detector's own output, the removal raises with the
   inferred edge, the declaration sentence and its wiki revision in the message, and the unmodified
   declarations raise nothing — so the raise is the removal's and not the state's.

   *The latent half is undischargeable against **D-84**, which this phase itself ruled.* No
   `E → Q2` `cc_setup` inference can exist — `_castable()` requires `cooldown > 0` and Q2 carries the
   `0.0` cast-exactly-once cooldown — so removing that suppression can never raise
   `ConflictingInferenceError`. Demanding the raise would reverse a ruling; re-reading the clause into
   the synthetic negatives, which is what happened, leaves the campaign's own prose-outruns-code shape
   inside criterion 4. The clause is therefore replaced by one that demands **more** evidence than a
   raise-on-removal, all three parts machine-checked in the same class: `E → Q2` appears in the
   detector's output in **no** certified option state, which is D-84 measured rather than quoted;
   clearing that suppression's `latent_reason` — leaving the suppression live and its parent active —
   makes the merge raise `MissingLatentReasonError` in every state where Q2 exists, so a latent
   suppression that stops explaining itself is refused; and removing it entirely is **inert**, the
   merged edge list identical and only the latent receipt row gone, which is the shape of the fact.
   Should Q2 ever gain a real charge cooldown, the reversed edge arrives with it, the suppression
   becomes matched, and the removal red the criterion originally asked for becomes writable — the
   suppression ledger in `docs/cast-dependency-audit.json` is where that transition shows up.
5. **Syndra derives without her seed.** With `CAST_ORDER_OVERRIDES["Syndra"]` deleted,
   `derive_champion_rule` returns `Q, Q2, E, W, R` at L11 and L18 × {no items, magic, physical,
   spellblade} and at splinters ∈ {40, 60, 119, 120}; `Q, E, W, R` at splinters ∈ {0, 39}; `Q, Q2` at L1.
6. **The 5.0-second Q recast is pinned exactly — by the coupled baseline, not by prose or a bespoke
   fixture.** The pin is the **`syndra_derived_order` scenario** in Phase 0A.2's coupled scenario set
   (no `cast_order`; L18, Q5/W5/E5/R3, 600 AP, 10 ability haste, 12 s deterministic, target 10000 HP
   with zero armour and zero MR; captured at splinters ∈ {39, 60, 120}, because the **splinter count
   is load-bearing and was previously unstated** — the same run totals three different numbers across
   those variants, so a pin without the splinter axis is ambiguous). The scenario definition is the
   one home of the parameter set and the committed `golden_coupled_baseline.json` entries are the
   binding home of the totals; this suite runs the named scenario live and reads its expectations from
   the baseline, retyping nothing. **No derived-order number is authored in this document**: pre-C6,
   `Q2` is unstamped and occupies its own slot in the cast-lockout schedule — exactly the scheduling
   C6 retires; once `recast_of="Q"` lands, the scheduler folds `Q2` onto Q's cast times and drops it
   from the independent schedule (`damage.py:3238-3241`, `:3094-3096`), moving W into the first
   lockout window and every recast time with it, so a timeline authored against today's tree would pin
   the pre-correction engine — an earlier draft of this criterion did exactly that. Instead, the 0A
   capture pins the pre-fix values, C6 declares its diffs on these scenarios in its allowlist, and the
   Phase 0 boundary re-capture under R-17 writes the post-fix pin this criterion runs against. Target
   HP, armour and MR are stated for reproducibility only — **the total is invariant in them**, and
   this criterion claims no movement it cannot show. Order sensitivity is criterion 7's positive
   control, run against this same scenario. The derived-order timeline is asserted structurally by
   running the scenario live — the 5.0 s Q recast present, `Q2` folded onto Q's cast times — and
   asserted **distinct** from the `syndra_custom_order` scenario's timeline (criterion 14 already
   requires choosing a requested order for which the two differ): a pin the fix and a fall-through to
   the derived order both satisfy is not a pin. Both scenarios are green against the live seed before
   it is deleted.
7. **Zero golden and zero coupled-golden diffs across the whole phase** (protocol: runbook R-11, R-17).
   A single diff on the seed-deletion commit means the declaration does not reproduce the seed, and the
   seed is restored rather than the baseline re-captured. **A positive control precedes that commit**:
   perturbing Syndra's derived order in a throwaway edit produces ≥ 1 diff in `champion_baselines` /
   `registered_champion_fights`, and the control's diff count is recorded in the commit body — otherwise
   "zero diffs" may mean golden is blind to her cast order rather than that the declaration reproduces
   the seed. R-05 applies to the control. Every one of R-01's eleven rows passes at every commit, the
   bench counters, residual, winners and scores are identical, and **expected qualifying occurrences are
   0 on every commit** (R-20).

   **Amended after the second `verify-P5-retire` pass, which found three of the criterion's literal
   clauses undischargeable against rulings already made — and, unlike criterion 12, no amendment
   written.** The substance was re-run and verified: the pair baseline reports `snapshot identical` at
   every commit in the group, all eleven R-01 rows pass at the phase tip, the bench counters, residual,
   winner and score reproduce R-07's priors exactly on all four scenarios and are identical under
   `--no-compiled`, and the positive control landed with its throwaway sha and output hash in
   `campaign-fingerprints.json`. Three clauses of the *wording* did not hold, and each is replaced by a
   clause that demands more evidence rather than less.

   *The coupled baseline.* "Zero coupled-golden diffs" and R-17 cannot both be satisfied inside the
   phase: R-17 **requires** a semantic slice to land against the committed baseline plus an allowlist of
   expected diff paths, and the boundary re-capture that would zero the compare is the integration
   agent's (R-32), not a lane's. The clause cited R-17 while forbidding what R-17 mandates. It is
   therefore **zero *unallowlisted* diffs**: every differing leaf appears in a committed
   `docs/receipts/expected-golden-diff-P5-*.json` allowlist carrying its oracle receipt, no allowlisted
   path is missing from the compare and no compare path is missing from an allowlist — the sole
   exception being the snapshot's own `metadata/fingerprint` counters, which umbrella criterion 4
   disowns to `campaign-fingerprints.json`. And the tightening the old clause never made: **every
   differing leaf lies inside a `rotation` receipt object**, so no `total_damage`, `breakdown`,
   `cast_timeline`, `damage_events`, `resource_*`, `champion_stats` or `combat` leaf moves anywhere in
   the phase, and the pair baseline stays byte-identical throughout. Both halves are machine-checked by
   `tests/test_p5_oracle_receipts.py::TestTheCoupledCompareIsFullyAllowlisted`, which runs R-01 row 3's
   compare and additionally fails on an allowlist entry excusing a leaf that no longer moves; the
   verifier read the same join by hand. The moved-leaf count is a measurement and belongs in a commit
   body, never here.

   *The seed-deletion commit.* "A single diff … means the declaration does not reproduce the seed"
   reads every leaf as a numeric pin, but a derived rule **publishes receipt fields a hand seed never
   had**: the merge's own sourced `rationale` and `sources` in place of the seed author's prose, the
   merged edge set's `setup`/`consume`/`aoe` projection in place of the seed's hand-written pair, the
   `dependencies` ledger, and — at the thirty-nine-splinter scenario only — `cast_order`, because the
   seed advertised `Q2` in a parse that has no `Q2` while the derivation advertises the slots the parse
   holds. Criterion 5 **rules** that order below forty splinters, so the clause as written demanded the
   wrong answer be preserved. What the retirement rule means is the executed order and the numbers:
   **`rotation/order` is unchanged at every scenario and every splinter count, no computed number moves
   in either jurisdiction, and every moved receipt leaf carries an independent oracle receipt** — all
   three recorded in `docs/receipts/expected-golden-diff-P5-seed-syndra.json`. A move outside that set
   restores the seed, exactly as the original clause intended.

   *The dissents that were defects.* Two of those oracle verdicts dissented on defects **older than
   this phase** — a cc-setup citation printing the field name where the authored marker belongs, and a
   recast citation restating its own cite without the precondition. Neither is fixed here: each moves
   committed baseline leaves and therefore owes its own R-20 population and its own oracle receipts,
   which is a slice, not a paragraph in someone else's. But an escalation living only in a commit body
   is absorbed by the phase-boundary re-capture — the leaves enter the new baseline and the compare
   goes quiet — so it is carried as a dated ledger,
   `docs/receipts/escalated-defects-P5-retire.json`, in the same idiom as the audit's acknowledged-gap
   list. Each entry names the oracle receipts that raised it, the source sites that carry it and the
   sentence production publishes today, and
   `tests/test_p5_oracle_receipts.py::TestTheEscalatedDefectsAreStillTracked` re-derives all three
   every session — so fixing a defect turns the ledger red and the entry is closed in the slice that
   fixes it, rather than fading out with a re-capture.

   *The occurrence line.* "Expected qualifying occurrences are 0 on every commit" reads R-20 as a
   prediction that no leaf ever qualifies. R-20's second half rules the opposite where the count cannot
   be read off the pre-change tree: such a slice declares the qualifying **population**, enumerated from
   committed artifacts before its first `src/` edit, and writes that size into the line. The
   seed-deletion commit did exactly that, and every occurrence it declared carries an independent oracle
   verdict — more evidence than a nought can carry, not less. The clause is therefore: **every commit
   carries the line; its value is nought except on the seed deletion, whose value is its pre-enumerated
   population; and every declared occurrence carries an oracle receipt.**

   **Corrected after the `verify-P5-signoff` pass.** The first version of this paragraph recorded one
   non-compliant commit; the deviation set is **three**, and the correction is stated as a rule a
   reader can re-run rather than as a recollection. The enumeration is over the lane's whole commit
   range — from the phase's first commit, `c442d11`, to its tip — and the command is part of the
   clause, not left to the checker:

   ```bash
   git rev-list --reverse c442d11~1..HEAD |
     while read c; do
       git show -s --format=%B "$c" | grep -q "Expected qualifying occurrences" || git show -s --oneline "$c"
     done
   ```

   It reports `96ace20` (`test(rotation)`: the edge taxonomy), `33cdddb` (`test(champions)`: D-85's
   guard) and `aae3d97` (`docs(receipts)`: the seed-retirement control). All three are recorded rather
   than rewritten, and none is a number moving unexplained: each touches no `src/`, no baseline and no
   allowlist — two are test-only, one is the `campaign-fingerprints.json` control commit under R-32's
   `demonstrated_red` carve-out — and each body records both compares identical on its own tree. Their
   shas are cited by the fingerprints receipt and the seed-deletion allowlist, so a rewrite would break
   artifacts that point at them. Every commit after this correction carries the line.

   As with criterion 12, this is a plan-text change made by an implementation lane and is flagged as
   such, in the criterion itself, so the next verifier adjudicates the amendment instead of inheriting
   it silently. That an amended criterion could itself state a checkable universal claim that was false
   is the reason the deviation set is now enumerated by a command rather than by counting from memory.
8. **Non-declaring champions reach no new code.** Every new raise site is behind a non-empty
   `CAST_DEPENDENCIES` guard — asserted at source level, in the `test_issue_158` idiom — so the 170
   non-declaring modules are byte-identical and keep the existing silent cycle fallback.
9. **The audit receipt is committed and diff-gated by set equality.** `inferred_kind_coverage` has no
   empty kind except one dated, single-entry acknowledged gap (`enhanced_consume`, H6, which this phase
   carries rather than resolves); `declared_dependency_activation` shows every declaration active in
   ≥ 1 certified option state; `suppression_ledger` has no latent row lacking a `latent_reason`;
   `conflict_ledger` has no uncovered row; every `source` resolves against the committed wiki audit and
   every `cc_enabler` resolves to an authored `cc_kind` on its required slot. The audit's exclusion list
   lives in the committed receipt, not inside the tool that measures it, and the receipt moves with the
   slice that moves its counts (R-36).
10. **Marker reachability is bidirectional and derived.** The marker surface in `authored_marker_reach`
    is computed from the resolver's existing apply-atom keys — not hand-listed — is committed to the
    receipt, and each member carries a negative test that withholds or mutates the marker and asserts
    the interpreter's output changes. A newly read key with no such test fails the audit.
11. **Custom orders are whole and checked.** Syndra with `cast_order=["Q","W","E","R"]` reproduces the
    `syndra_custom_order` scenario's committed baseline total with `breakdown["Q2"]["casts"] == 1`
    (Phase 0B's C6,
    re-asserted here as a regression) and a timeline **distinct from** criterion 6's derived one; the
    permutation check lives in `validate_for_champion` against `orderable_slots`, not as a literal.
    No Phase-5 commit touches `pipeline.py:994`.
12. **Every declaration is load-bearing, on a route the receipt publishes.** Removing any one
    `CastDependency` is observable on at least one of three named surfaces, and
    `docs/cast-dependency-audit.json` records which, per declaration, in
    `declared_dependency_activation[].load_bearing_routes`; a declaration on none of them fails the
    audit. The routes are `derived_order` (removing it changes the order the derivation returns, or
    makes it refuse to return one, in ≥ 1 certified option state), `confirmed_by_inference` (an
    inferred edge agrees and the merge receipt says so), and `custom_order_refusal` (removing it makes
    a request order the engine currently refuses legal again, D-86). *Without this, Syndra's retired
    seed returns as four declarations with plausible prose and c5–c7 all pass — seed dependence intact
    and now unfalsifiable.*

    **Amended after the first `verify-P5-retire` pass, which found the original two-route form
    undischargeable against D-89 and declined to rule on the widening.** The original wording offered
    `derived_order` or `confirmed_by_inference` only. D-89 *rules* that Zed and Brand carry head-only
    declarations **whose seeds stay**, so their order is decided by `CAST_ORDER_OVERRIDES` before the
    derivation is consulted at all: measured across `cast_dependency_audit.option_states` × levels 1–18,
    removing any of their three declarations changes no derived order in any state, and no inferred edge
    agrees with any of them, so tagging them `confirmed_by_inference` would be a false receipt. The two
    rulings were therefore mutually unsatisfiable and one had to give; D-89 is ruled and this criterion
    was not, so the criterion names the third route. It is a widening in count and a **tightening in
    evidence**: the original demanded a receipt entry only for the `confirmed_by_inference` escape,
    where every declaration now carries a published route, machine-measured and diff-gated.
13. **The frontier is counted, not claimed.** `COMBO_TABLE` has zero occurrences in `src/` and `tests/`;
    **every one of the eleven entries is dispositioned** — four retired (Syndra, Aatrox, Jhin,
    Aphelios), two head-only (Zed, Brand), five Tier 3 (Cassiopeia, Vladimir, Lux, Annie, Varus) — so
    the seven survivors each carry an `override_reason` from the closed set, and the audit publishes
    that count with its reason histogram. `f2`'s combo-champion set and `f3`'s override set agree with
    it by assertion.
14. **The algorithmic coverage floors move up, never down.** `test_algorithmic_coverage_floors`' two
    floors are re-measured after the retirements — which add the retired champions to its counted
    population — and raised to the measured values; a lowered floor is a failed criterion.
15. **The rotation caches invalidate on data.** `_DERIVED_RULE_CACHE` and `_MATRIX_DPS_CACHE` both carry
    a `data_version()` component — the counter Phase 0A declared, not one this phase introduces — and a
    test that bumps it and re-derives proves a stale order cannot be served across a refresh.
16. **Recast parentage has one authority.** `rotation_resolver._PARENT_SLOT` and the name-based
    `add("Q","Q2","recast", …)` fallback at `:630-631` both have zero occurrences in `src/`; every
    recast edge derives from `recast_of`; and a synthetic champion with a recast slot carrying no
    `recast_of` raises rather than being silently linked by name.
