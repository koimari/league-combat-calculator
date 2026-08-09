# Silent-Failure Campaign — Umbrella Contract (rev 2)

*Rev 2 supersedes rev 1 in place. Rev 1 bound five phase end states from one incident; rev 2 adds the
decision table that makes those end states implementable without re-litigation, retires every claim the
planning workflow could not reproduce, and moves all shared protocol into the
[campaign runbook](silent-failure-runbook.md). Prepared against `1274615` on `command-amp-and-gnar-mega`.*

## Goal

A calculator in which every numeric leaf is either a value some rule computed or a named refusal to
compute one — never a zero standing in for a rule that did not run — with that distinction enforced by
machine at load, at every `pytest` run, and at every gate.

## Decisions

### Why this campaign exists

Imperial Mandate's Command (+7% damage taken after an immobilize) priced **zero** for Syndra, and six
layers failed independently without a single error:

1. **Marker never authored** — `champions/syndra.py` treated all CC as utility; E carried no `cc_kind`.
2. **Marker dropped in transit** — `champions/pantheon.py` W authored `cc_kind="stun"`, but without
   `event_order_certified` the emission gate in `damage.py::_evaluate_cast_parts` never exported it.
3. **Consumer half missing** — the walk's owner-skip in `survival/transitions.py` documented that "the
   holder's pair engine already prices its own amp." That pair-engine side did not exist.
4. **Coverage claimed anyway** — `item_coverage._STATEFUL_MODELED_ITEMS` said in prose that both halves of
   Command existed. Nothing checked the prose against code. (The Imperial Mandate entry at
   `item_coverage.py:52-58` has since been reworded; the sibling Bandlepipes entry at `:47-51` still
   carries the original "represented by the shared participant support ledger" shape.)
5. **Predicate divergence** — "is this an immobilize?" existed as three literal sets; one let slows
   trigger Command.
6. **Tag → collateral reorder** — authoring the stun re-ordered the rotation resolver's generic cc-setup
   fan-out, costing a Q recast at the 5.0 s window in builds holding no Mandate at all.

Shipped as the incident fix and *not* re-done here: `cc_kind` on `damage_entry`/`simple_damage`,
`_validate_cc_event_contract`, `IMMOBILIZING_CC_KINDS` / `CC_KIND_VOCABULARY` / `is_immobilizing_event`,
`_apply_command_amp` + the walk `owner` handshake, and Syndra's rotation seed. The campaign generalizes
them. The one prose sentence at `participant_timeline.py:2611` that described a property later deleted is
the incident in miniature and the reason every claim below must resolve against code.

### The one invariant

Every phase document quotes this verbatim.

> **A number the model did not compute must never be indistinguishable from a number the model computed
> as zero.** Every numeric leaf is exactly one of four dispositions.

| Disposition | Meaning | Enforcement |
|---|---|---|
| `MEASURED` | A rule ran against adequate inputs and produced this value, zero included. | Traceable to an executed rule in the outcome ledger. |
| `STRUCTURAL_ZERO` | A declaration says the mechanic does not apply here; zero is the answer and the declaration is the receipt. | `zero_policy=STRUCTURAL_ZERO` with a reason (D-24). |
| `WITHHELD` | Coverage refused to model it. A named receipt and **no number**. | Status-derived eligibility plus a registered withholding prefix (D-23). |
| `STARVED` | A projection could not answer the question a rule asked. A programming error. | `ProjectionStarvation` raised on first read; caught at exactly one boundary (D-25). |
| *(propagation)* | An aggregate over a set containing a `WITHHELD` or `STARVED` member is itself `WITHHELD`, naming its withheld members. `STRUCTURAL_ZERO` contributes 0.0; `MEASURED` aggregates only over `MEASURED` and `STRUCTURAL_ZERO`. | **`Quantity.__add__` (D-72)** — propagation is arithmetic on the value type, not a tested behaviour; Phase 4 c19 unit-tests the full member matrix and keeps one end-to-end roster fixture as the backstop. *Why: a total is also a leaf, and the natural implementation contributes 0.0 for a withheld member — the incident re-created at the aggregate. With the algebra, that failure is unrepresentable rather than merely tested-for.* |

These four spellings are the campaign's vocabulary: wherever a phase needs a symbol, a receipt string or a
reason prefix for one of these states, it uses this exact word. *Why: the Mandate bug is a `STARVED` case
rendered as a `MEASURED` zero, and one shared spelling is what makes that conversion greppable.* The word is
not enough on its own — the `disposition` field, its home and its gate are in *Shared names* below, and
success criterion 1 is discharged through that field, never by an offline audit over a hand-maintained path
list.

### Semantic authority — which engine owns a mechanic

> Authority belongs to the smallest engine that can see **every input the mechanic's rule reads**.
> All-pair-local inputs ⇒ `PAIR_ONLY`. Any roster input — another participant's damage, another holder's
> stacks, the subject's live HP under combined fire, the set of enemies one cast hit — ⇒
> coupled-authoritative. **`SPLIT` is legal only when the pair-local restriction of the rule is exactly
> the holder's own contribution, the two halves are provably disjoint, and the owner skip is
> machine-checked.** A coupled-authoritative declaration is honest only if it carries a `Compilability`
> that forces the fallback rung until the compiled kernel can represent it.

| Mechanic | Ruling | Binding obligation | Phase |
|---|---|---|---|
| `abyssal_mask.unmake` | `SPLIT` | Pair keeps `magic_amp` (golden pins it); 0B declares `owner`, `damage_classes={magic}`, `attack_classes`=all three and `AURA_ARM`. `HolderStacking.IDEMPOTENT_AURA` — the declaration that makes its dedupe key `(subject, mechanic_id)` (D-66) — lands with the field itself, which Phase 4 introduces; `MechanicCapability` does not exist at 0B | 0B, then 4 |
| `dream_maker.blue_bubble` | `COUPLED_ONLY` — **settled in 0B** | Verified: no pair-engine pricer for Blue Dream Bubble exists in `src/`, so it declares no `owner`; `next_event_only` needs the `Consumption` axis, expressible in no contract as written | 0B declares, 3 models |
| `imperial_mandate.command` | `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` | The pool is roster-wide; summed across N pair ledgers the pair number claims every defender was stunned. `_apply_command_amp` stays, tagged `THEORETICAL` — and D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` rule is what keeps the surviving preview from becoming a second applied contribution. `HolderStacking` is H2-blocked and fails closed to `PER_HOLDER`, so a second Mandate holder is priced, not deduped away. Blocked on H2 | 4 |
| `bloodsong.expose_weakness` | Freeze the divergence behind a `DivergenceReceipt`, then `COUPLED_AUTHORITATIVE` | Pair and walk are not numerically equivalent; never unify inside a slice labelled a pure refactor | 3 freezes, 4 corrects |
| `black_cleaver.carve` | `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` — **H1** | The stack ledger is a roster fact; the Cesàro approximation stays pair-side as `THEORETICAL` and may not move in a refactor (`docs/math-foundations.md` §2.3) | 4 |
| `bloodletters_curse.vile_decay` | Same as Carve — **H1** | Identical shape, magic/ability-gated | 4 |
| `horizon_focus.hypershot` | `PAIR_ONLY`, declared | Exclusion set is a pair-local rotation fact; ship it first as the amp-kernel canary, expected no-op | 3/4 |
| `shadowflame.cinderbloom` | `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` | A `LivePredicate`, never a window; the bonus becomes a rider on its triggering event, and the Liandry reprice is extracted in a prior slice | 4, last |
| `force_of_nature.steadfast` | `COUPLED_AUTHORITATIVE` — the stack ledger reads **any roster attacker's** magic damage and CC into the holder (`survival/transitions.py::update_combat_state` keys on `action.attacker`), a roster input under the rule three lines above; the earlier `PAIR_ONLY` reading contradicted both that rule and C5's own receipt-walk blast radius, and is retired | D-08's predicate widening is unchanged. The pair engine's `defensive_effects` DefenseSource schedule is **a distinct surface, not a preview of the coupled number** — it feeds the single-attacker TDD estimate, which is never a score or BIS input, asserted once, structurally. No Phase 4 tagging work exists for this mechanic and none is created here | 0B |

### Contradictions this revision resolves

| Claim as written | Verified | Ruling |
|---|---|---|
| Golden holds a fixed scenario-entry count, stated in prose | **The figure reproduces under no definition** | The figure is **retired campaign-wide and is not restated here**. Every golden shape number is emitted by `golden_snapshot.py fingerprint` (Phase 0A) into `docs/receipts/campaign-fingerprints.json`, which is its **sole home**. No campaign document states a golden leaf or entry count — including this row, deliberately: a doc figure a reader cannot regenerate is exactly how the retired one survived, so repeating it as a warning would re-seed it |
| "Five dual-sided mechanics" produce `damage_modifier` | **Six.** `item_support_effects.py` emits `kind="damage_modifier"` at six sites; the sixth is `Dream Maker — Blue Dream Bubble`, which carries no `owner` and is a cross-participant modifier outside every phase contract | D-07. The machine check keys on the semantic, not on `all_sources=True` — which three of the six producers (Black Cleaver, Bloodletter's Curse, Dream Maker) do not set |
| Four bench fingerprint triples pin performance | Only `public_evaluations` is emitted today; measured proposals, score-memo misses and pair `run_fight` counts have **no producing tool and no committed artifact** | Three quarters of the performance contract is unmeasurable until Phase 0A builds the instrument; no phase may cite those numbers as a baseline before then ([runbook](silent-failure-runbook.md), R-06/R-07) |
| Golden is the campaign's safety net | `golden_snapshot.py` calls only `pipeline.run_fight` — no roster, no coupled walk, no `score_only`, and it rounds to 2 dp | D-93. Golden proves no pair-engine leak and nothing else; the coupled baseline is built in Phase 0A |
| Phase 5 rides on Phase 3's vocabulary | It does not — `cast_dependency.py` is a stdlib leaf and Phase 5's only shared file is a different function in `pipeline.py` | Phase 5 runs in parallel from the first barrier |
| Shrinking the enriched-view set is inert | Fimbulwinter reads `_event_id`, which exists only on enriched rows; dropping it disarms a fail-closed raise | D-03. The enriched-view set is one member larger than the claim assumed; its membership is enumerated once, in Phase 2's `enriched_view_items` docstring |
| **Rev 1's Phase 4 end state**: the pairing registry empties and is deleted, ending the `owner` handshake entirely | **Two pair-side halves survive on the merits** — `abyssal_mask.unmake` keeps `magic_amp` because golden pins it, and `_apply_command_amp` is kept as a `THEORETICAL` preview rather than deleted | **The end state is deliberately revised, not met**, and this row is that revision's retirement notice. `Pairing` keeps three members with `UNPAIRED_KNOWN_DEFECT` asserted empty (D-92), `SPLIT` stays legal wherever the authority rule's three conditions hold, and D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` uniqueness test replaces deletion as the double-count guard. What rev 1 wanted from the deletion is carried by criterion 8 below and by Phase 4's criteria 1 and 4; no phase document may restate rev 1's wording as a live end state |

### D-01 … D-14 — Phase 0 semantic corrections ([Phase 0](phase-0-gates-and-corrections.md))

| # | Ruling | Why |
|---|---|---|
| D-01 | The tuple gate at `pipeline.py:994` consults `has_event_view_support_items`. Phase 2's later derivation must reproduce that predicate's exact membership, enumerated once in `tuple_incapable_items`'s docstring. Reject the union variant and reject widening the tuple schema. | Smallest diff, no schema change, and it makes two gates name one predicate; widening the tuple fixes one item and leaves three broken. |
| D-02 | Solstice Sleigh is tuple-incapable and enters the set automatically; its test asserts membership and asserts health-regen is *not* the reason it is protected. | Its protection today is a cached-stat coincidence, and a test pinning a coincidence is worse than no test. |
| D-03 | Fimbulwinter needs the enriched view and is a member of `enriched_view_items()`, whose membership Phase 2's docstring enumerates. | It reads `_event_id`, and dropping it changes a serialized receipt field and disarms a fail-closed raise. |
| D-04 | Damage-type restriction is `damage_classes: frozenset[DamageClass]` and `attack_classes: frozenset[AttackClass]`, both required, no default. Empty-means-all is banned. | A silent default in a campaign whose thesis is that silent defaults kill; `attack_classes` is the only place "from all sources" becomes expressible. |
| D-05 | One `TransitionRank` IntEnum, introduced in 0A as a byte-identical projection of today's floats, extended in 0B by exactly one member. `_priority` as an open float is deleted. | Three phases each invented a different float for one unnamed ordering question; naming it in 0A makes Phase 4's stage a no-op instead of a rewrite. |
| D-06 | Rank → `legacy_phase` float, a many-to-one projection stated once per stage. **At 0A: eight producing names onto five distinct floats** — `STATE_GRANT −2.0`, `BARRIER_GRANT −1.0`, `DAMAGE 0.0`, `LATE_BARRIER 0.5`, `REACTIVE 0.5`, `DEBUFF_ARM 1.0`, `RECOVERY 1.0`, `UTILITY_ARM 1.0`. **After 0B adds `AURA_ARM −0.5`** (D-05's one new member): nine producing names onto six distinct floats. These are **not** `IntEnum` values — the enum is a dense ordinal and `legacy_phase` is the projection. `TERMINAL` is the producer-less rank carrying the published name `death_or_terminal_cutoff`, which no transition produces — the ninth member at 0A, the tenth after 0B. **`legacy_phase` is total over the enum**: `TERMINAL` is declared last and projects to `math.inf`, so the non-decreasing-over-declaration-order assertion runs over every member with no exception, and no producer can put that float in a sort key anyway. | One member per commit keeps every ordering diff attributable; the collapsed groups are exactly where Phase 4's S6 split becomes semantic; and a projection with a hole in it is a monotonicity gate with an exception clause. |
| D-07 | Dream Maker joins the corrections scope. The check is: every packet modifying another participant's damage declares an `Authority`, and `owner` is present **iff** `Authority == SPLIT`. | Keying on `all_sources=True` misses Dream Maker, Black Cleaver and Bloodletter's. |
| D-08 | Force of Nature's 5-of-15 kind set widens to `IMMOBILIZING_CC_KINDS`, one commit in 0B. | The campaign's own one-predicate-one-home invariant decides it, and the blast radius is receipt-walk only. |
| D-09 | Delete `SurvivalAction.utility_kind` and `state["utility_effects"]` in 0A. | The comparison against a `frozenset[str]` is permanently false because `ActionKind` is not a str enum, and nothing reads the state. |
| D-10 | Delete `apply_transition` and its two exports in 0A. | Zero call sites; a second dispatch ladder that can drift, in the module Phase 4 rebuilds. |
| D-11 | Custom `cast_order` keeps a champion-agnostic shape check; the permutation check moves to `FightParams.validate_for_champion` and `cast_dependency.expand_user_order` reinserts recast slots after their parents. Recast parentage is `recast_of` on the parsed ability entry and nothing else. Fixed in 0B, over the `cast_dependency` leaf Phase 5 lands first (see *Ordering*). | A silent damage-row drop on a public parameter is a correction, and Phase 5 should inherit it fixed. |
| D-12 | Repeat-Command stacking ships as a sentinel in 0B and a policy (`merge=EXTEND`) in Phase 3; the sentinel's failure message names D-12. | A correction with no reachable fixture is a declaration wearing a correction's clothes. |
| D-13 | The expiry boundary is characterized in Phase 0 and declared `OPEN_CLOSED` for all dual-sided mechanics in Phase 3. | Reachable only on exact float equality today; unifying it in Phase 0 would be an unfixtured change. |
| D-14 | `support_value` unit mixing is pinned by a characterization test and excluded from every coverage expectation. **H3.** | A product decision about the utility objective, not a defect with an oracle. |

### D-20 … D-26 — where a failure lands ([Phase 1](phase-1-coverage-evidence.md))

| # | Ruling |
|---|---|
| D-20 | **Load** catches structural impossibility only — a claim whose shape cannot be backed. No imports, no filesystem, no `data/` read; O(n) string and set checks raising `CoverageClaimError` / `TriggerRegistryError` / `DeclaredCycleError`. *Why: a load gate that reads data is a startup cost and a rule-2 violation.* |
| D-21 | **Resolution** (any `pytest` run, including `-k` and bisect) resolves every claim's evidence against the real codebase. *Why: this is the tier that makes the drift window one commit.* |
| D-22 | **Full session** owns exact parametrized ids and duplicate-nodeid detection, gated on a session predicate that **never** calls `pytest.skip`. *Why: a skip takes the tier-1 path and reports green.* |
| D-23 | A coverage refusal is `WITHHELD` — a named receipt and no number — and a new withholding reason extends `champion_optimizer_matrix.EXPECTED_WITHHOLDING_PREFIXES` in the same commit. A withheld item is **excluded from candidate generation and named in the response's `withheld[]`**, never scored as zero; the per-request exclusion count is published and pinned by `champion_optimizer_matrix`. *Why: otherwise CI is red while `pytest` is green — and an unruled withheld item either silently loses BIS a legal build or re-creates the zero this campaign exists to kill.* |
| D-24 | A rule that can legitimately return 0.0 declares `zero_policy=STRUCTURAL_ZERO` with a reason; an undeclared zero arising from an empty stream is a bug by definition and raises. `zero_policy` is **required on `BehaviorRule` and on `damage_entry`/`simple_damage`** — with one ruled exception, written here the way D-52 writes its registry exception: the champion call sites are **not** individually edited. `damage_entry` and `simple_damage` have exactly one construction layer, `champions/slotlib.py` (`:391`, `:600`), and that layer supplies the one declared default — `zero_policy=MEASURED`, because a module formula that evaluates to zero *computed* that zero — overridable per call. **The exception is itself guarded**: a source assertion over `champions/` forbids a `.get(key, <literal>)`-shaped fallback from feeding a damage formula — rule 5's no-stale-literal discipline extended to champion inputs — because a zero produced by an *unwired input* (a stack count or option that never resolved) is the incident's own shape and must fail loud, never be stamped `MEASURED` by the default. Phase 3's criterion 7 carries the assertion. Measured blast radius of the no-exception reading: **384 call sites across 143 champion modules**, which no lane owns and no phase budgets; a required-no-default field there is a campaign-wide champion sweep smuggled in by an idiom. Every numeric leaf produced by neither is enumerated in a committed `zero-policy-frontier` set with an issue ref, asserted non-growing. *Why: this is the invariant, mechanized — and a policy that stops at items cannot discharge a criterion written over every leaf.* |
| D-25 | `ProjectionStarvation(field, producer, reason)` is raised lazily on first read of an inadequate representation. **Exactly one catch exists**, at the request boundary in `src/app.py`, converting it to a 500 carrying the `STARVED` receipt; a source assertion allowlists that single handler and forbids every other. *Why: it means a projection and a consumer disagree — a programming error, not a data condition — but "never caught" makes a reachable one an unhandled traceback rather than a named refusal.* |
| D-26 | Fail-closed branches no real item reaches are proven three ways: the rule is checked on an empty registry, a synthetic fixture exercises each branch, and emptiness itself is a pinned number. *Why: zero ordinary-SR items are ineligible today, so silence would otherwise pass for coverage.* |

### D-30 … D-38 — trigger scope ([Phase 2](phase-2-trigger-bus.md))

| # | Ruling |
|---|---|
| D-30 | The bus carries `CC`, `DAMAGE`, `TAKEDOWN`, `SUPPORT_TRIGGER`, built lazily and gated by declared `reads`. *Why: lazy construction is what keeps the refactor performance-neutral.* |
| D-31 | Takedown is a bounded compatibility member: one synthesizer, one consumer, declared `SynthesizedTrigger`; two look-alike mechanics declare `reads=frozenset()` so nobody unifies them by accident. *Why: an unbounded synthetic stream is a new silent-failure surface.* |
| D-32 | `CcClass` is the only thing consumers branch on; `cc_kind` survives as an opaque receipt token, enforced by a source assertion. *Why: the incident's third failure was three consumers branching on raw strings.* |
| D-33 | `CcClass` gains a fifth member, `UNCLASSIFIED_CONTROL`; the invariant is `kind is CC ⟹ cc is not NONE`. *Why: the proposed two-member invariant silently narrows the live CC stream, which admits bare `crowd_control` marker rows.* |
| D-34 | The sixth control-reading site (`damage.py`'s certification gate) migrates to the bus; `"crowd_control"` as a token outside the vocabulary is a Phase 3 declaration problem. *Why: an allowlist that admits only writes leaves a read behind.* |
| D-35 | Registry validation is structural only and may not read `data/items.json`; item-name resolution moves to the test that pins the capability tables. *Why: repo rule 2, and otherwise the bus stops being a stdlib-plus-`ability_spec` leaf.* |
| D-36 | `MechanicOwner` is a four-member union — `ItemOwner`, `RuneOwner`, `ChampionSlotOwner`, `EngineOwner` — replacing the item-name field. The `*Owner` suffix is not decoration: `Engine` is already the `PAIR \| WALK` enum on the same dataclass. *Why: four keystones, a champion healing registry and two ally-effect producers flow into the same support templates and have no item name.* |
| D-37 | The guarded-equals-declared assertion is folded per `impl`. *Why: scoped to one deriving function it is simply false for two producers.* |
| D-38 | The tuple gate at `pipeline.py:968-1000` conjoins **ten** adequacy clauses after the `score_only` guard. Phase 2 derives **one** — the support-item adequacy clause, which reads `has_event_scan_support_items` at HEAD and `has_event_view_support_items` after C1 repoints it (D-01) — and says so; Phase 4 owns the other **nine**, including `params.target_threshold_health_heal <= 0`, which no earlier reading counted. *Why: a partial derivation presented as complete is the same prose-outruns-code failure, a miscount leaves a live clause behind a discharged criterion, and naming the pre-correction spelling as the clause's identity would hand an implementer the predicate C1 exists to retire.* |

### D-40 … D-52 — behaviour as data ([Phase 3](phase-3-behavior-rules.md), less D-45)

| # | Ruling |
|---|---|
| D-40 | **Every** frontier commits its exclusion lists beside its counters, diff-gated by set equality — `docs/behavior-frontier.json` (Phase 3, counters 1–4) and `docs/migration-frontier.json` (Phase 4, counters 5–7). *Why: a frontier whose exclusions live inside the tool that measures it can be driven to zero by editing the exclusions.* |
| D-41 | Lane-membership assertions inspect resolved values, not literal `frozenset` nodes. *Why: a tuple, list or set literal defeats the syntactic version.* |
| D-42 | The existing "no item-name dispatch in the damage engine" test is superseded by the frontier counter. *Why: it inspects only comparisons, and all fifteen live sites are calls, so it passes today.* |
| D-43 | `COMPILED_WALK_UNREPRESENTABLE_ITEMS` becomes a per-**rule** `Compilability` field owned by Phase 3 and consumed by Phase 4 — not a per-family lane predicate. Phase 3 also declares the fold from N per-rule values to the one per-owner answer `compilability_for` returns. *Why: three of its sixteen reasons are item-level conservatism notes that a family predicate over-withholds by an order of magnitude.* |
| D-44 | The unit of declared behaviour is a `BehaviorRule`; "atom" is retired as a name for **any declared unit** — behaviour rules, evidence members, and Phase 5's marker reach (`authored_marker_reach`). The live `atomizer.Atom`, `atomizer_domains` and `rotation_resolver`'s apply-atom keys keep the word; they are existing code, not declarations this campaign authors. *Why: three unrelated meanings of "atom" already exist in `src/`, and "retired campaign-wide" would be unimplementable against them.* |
| D-45 | Phase 1 exports `ClaimLane`; Phase 3 exports `EngineLane`. **Owned by Phase 1**, binding on Phase 3. *Why: two new modules must not both export `Lane`.* |
| D-46 | `ValueRef.registry` is a three-member union from day one: `ITEM_EFFECTS`, `ALLY_ITEM_EFFECTS`, `RUNE_EFFECTS`. *Why: CLAUDE.md rule 5 extends the no-literals rule to keystones, which are runtime damage producers.* |
| D-47 | `ALLY_ITEM_EFFECTS` is hand-authored and refresh-inert; it joins `scripts/patch_update.py`'s audit in 0A. *Why: four of six `damage_modifier` mechanics read their numbers from it, and refresh-inert is worse than stale-cached on patch day.* |
| D-48 | The refresh-liveness proof mutates cached JSON, not the registry. *Why: a monkeypatched registry value is overwritten by the parse, so the test cannot distinguish a live reference from a reconstruction.* |
| D-49 | One monotonic `data_version()` counter in `data_registry`, **declared in 0A** and keyed on by every item-derived memo: Phase 3 keys the seven non-rotation survivors, Phase 5 keys the two rotation memos. *Why: eleven such memos exist and refresh clears two; two of the nine survivors cache derived cast orders, and L4 and L6 are live at once — a counter either lane declares is a counter the other cannot key on. `data_registry.py` is a zero-import leaf and an unread counter is behaviour-free, so 0A is its only conflict-free home (same argument as D-05's `TransitionRank`).* |
| D-50 | Redemption gets a `secondary_target` declaration; Moonstone's runtime-computed packet kind is refactored into two declared packets. *Why: a runtime-computed kind cannot be statically resolved or assigned a family.* |
| D-51 | Reachability is **bidirectional and campaign-wide**: a declared marker reaches its consumer, and every interpreter branch is reachable from some declaration. *Why: both live failures are real — one branch no champion reaches, and one packet spelling the enum would orphan.* |
| D-52 | A compiler/interpreter registry of callables is an accepted exception to "no callables in declarations", provided the key is a closed enum, the callable is a module-level `def`, and totality is asserted. *Why: better to write the exception into the criterion than to let the criterion be quietly false.* |

### D-60 … D-72 — one walk, five views, one algebra ([Phase 4](phase-4-program-engine.md))

| # | Ruling |
|---|---|
| D-60 | One kernel, one invocation per pass; five views project the result. *Why: two engines pricing one mechanic is failure mode C of the incident.* |
| D-61 | A view reads only the program and the walk result and may not re-run arithmetic. *Why: it makes "score mode and receipt mode agree" structural instead of tested.* |
| D-62 | `ViewTag` is `THEORETICAL` or `APPLIED`; every serialized number carries exactly one and a sum may never mix them. `view_tags` declares **exactly one tag per `(mechanic, EngineLane)`**, and for every `(mechanic, subject, event_id)` at most one `APPLIED` contribution exists across all producers — a uniqueness test on the `OutcomeLedger`, not a review rule. *Why: a pair-authored preview summed into a coupled total is a double count with no symptom, and forbidding only mixed tags leaves two `APPLIED` contributions for one mechanic legal.* |
| D-63 | `PARTICIPANT_LEDGER_CONTRACT["phases"]` is **derived** from `TransitionRank` through `public_phase`, and `CAPABILITY_SCHEMA_VERSION` bumps whenever the **published phase list changes** — never on a derivation edit that leaves the payload identical. *Why: six phase names are hand-listed public receipts today and no contract noticed that Phase 0B inserts one; and a bump with an unchanged payload teaches clients the version means nothing.* **The chain is chronological and every value has exactly one owning commit — this row is its only home:** `1` 0A lands the derivation (a starting value, not a bump) → `2` 0B's C4 publishes `AURA_ARM` → `3` Phase 3's 3.8 coverage flip changes the serialized coverage payload → `4` Phase 4's S9 publishes `disposition` and `ViewTag`. Phase 4 owns every bump after Phase 3's, so if S6's rank split ever publishes a new phase name it takes `4` and S9 takes `5`; S6 is asserted payload-neutral, so it does not. |
| D-64 | `OutcomeLedger` has write-once fields and exactly one named adjustment reason. *Why: an unnamed in-walk mutation is how a receipt and a score diverge.* |
| D-65 | `SumPlan` is defined over a set of event ids with a declared ordering plus a uniqueness test across all three panels. *Why: three sources are unioned today with only a comment preventing a double count.* |
| D-66 | Every dual-sided mechanic declares `HolderStacking = IDEMPOTENT_AURA \| PER_HOLDER` in `holder_stacking`, the required, defaultless capability field **Phase 4 introduces** (field-ownership table below) and `None` everywhere the mechanic is not dual-sided. The arm-time dedupe key is `(subject, mechanic_id)` only for `IDEMPOTENT_AURA` and `(subject, mechanic_id, holder)` otherwise; a dropped duplicate emits a `dedupe` receipt row. Abyssal is `IDEMPOTENT_AURA`; Command's value is H2-blocked and fails closed to `PER_HOLDER` — written into the row explicitly beside the `[H]` id, because the field has no default to fall through to. One test per dual-sided mechanic. *Why: two Abyssal holders arm two modifiers on one subject today — but a flat `(subject, mechanic_id)` key silently drops a second Mandate holder's contribution, which is the incident's own shape mandated by a criterion.* |
| D-67 | The sort key is **eight** elements — `(time, phase, sequence, *participant_order → 2, participant_id, _event_id, source)`, verified `len(action_key(...)) == 8` — and any index-ification preserves that shape verbatim. *Why: the participant-order component contributes two, and a seven-element restatement silently reorders ties.* |
| D-68 | Every float `phase` the compiler and the timeline write consumes `TransitionRank` in the same commit as the ladder: `survival/compile.py:316` (the `action_key` phase argument), `:319`, `:865` (the inline sort tuple's second element), `:874`, `:1011`, and `participant_timeline.py:2767`. *Why: otherwise the compiled path desyncs and only the equivalence suite can see it — and the two originally named were not the whole surface.* Landed in 0A; Phase 4 only deletes `legacy_phase`. |
| D-69 | The fallback rung ladder has four states, including `SearchPoisoned(reason)`. *Why: one roster ally holding a `damage_modifier` producer degrades an entire optimizer request today, and a three-rung histogram would report uniform fallback with no cause.* |
| D-70 | Catalyst is a `CrossPassDependency` with `max_passes=2`; the program is rebuilt per pass and the walk is never re-entered. *Why: recursion through the walk is what makes the current path unrepresentable.* |
| D-71 | Rounding is presentation, owned by one precision registry in `program/`; the death-time cutoff policy is named, not commented. Scope: `round(` outside the registry goes to zero **within `program/`**; the kernel's measured 118 sites (`survival/transitions` 72, `receipt_state` 38, `compile` 6, `accumulate` 1, `score_state` 1) are a declared, non-increasing counter on the migration frontier, driven down by moving receipt-field rounding into the end-of-walk projection. *Why: rounding scattered across twelve modules is unverifiable — but gating `survival/` at zero would force `survival/ → program/`, inverting the phase's own one-way dependency.* |
| D-72 | **Disposition is an algebra, not an annotation.** `Quantity = Measured(float) \| StructuralZero(reason) \| Withheld(receipts) \| Starved(field, producer, reason)` — one frozen algebraic value type in `ability_spec.py` beside `Disposition`, which survives as `Quantity`'s tag projection. Arithmetic is defined on the type: the invariant table's propagation row **is** `Quantity.__add__`, and a `Starved` quantity raises `ProjectionStarvation(field, producer, reason)` on first read, preserving D-25's single catch. The kernel is untouched — raw floats inside the walk; `Quantity` applies where leaves are born, at the `OutcomeLedger`/view boundary (Phase 4 S3 introduces it, pure — `Measured` wraps the same floats; S9 serializes it). Serialization is **derived**: one `serialize_leaf` function is the only producer of both a payload leaf and its `dispositions` entry, so map and leaves cannot drift because there is one writer, and the payload-schema equality test becomes a backstop rather than the mechanism. *Why: without the type, propagation, the starved-read rule and map/leaf agreement live as a shadow type system maintained by tests — annotation plus discipline emulating what one `__add__` gives structurally, at a permanently higher gate count.* |

### D-80 … D-89 — declared cast dependencies ([Phase 5](phase-5-cast-dependency.md))

| # | Ruling |
|---|---|
| D-80 | Two vocabularies, asserted disjoint: module-declared `DEPENDENCY_KINDS` and resolver-inferred `INFERRED_EDGE_KINDS`, with an `origin` field on each edge. *Why: merging them would blur which surface owns the claim.* |
| D-81 | A suppression nests inside its parent dependency and structurally can express only the exact reverse pair. *Why: it makes an over-broad suppression inexpressible rather than merely discouraged.* |
| D-82 | A declared edge opposed by an unsuppressed inferred edge raises. *Why: "declared always wins" resolves a real modelling disagreement silently in the module's favour.* |
| D-83 | Both Syndra declarations ship — the recast dependency is load-bearing, not redundant. *Why: verified — without it the resolver's tie-break ranks E ahead of the recast and the derived order changes.* |
| D-84 | The reverse recast inference does not exist today; the test's seed exception for it is vacuous and is deleted, and the fact moves to an audited `latent_reason`. *Why: a silently-passing exception is a claim nothing checks.* |
| D-85 | Cycle failure is gated on a non-empty declaration set. *Why: the 170 non-declaring champions (173 cached, less Syndra, Zed and Brand) keep the existing silent fallback and change by zero bytes, which is what makes the migration provably diff-free.* |
| D-86 | A custom order violating a declared dependency is rejected, carrying the dependency's own reason and source. *Why: the softer alternative — making the stun conditional so the order is legal — is better modelling and belongs on the frontier, not here.* |
| D-87 | The vocabulary lives at `src/calculator/cast_dependency.py`, not under `champions/`. *Why: putting the generic resolver's taxonomy under `champions/` inverts the layering.* |
| D-88 | The one unreachable inferred kind lands on a dated single-entry acknowledged-gap list, emptied by the phase's second half. **H6.** *Why: a dated one-line gap is auditable; a silently dead branch is not.* |
| D-89 | One seed conversion plus three redundant-seed deletions; `COMBO_TABLE` becomes `CAST_ORDER_OVERRIDES` with a closed `override_reason`. *Why: it makes the retirement frontier machine-countable instead of doc-claimed.* |

### D-90 … D-101 — cross-cutting corrections to the phase contracts

| # | Ruling |
|---|---|
| D-90 | **Phase 0 owns every semantic correction.** Phases 2, 3 and 4 delete their own correction stages and declare Phase 0 a hard entry gate. *Why: a correction inside a refactor slice has no attributable diff.* |
| D-91 | **Phase 1 sheds the classifier rewrite**, attaching evidence to the existing registries; the rewrite happens once, in Phase 3, which re-captures Phase 1's receipt with an enumerated diff. *Why: hand-authoring hundreds of claim records against registries Phase 3 deletes is work done twice and drift in between.* |
| D-92 | Any set pinned as "known exceptions" is asserted **empty** after Phase 0, with the declaration as source of truth. *Why: a set pinned at the pre-correction state is born stale.* |
| D-93 | **Golden's role is restated campaign-wide**: it proves no pair-engine leak and nothing about the coupled walk, coverage, or support effects. Every slice touching those names cites a non-golden numeric gate. *Why: verified — the snapshot calls only the one-pair entry point.* |
| D-94 | The E9 corpus gate is fixed in Phase 0A before anything else. *Why: as written every `src/` edit turns the suite red, and it is a cross-worktree mutex by construction.* |
| D-95 | The hand-listed module front-door registry in the architecture tests is derived. *Why: it is itself the "prose that survives a missing implementation" shape this campaign exists to kill.* |
| D-96 | `acceptance_matrix.py` and `champion_optimizer_matrix.py` join every phase's gate list, and a new withholding reason is registered in the same commit. *Why: neither appears in any phase contract, and Phase 3's intermediate slices are structurally CI-red without this.* |
| D-97 | **Never re-capture a baseline inside a semantic slice**; land against the old baseline plus a committed allowlist with oracle receipts, and re-capture once per phase boundary. *Why: reverting a slice must not require reverting a multi-megabyte blob.* |
| D-98 | Every replacement of a hand set by a derivation lands the derivation **beside** the legacy set with an asserted delta, then flips in a one-symbol commit. *Why: two phases skip this and are correspondingly unrevertible.* |
| D-99 | CI's real lint gate is `--fail-under=9`; the ratchet becomes **per-file and non-decreasing** for every file a slice touches. *Why: ~25 new clean modules raise the average while the largest module degrades, so an average ratchet measures nothing.* |
| D-100 | The corpus gate compares each scenario's pinned tree against the **merge-base**, and a repin script joins the commit gate. *Why: the current gate demands a value that cannot exist before the commit does, and a merge commit is stale against both parents.* |
| D-101 | **The compiled score kernel categorically cannot represent a `damage_modifier` today.** Therefore after D-01 an amp holder falls back rather than compiling, and an amp-holding ally poisons the search (D-69). Both the compiled-lane claim in Phase 3 and the performance thesis in Phase 4 are unfounded until **H5** is scoped or explicitly descoped. *Why: verified against the template compiler's fail-closed raise; no contract budgeted it.* |

### Ordering

Phases 0/2/1/3/4 are one serial chain because they rewrite the same five hotspots — `pipeline.py`,
`item_support_effects.py`, `survival/transitions.py`, `survival/actions.py`, `participant_timeline.py`.
Phase 5 is the only structurally partitionable phase and runs in a parallel worktree from the first
barrier; it was sequenced last for a Phase-3 vocabulary dependency the delivered contract does not have.
Phase 1 follows Phase 2 because the pairing registry is the evidence source for its dual-sided claims.

**The campaign has exactly one edge running backwards out of Phase 5.** Phase 5's `cast_dependency.py`
leaf carries `orderable_slots` and `expand_user_order`, and Phase 0B's C6 consumes them; the leaf commit
therefore merges before C6. That is barrier `B0.5` in the [runbook](silent-failure-runbook.md)'s *Shape*
section — the block holding the worktree ownership map and the barrier list — it is the only L6→L1
dependency, and it exists so the two functions have one home from day one
instead of a rename-then-move across two live worktrees. Lane ownership, barriers and the integration
protocol are the runbook's.

### Human-owned decisions

Everything above is ruled and must not be re-opened by an implementation agent. These six are not.

| `[H]` | Decision | Why it is yours | Cost of deferring |
|---|---|---|---|
| **H1** | Move Carve and Vile Decay to coupled-authoritative with pair preview | Moves BIS winners on real builds; the Cesàro approximation is documented balance-sensitive | Phase 4's mechanic stage ships **four of the seven authority moves** (Hypershot, Abyssal, Bloodsong, Shadowflame); Carve and Vile Decay hold for H1 and Command for H2 |
| **H2** | `CcScope` for Syndra E — how many roster targets does one cone stun, and on what source | Needs a sourced wiki reading with a target cap; today's answer is a construction accident of running the rotation once per defender | **Recorded ruling if unanswered at Phase 4 S7: *deferred, default shipped*.** Command stays `SPLIT`, `CcScope.Unreviewed` resolves to `SingleTarget` on the pair defender with a disclosure, and `HolderStacking` fails closed to `PER_HOLDER`. If H2 lands before S7, `CcScope` takes the sourced value and Command's authority moves in that same commit |
| **H3** | Does amplification count as support value in the utility objective | A Mandate holder contributes ~0.07 points where a Locket holder contributes hundreds of HP, because a unitless multiplier is summed with health | Nothing blocks; pinned by a sentinel |
| **H4** | Delete the **four** dead effect tags (`conditional_attack_speed`, `shield_reduction`, `target_state`, `target_attack_speed_aura` — read nowhere in `src/`) and make defensive dispatch consume the **six** self-referential ones (`defensive_start`, `stat_conversion`, `sustain`, `target_mitigation`, `target_threshold_health`, `target_threshold_shield` — read only by the `item_coverage` claim that cites them, while the behaviour is reached by item name) | A data-declaration edit whose only current reader is the sentence justifying it; renaming a tag silently reclassifies items with zero test signal | Ten tag-claims sit on Phase 1's frontier with explicit reasons. Phase 3 enumerates the members; this row and Phase 3 must not disagree on which four and which six |
| **H5** | **Scope the compiled-kernel extension** — timed, typed damage modifiers (D-101) | Multi-week and unbudgeted; it decides whether the compiled lane and the performance thesis are achievable at all | **Recorded ruling: DESCOPED.** The compiled kernel is not taught timed, typed damage modifiers in this campaign, and the descope is recorded here because no phase document may write it into its own prose. The dependent criteria, restated as criterion 11 requires: **Phase 3's criterion 16** — every `delta_amp` rule declares `ReceiptOnly` carrying the compiled-kernel reason and the phase's compiled-lane claim reads "declared empty, fallback receipted", discharged by the declaration and never by an unstated absence; **Phase 4's criterion 16** — no criterion in that phase asserts a compiled amp, and every `damage_modifier` holder reports `RECEIPT_WALK` with a named receipt. Accepted consequences under D-101: every amp holder falls back to the receipt walk for the life of the campaign, an amp-holding roster ally takes a fallback rung with a named cause rather than compiling (D-69), and the performance thesis that assumed a compiled amp lane is **not met and may not be cited as achieved by any phase**. Re-scoping later is a new ruling recorded in this row, not a phase-level choice: it would land as its own stage after Phase 4 S7 with its own equivalence fixture, and the flip from `ReceiptOnly` to `Compilable` would be that stage's one-symbol commit under D-98 |
| **H6** | Author the missing chill marker, or delete the branch and replace it with a declared enabler dependency | Option two is the Phase 5 thesis but changes a champion's order and her golden rows | **Recorded ruling: Phase 5 ships the audit with `enhanced_consume` on a dated single-entry acknowledged-gap list and does not resolve H6.** Emptying the list is a named follow-on slice with its own investigator receipt, scheduled only once H6 is answered |

## Shape

### Document manifest

| Path | Owns |
|---|---|
| `docs/plans/2026-08-08-silent-failure-campaign.md` *(this file)* | The invariant, the disposition vocabulary, semantic authority, D-01…D-101, the phase graph, the manifest, shared names, and the `[H]` list |
| [`silent-failure-runbook.md`](silent-failure-runbook.md) | Every protocol shared by more than one phase: the verification matrix, golden and coupled-golden discipline, the investigator rule, performance methodology and fingerprints, **the instrument-and-artifact table with every script signature**, commit units, lanes, barriers, integration and agent briefs. Owns D-96, D-97 |
| [`phase-0-gates-and-corrections.md`](phase-0-gates-and-corrections.md) | 0A gate hardening (no behaviour change) and 0B's six semantic corrections C1…C6. Owns D-01…D-14, D-90, D-93, D-94, D-99, D-100, plus the 0A halves of D-47, D-49, D-63 and D-68 |
| [`phase-1-coverage-evidence.md`](phase-1-coverage-evidence.md) | Typed coverage evidence, the resolver, the audit and the mutation tests. Owns D-20…D-26, D-45, D-91, D-95 |
| [`phase-2-trigger-bus.md`](phase-2-trigger-bus.md) | One trigger bus, `MechanicCapability`, five hand name sets retired. Owns D-30…D-38 (D-38's first clause), D-92, D-98 |
| [`phase-3-behavior-rules.md`](phase-3-behavior-rules.md) | Item behaviour as a closed rule union with value references and interpreters. Owns D-40…D-52 except D-45, plus **D-101**, and answers it with H4/H5; plus the 3.8 half of **D-63** (the coverage-flip bump to schema 3) |
| [`phase-4-program-engine.md`](phase-4-program-engine.md) | Immutable programs, one walk, five views, the `Quantity` algebra. Owns D-60…D-72 and D-38's remaining nine adequacy clauses, plus the Phase 4 halves of **D-63** (every `CAPABILITY_SCHEMA_VERSION` bump after Phase 3's 3.8 flip), **D-68** (`legacy_phase`'s deletion) and **D-101** (the compiled-lane criterion) |
| [`phase-5-cast-dependency.md`](phase-5-cast-dependency.md) | Module-owned cast dependencies and bidirectional reachability. Owns D-80…D-89 and D-49's two rotation memos; carries H6's dated acknowledged gap |

Every decision id is claimed by exactly one document's *decisions owned* line unless it appears in the
split table below, and the union covers **every declared decision id** — the 78 ids the decision tables
above define. The numbering is deliberately sparse: **D-15…D-19, D-27…D-29, D-39, D-53…D-59 and
D-73…D-79 are unassigned reserve gaps** between per-phase blocks, defined in no document, and a
governance check treats them as non-existent rather than missing — "covers D-01…D-101 with no gaps"
would fail on day one or teach the checker to reinterpret, which is the discretion this manifest exists
to remove. The declared inventory is committed as `docs/receipts/decision-inventory.json` — one row per
id with its owning document and, for split decisions, every half — and the governance check (criterion
11) reads that file through `plan_audit.py` (runbook R-37) rather than performing a prose audit.
**The manifest is authoritative**: a phase
header that disagrees with it is the header that is wrong; the inventory is derived from the manifest
and diff-gated, never hand-reconciled.

| Split decision | Halves |
|---|---|
| **D-38** | Phase 2 derives one of the ten adequacy clauses; Phase 4 the other nine |
| **D-44** | Phase 3 owns the ruling; binding on Phase 5's `authored_marker_reach` rename |
| **D-45** | Owned by Phase 1; binding on Phase 3's export name |
| **D-47** | Phase 3 owns the refresh-inert ruling; Phase 0A owns adding `ALLY_ITEM_EFFECTS` to `patch_update.py`'s audit |
| **D-49** | Phase 0A declares `data_version()`; Phase 3 keys seven memos; Phase 5 keys the two rotation memos |
| **D-63** | Phase 0A lands the derivation at version 1; 0B's C4 bumps to 2; **Phase 3's 3.8 coverage flip bumps to 3**; Phase 4 owns every bump after that (S9 → 4) |
| **D-68** | Phase 0A repoints every float `phase` write at `TransitionRank`; Phase 4 deletes `legacy_phase` |
| **D-101** | Phase 3 owns the ruling and the empty-compiled-lane declaration; Phase 4's compiled-lane criterion is the bound half |

### Campaign artifacts

Instruments, gate scripts and committed receipts are one table, in the
[runbook](silent-failure-runbook.md)'s *Shape* section, with the creating lane and the role of each. It is
the only such table in the campaign; this document names artifacts but never re-lists them.

### Phase dependency graph

```text
Phase 0A  gate hardening, zero src behaviour change  ──── hard barrier ────┐
   │                                                                      │
Phase 0B  six semantic corrections, one commit each  ──── hard barrier ────┤
   │                                                                      │
   ├──> Phase 2  trigger bus + capability projections                     │
   │        │                                                             │
   │        └──> Phase 1  coverage evidence (reads Phase 2's registry)    │
   │                 │                                                    │
   │                 └──> Phase 3  behaviour rules (authors tag-claims)   │
   │                          │                                           │
   │                          └──> Phase 4  program engine                │
   │                                                                      │
   └──> Phase 5  cast dependencies  ── PARALLEL FROM THE 0A BARRIER ──────┘
             └── except the cast_dependency leaf, which merges before 0B's C6 (B0.5)
```

At most two lanes are ever live: Phase 5 plus whichever link of the serial chain is current.

### Shared names

One home per name; phases write disjoint fields. Anything not listed is phase-local and lives only in that
phase's plan.

| Name | Home | Introduced | Filled or consumed by | Intent |
|---|---|---|---|---|
| `MEASURED` / `STRUCTURAL_ZERO` / `WITHHELD` / `STARVED` | `ability_spec.py` (the `Disposition` enum) | 0A | 1 and 3 tag rules, 4 tags leaves | The four dispositions; these exact spellings wherever a symbol, receipt string or reason prefix is needed |
| `Quantity` — `Measured(float)` \| `StructuralZero(reason)` \| `Withheld(receipts)` \| `Starved(field, producer, reason)` | `ability_spec.py`, beside `Disposition` | 4 (S3) | folded by ledger reads and the views; serialized at S9 by `serialize_leaf` | The algebra behind the dispositions (D-72): propagation is `__add__`, a `Starved` read raises `ProjectionStarvation`, and `Disposition` survives as its tag projection |
| `disposition` — one `Disposition` per serialized numeric leaf | `program/views/receipt.py` + `capabilities.py` | 4 (S9) | published at `CAPABILITY_SCHEMA_VERSION == 4`, S9's bump in D-63's chain | The field criterion 1 is discharged through. Serialized as a parallel `dispositions` map keyed by leaf path (`{disposition, view_tag}` per entry), produced only by `serialize_leaf` over `Quantity` (D-72) — `MEASURED`/`STRUCTURAL_ZERO` leaves stay bare numbers; a `WITHHELD` leaf is absent with its receipt-bearing entry present; a leaf missing its entry fails the payload-schema test |
| `ProjectionStarvation(field, producer, reason)` | `trigger_stream.py` | 2 | raised by projections; caught at exactly one boundary (D-25) | A consumer asked a projection a question its representation cannot answer. `field` is the stream asked for, `producer` the holder, `reason` the projection that should have excluded it |
| `Authority` — `PAIR_ONLY`, `SPLIT`, `COUPLED_AUTHORITATIVE`, `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW`, `COUPLED_ONLY` | `ability_spec.py` | 0A (all five members) | declared 0B, re-exported by `trigger_stream` and enforced in 2, honoured 3 and 4 | Which engine owns a mechanic, per the authority rule above. It lives in the dependency-free vocabulary leaf because 0B declares `PAIR_ONLY` and `COUPLED_AUTHORITATIVE` mechanics in a module Phase 2 has not yet created |
| `MechanicCapability` | `trigger_stream.py` | 2 | see field table below | The single per-mechanic declaration the whole campaign shares |
| `DivergenceReceipt` | `trigger_stream.py` | 2 | 3 freezes, 4 retires | A reviewed, cited disagreement between two engines — the precedent is the acknowledged source-conflict table |
| `TransitionRank` (IntEnum) | `survival/actions.py` | 0A | extended 0B, split in 4, derives the published phase list | The one ordered transition vocabulary; no float `phase` literal survives it |
| `Compilability` = `Compilable \| ReceiptOnly(reason)` | `item_behavior.py` | 3 | consumed by 4's rung ladder | Per-rule, not per-family (D-43). It is a union of two types, not an enum — `Rung`'s `ReceiptWalk(reason)` is a different thing |
| `ValueRef` over a three-registry union (`ITEM_EFFECTS`, `ALLY_ITEM_EFFECTS`, `RUNE_EFFECTS`) | `value_ref.py` | 3 | 3 and 4 | A reference to a sourced number, never a float in a declaration. Phase 1's four-member `EvidenceRegistry` is a **different, deliberately named** literal — it adds `ITEM_INPUT_OPTIONS`, which `OptionSchema` needs and `ValueRef` must not have |
| `SourceReceipt(url, revision_id, revision_timestamp)` | `value_ref.py` | 3 | replaces the defensive-source record; Phase 5's `CastDependency.source` | Every declaration cites the revision it was read from. It sits with the registry accessors and `receipt_for`, not with the rule union |
| `BehaviorRule` | `item_behavior.py` | 3 | 4 interprets | The unit of declared behaviour; "atom" is retired for declared units (D-44) |
| `UtilityDimension` | `item_behavior.py` | 3 | Phase 1's `UTILITY_DIMENSIONS` becomes a projection of it at 3.8 | The 29 distinct dimension strings in `item_coverage._UTILITY_DIMENSIONS` (43 keys, 29 distinct values) — one home, two readers |
| `ViewTag` — `THEORETICAL` / `APPLIED` | `program/views/__init__.py` | 4 | published in the capability schema | Pair-authored preview versus coupled-delivered; sums may not mix them, and one tag per `(mechanic, EngineLane)` |
| `HolderStacking` — `IDEMPOTENT_AURA` / `PER_HOLDER` | `trigger_stream.py`, beside `Pairing` and `Engine` | 4 | `program/amp.arm_key` | Whether a second holder of one mechanic arms a second modifier on one subject (D-66). It is a per-**mechanic** fact, so it is a capability field and not part of Phase 4's per-event `Provenance`; declaring the enum beside the registry it is a field of is what keeps `trigger_stream`'s single intra-package import intact |
| `ClaimLane` / `EngineLane` | `coverage_evidence.py` / `item_behavior.py` | 1 / 3 | — | Two distinct lane vocabularies that must never both be spelled `Lane` (D-45) |
| `CastDependency`, `DEPENDENCY_KINDS`, `INFERRED_EDGE_KINDS`, `orderable_slots`, `expand_user_order` | `cast_dependency.py` | 5 (leaf commit, before 0B's C6) | `rotation_resolver`, `module_contract`, `packet_module`, `pipeline` | Declared ordering prerequisites, the resolver's own inferred taxonomy asserted disjoint, and the two order functions 0B's C6 consumes. **No `RECAST_PARENT_SLOT`**: `recast_of` on the parsed ability entry is the single authority for recast parentage (D-11) |

`MechanicCapability` field ownership — one declaration, three phases, no overlapping writes:

| Fields | Written by |
|---|---|
| `mechanic`, `owner`, `engine`, `reads`, `needs`, `authority`, `pairing`, `pair_of`, `divergence_ref`, `impl`, `packet_source` | Phase 2 |
| `values`, `compilability` | Phase 3 |
| `view_tags`, `holder_stacking` | Phase 4 |

**This table is the single answer to "who writes what on `MechanicCapability`", and a phase document
that counts its own fields differently is the document that is wrong.** Every field a later phase adds
is **required with no default** on the commit that adds it, so each existing declaration must be
revisited rather than silently inheriting an empty value — the rule Phase 2 states for `values`,
`compilability`, `view_tags` and `holder_stacking` alike. `holder_stacking` is `None` exactly for
mechanics that are not dual-sided, structurally validated at import the way `pair_of` is.

## Success criteria

1. **The invariant holds by machine.** Every serialized numeric leaf of `/api/calculate` — score, breakdown,
   survival, TDD and timeline — **and of `/api/bis` (`app.py:1238`) and `/api/optimize` (`app.py:1273`), the
   two score-serving endpoints the Goal's "every numeric leaf" also binds** — is covered by exactly one
   entry in its payload's parallel `dispositions` map, keyed by leaf path and resolving to exactly one of
   the four spellings. That map is the ruled serialization (Phase 4's S9 owns it): a bare JSON number
   cannot carry a field, and a sibling map is the one shape that leaves every `MEASURED` and
   `STRUCTURAL_ZERO` leaf a bare number. Both leaf and entry are produced by the one `serialize_leaf`
   over `Quantity` (D-72), so they cannot drift — the schema test is a backstop behind a single writer.
   A `WITHHELD` leaf is **absent** from the payload while its map entry remains, carrying the receipt;
   `static/js/app.js` takes exactly one budgeted change at S9 — the withheld-marker rendering helper —
   so an absent-with-receipt leaf renders as a named refusal, never a blank, a zero or `NaN`. A numeric
   leaf with no map entry, or a map entry naming neither a present leaf nor a withheld path,
   fails the payload-schema test; aggregates propagate per the invariant
   table's propagation row; an undeclared zero produced from an empty stream raises rather than serializes,
   proven by a negative test per fail-closed branch and by the frontier's emptiness being a pinned number.
   *No part of this criterion is discharged by an offline audit over a hand-maintained path list.*
2. **The incident cannot recur silently.** Renaming the pair-engine effect accessor, deleting the pair-side
   pricer, removing the Command packet's source literal, dropping its `owner=`, or emptying its trigger
   stream each turns the suite red — as permanent mutation tests, not a one-time demonstration. The first
   four are Phase 1's M1–M4, four of the nine permanent mutation tests M1–M9 it carries; **emptying the
   stream is Phase 2's A9**, the declared-stream sensitivity matrix.
   Phase 0 additionally carries one roster fixture whose expected total differs from the no-Command total,
   so deleting the pricer fails on a **number**, not only on an evidence member.
3. **Six, not five.** Every packet that modifies another participant's damage declares an `Authority`;
   `owner` is present iff `Authority == SPLIT`; the producer set is enumerated and includes Dream Maker;
   a seventh producer added without a declaration fails at resolution.
4. **The retired figure is gone and nothing replaces it.** No campaign document, receipt or commit body
   states a golden leaf or entry **count of a committed baseline** — not the retired scenario-entry figure,
   not a successor, and not one quoted as a warning: every golden shape number is emitted by
   `golden_snapshot.py fingerprint` into
   `docs/receipts/campaign-fingerprints.json`, which is the sole home, and every consumer reads the
   receipt's field rather than a value. **A measured diff count from a positive control or an allowlist is a
   measurement, not a shape figure, and is exempt** — Phase 5's criterion 7 requires exactly one such count in
   a commit body. The check is two halves: the test over `docs/plans/*.md` in the
   [runbook](silent-failure-runbook.md)'s criterion 2 — **whose detection rule is R-37's
   `plan_audit.py`, not an invented regex**: the retired literals live in the instrument, the live
   counts are read from the receipt and matched as standalone integers, and the proximity prong
   requires any integer adjacent to golden-shape keywords to carry a `fingerprint:` citation marker —
   so both a *correct* restated figure (value match) and a *wrong* one (unmarked proximity) fail on
   the commit that adds it, with a committed collision allowlist absorbing legitimate coincidences; and the integration agent's scan of `docs/receipts/` and the commit bodies over the
   range at every barrier, the same over-the-range check the runbook's criterion 10 already runs.
5. **Every gate means what it says.** All eleven rows of R-01 in the
   [runbook](silent-failure-runbook.md) are green at every phase boundary; zero pair-engine golden diffs
   outside a slice that declared them in advance with an oracle receipt per qualifying occurrence.
6. **The hand-maintained adequacy sets are gone.** The five trigger name sets have zero occurrences in
   `src/`; the derived tuple-incapable and enriched-view sets equal the memberships enumerated in their
   docstrings, item for item; all **ten** tuple
   clauses are derived by the end of Phase 4; and each replacement landed beside its legacy set with an
   asserted delta before the flip (D-98).
7. **Declarations outrank prose.** Phase 3's behaviour frontier reports counter 1 (runtime item-name
   dispatch) zero, counter 3 (undeclared registry entries) zero, and counter 4 zero for `PAIR_ENGINE` and
   `RECEIPT_WALK`, with counter 2 at or below its declared `NO_RUNTIME_BEHAVIOR` reason count; Phase 4's
   migration frontier reports counters 5–7 at their stage targets. Every counter's exclusion list is
   committed beside it and diff-gated rather than living inside the measuring tool.
8. **One engine prices one mechanic.** One kernel invoked exactly `len(passes)` times per request, one
   `SurvivalAction` constructor, five views none of which re-runs arithmetic, zero mixed-view sums, at most
   one `APPLIED` contribution per `(mechanic, subject, event_id)`, and the pairing divergence ledger empty
   of unreceipted rows.
9. **The public schema is derived.** `PARTICIPANT_LEDGER_CONTRACT["phases"]` is computed from
   `TransitionRank` with no hand-listed member — including the one published name no transition produces,
   carried by the `TERMINAL` rank — and `CAPABILITY_SCHEMA_VERSION` has moved for every change to the
   **published payload** and for no change that leaves it identical. The chain is D-63's and every value
   has exactly one owning commit: `1` at 0A's derivation, `2` at 0B's C4 (`AURA_ARM`), `3` at Phase 3's
   3.8 coverage flip, `4` at Phase 4's S9. No two commits claim one value and no value is skipped.
10. **Declared cast dependencies reproduce the seeds they retire.** Every retired seed's order is derived
    exactly; a single golden diff across the migration means the declaration does not reproduce the seed
    and the seed returns — and a **positive control** on the same commit range proves golden is sensitive
    to that champion's cast order, so "zero diffs" cannot mean "golden is blind".
11. **Governance is closed.** Every decision id above is claimed by exactly one document's *decisions owned*
    line except the eight in the split table, each of which names every one of its halves and the phase
    that owns it; every phase header matches
    the manifest verbatim; no phase document re-rules a decision; no cross-phase number appears in two
    documents with two values; the id-coverage and split-halves clauses are checked by machine against
    the committed `docs/receipts/decision-inventory.json` through `plan_audit.py` (R-37), never by a
    prose read; and every `[H]` is either answered and recorded in this file or its
    dependent slice is explicitly descoped **in this file** with its criterion restated — a phase document
    may not write its own descope. H5 in particular no default can settle; H2 ships its fail-closed default
    and is recorded here as *deferred, default shipped*; H6 ships as Phase 5's dated acknowledged gap.
