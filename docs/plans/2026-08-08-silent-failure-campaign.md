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
| `bloodsong.expose_weakness` | Freeze the divergence behind a `DivergenceReceipt`, then `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` — **refreshed by Amendment D below**; the plain member is unconstructible while the pair pricer stands | Pair and walk are not numerically equivalent; never unify inside a slice labelled a pure refactor. The pair pricer `damage._add_expose_weakness` **survives on the merits** as a `ViewTag.THEORETICAL` preview, and D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` uniqueness is the double-count guard; deleting it is **not scheduled in this campaign** | 3 freezes, 4 corrects |
| `black_cleaver.carve` | `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` — **H1** | The stack ledger is a roster fact; the Cesàro approximation stays pair-side as `THEORETICAL` and may not move in a refactor (`docs/math-foundations.md` §2.3) | 4 |
| `bloodletters_curse.vile_decay` | Same as Carve — **H1** | Identical shape, magic/ability-gated | 4 |
| `horizon_focus.hypershot` | `PAIR_ONLY`, declared | Exclusion set is a pair-local rotation fact; ship it first as the amp-kernel canary, expected no-op | 3/4 |
| `shadowflame.cinderbloom` | `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` | A `LivePredicate`, never a window; the bonus becomes a rider on its triggering event, and the Liandry reprice is extracted in a prior slice. Its walk half is **rider-delivered** under Amendment C above — a `RiderDelivery` stamp, no `packet_source` — and its `Subject` is the holder, so it is **not** a cross-participant producer and the ruled producer count does not move when it is declared | 4, last |
| `force_of_nature.steadfast` | `COUPLED_AUTHORITATIVE` — the stack ledger reads **any roster attacker's** magic damage and CC into the holder (`survival/transitions.py::update_combat_state` keys on `action.attacker`), a roster input under the rule three lines above; the earlier `PAIR_ONLY` reading contradicted both that rule and C5's own receipt-walk blast radius, and is retired | D-08's predicate widening is unchanged. The pair engine's `defensive_effects` DefenseSource schedule is **a distinct surface, not a preview of the coupled number** — it feeds the single-attacker TDD estimate, which is never a score or BIS input, asserted once, structurally. No Phase 4 tagging work exists for this mechanic and none is created here | 0B |

> **Amendment D — 2026-08-13, `bloodsong.expose_weakness`'s member.** The S7 lane landed
> `COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW` where this table ruled `COUPLED_AUTHORITATIVE`, recorded
> the divergence rather than absorbing it, and referred the choice up — correctly, because the two
> ways out were "refresh the table" and "schedule the pair pricer for deletion", and an
> implementation lane may pick neither. The measured reason the ruled member does not build:
> *"`item_support_effects._check_cross_participant_authority` resolves a `damage_modifier` packet's
> authority through `trigger_stream.CROSS_PARTICIPANT_AUTHORITIES`, whose three members are the ones
> that say a second engine can see the mechanic. Bloodsong's pair pricer (`damage._add_expose_weakness`)
> still exists — golden pins it and deleting it is a pair-engine change this slice does not make — so a
> second engine does see it, and declaring otherwise makes the packet fail to build at runtime."*
> **Ruling:** the table's entry is **refreshed to the constructible member**. The pair pricer survives
> **on the merits** — the pair-engine golden pins it — as a `ViewTag.THEORETICAL` preview, which is the
> same rev-2 pattern already ruled for Abyssal's `magic_amp` and Command's `_apply_command_amp`, with
> D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` uniqueness as the double-count guard rather
> than deletion. The row's binding obligation is unchanged and was met: nothing was unified, one side
> is named the answer and the other is tagged and excluded from every roster total. **Deleting the pair
> pricer is explicitly NOT scheduled in this campaign** — it is an unbudgeted slice that would move the
> pair golden, and no phase may adopt it by implication. Consequently the rev-1 retirement row below
> reads **three** surviving pair-side halves rather than two; that row's own ruling is untouched.

### Contradictions this revision resolves

| Claim as written | Verified | Ruling |
|---|---|---|
| Golden holds a fixed scenario-entry count, stated in prose | **The figure reproduces under no definition** | The figure is **retired campaign-wide and is not restated here**. Every golden shape number is emitted by `golden_snapshot.py fingerprint` (Phase 0A) into `docs/receipts/campaign-fingerprints.json`, which is its **sole home**. No campaign document states a golden leaf or entry count — including this row, deliberately: a doc figure a reader cannot regenerate is exactly how the retired one survived, so repeating it as a warning would re-seed it |
| "Five dual-sided mechanics" produce `damage_modifier` | **Six.** `item_support_effects.py` emits `kind="damage_modifier"` at six sites; the sixth is `Dream Maker — Blue Dream Bubble`, which carries no `owner` and is a cross-participant modifier outside every phase contract | D-07. The machine check keys on the semantic, not on `all_sources=True` — which three of the six producers (Black Cleaver, Bloodletter's Curse, Dream Maker) do not set |
| Four bench fingerprint triples pin performance | Only `public_evaluations` is emitted today; measured proposals, score-memo misses and pair `run_fight` counts have **no producing tool and no committed artifact** | Three quarters of the performance contract is unmeasurable until Phase 0A builds the instrument; no phase may cite those numbers as a baseline before then ([runbook](silent-failure-runbook.md), R-06/R-07) |
| Golden is the campaign's safety net | `golden_snapshot.py` calls only `pipeline.run_fight` — no roster, no coupled walk, no `score_only`, and it rounds to 2 dp | D-93. Golden proves no pair-engine leak and nothing else; the coupled baseline is built in Phase 0A |
| Phase 5 rides on Phase 3's vocabulary | It does not — `cast_dependency.py` is a stdlib leaf and Phase 5's only shared file is a different function in `pipeline.py` | Phase 5 runs in parallel from the first barrier |
| Shrinking the enriched-view set is inert | Fimbulwinter reads `_event_id`, which exists only on enriched rows; dropping it disarms a fail-closed raise | D-03. The enriched-view set is one member larger than the claim assumed; its membership is enumerated once, in Phase 2's `enriched_view_items` docstring |
| **Rev 1's Phase 4 end state**: the pairing registry empties and is deleted, ending the `owner` handshake entirely | **Three pair-side halves survive on the merits** — `abyssal_mask.unmake` keeps `magic_amp` because golden pins it, `_apply_command_amp` is kept as a `THEORETICAL` preview rather than deleted, and Amendment D keeps Bloodsong's `_add_expose_weakness` on exactly those terms | **The end state is deliberately revised, not met**, and this row is that revision's retirement notice. `Pairing` keeps three members with `UNPAIRED_KNOWN_DEFECT` asserted empty (D-92), `SPLIT` stays legal wherever the authority rule's three conditions hold, and D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)` uniqueness test replaces deletion as the double-count guard. What rev 1 wanted from the deletion is carried by criterion 8 below and by Phase 4's criteria 1 and 4; no phase document may restate rev 1's wording as a live end state |

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

> **Amendment C — 2026-08-13, D-07's structural half.** Phase 4's S7 lane measured a contradiction
> between two live rules and refused to resolve it from an implementation lane, which is the correct
> refusal; the ruling is recorded here because a phase document may not amend a decision it does not
> own. Both rules are quoted from the tree the lane measured: `trigger_stream._validate_pairing`
> requires a `PAIRED` walk half to carry a `packet_source` — *"the walk half's packet is what the pair
> half is paired against"* — and `golden_snapshot.cross_participant_producers` treats **any** walk row
> carrying one under a cross-participant `Authority` as a producer of the set this table's D-07 row
> rules and criterion 3 pins. Shadowflame's Cinderbloom is ruled a rider on its triggering event and
> therefore authors no packet, while its declared `Subject` is `HOLDER` — *"it amplifies the holder's
> own magic and true damage on a predicate about the target's live health"* — so satisfying the first
> rule would have enrolled it in the second and edited a ruled count to satisfy a validator.
> **Ruling:** the **structure** is amended, keyed on D-07's own semantic — *every packet modifying
> ANOTHER participant's damage*. A `PAIRED` walk half may be **rider-delivered**: its delivery
> reference is the rider stamp (`pair_preview_of` / the `AmpBonus` source, carried as
> `trigger_stream.RiderDelivery`) rather than a packet source, implemented **within `trigger_stream`'s
> existing fields** — Phase 4's exactly-two-fields rule on `MechanicCapability` stands and no new
> required field is added there. The cross-participant producer derivation moves onto the
> modifies-another-participant semantic, in one home
> (`trigger_stream.cross_participant_packet_source`, which both the packet builder and the baseline
> instrument read): a rider amplifies the event it rides and that event belongs to its own holder, so
> Cinderbloom is **not** a member and D-07's ruled producer count and criterion 3 stand untouched.
> Gated both directions — a rider-delivered `PAIRED` half constructs, and a `PAIRED` half carrying
> neither a packet source nor a rider stamp still fails validation — and the structural commit is
> zero-diff on both baselines. What this unblocks it does not land: the Shadowflame authority move is
> still owed, and the slice that lands it owes the bench-population enumeration before its first `src/`
> edit (R-20's second half), because the lane measured the coupled-golden population as empty for a
> stated reason while the bench population is not.

### D-20 … D-26 — where a failure lands ([Phase 1](phase-1-coverage-evidence.md))

| # | Ruling |
|---|---|
| D-20 | **Load** catches structural impossibility only — a claim whose shape cannot be backed. No imports, no filesystem, no `data/` read; O(n) string and set checks raising `CoverageClaimError` / `TriggerRegistryError` / `DeclaredCycleError`. *Why: a load gate that reads data is a startup cost and a rule-2 violation.* |
| D-21 | **Resolution** (any `pytest` run, including `-k` and bisect) resolves every claim's evidence against the real codebase. *Why: this is the tier that makes the drift window one commit.* |
| D-22 | **Full session** owns exact parametrized ids and duplicate-nodeid detection, gated on a session predicate that **never** calls `pytest.skip`. *Why: a skip takes the tier-1 path and reports green.* |
| D-23 | A coverage refusal is `WITHHELD` — a named receipt and no number — and a new withholding reason extends `champion_optimizer_matrix.EXPECTED_WITHHOLDING_PREFIXES` in the same commit. A withheld item is **excluded from candidate generation and named in the response's `withheld[]`**, never scored as zero; the per-request exclusion count is published and pinned by `champion_optimizer_matrix`. *Why: otherwise CI is red while `pytest` is green — and an unruled withheld item either silently loses BIS a legal build or re-creates the zero this campaign exists to kill.* |
| D-24 | A rule that can legitimately return 0.0 declares `zero_policy=STRUCTURAL_ZERO` with a reason; an undeclared zero arising from an empty stream is a bug by definition and raises. `zero_policy` is **required on `BehaviorRule` and on `damage_entry`/`simple_damage`** — with one ruled exception, written here the way D-52 writes its registry exception: the champion call sites are **not** individually edited. `damage_entry` and `simple_damage` have exactly one construction layer, `champions/slotlib.py` (`:432`, `:652`), and that layer supplies the one declared default — `zero_policy=MEASURED`, because a module formula that evaluates to zero *computed* that zero — overridable per call. **The exception is itself guarded**: a source assertion over `champions/` forbids a `.get(key, <literal>)`-shaped fallback from feeding a damage formula — rule 5's no-stale-literal discipline extended to champion inputs — because a zero produced by an *unwired input* (a stack count or option that never resolved) is the incident's own shape and must fail loud, never be stamped `MEASURED` by the default. Phase 3's criterion 7 carries the assertion. Measured blast radius of the no-exception reading: **397 call sites across 151 champion modules** — every `ast.Call` under `champions/` whose callee spells `damage_entry` or `simple_damage`, excluding `slotlib.py` itself, and pinned by `tests/test_zero_policy.py` so the figure has a producer — which no lane owns and no phase budgets; a required-no-default field there is a campaign-wide champion sweep smuggled in by an idiom. Every numeric leaf produced by neither is enumerated in a committed `zero-policy-frontier` set with an issue ref, asserted non-growing. *Why: this is the invariant, mechanized — and a policy that stops at items cannot discharge a criterion written over every leaf.* |
| D-25 | `ProjectionStarvation(field, producer, reason)` is raised lazily on first read of an inadequate representation. **Exactly one catch exists**, at the request boundary in `src/app.py`, converting it to a 500 carrying the `STARVED` receipt; a source assertion allowlists that single handler and forbids every other. *Why: it means a projection and a consumer disagree — a programming error, not a data condition — but "never caught" makes a reachable one an unhandled traceback rather than a named refusal.* |
| D-26 | Fail-closed branches no real item reaches are proven three ways: the rule is checked on an empty registry, a synthetic fixture exercises each branch, and emptiness itself is a pinned number. *Why: zero ordinary-SR items are ineligible today, so silence would otherwise pass for coverage.* |

> **Amendment G — 2026-08-14, D-25's one catch names a class.** The commit that joined the write-once
> `OutcomeLedger` to the receipt walk gave three `RuntimeError` subclasses a path to every serving
> request — `OutcomeRewritten` at two sites, `DuplicateApplied`, and `UnwrittenAdjustment` beside them
> — and D-25's boundary names `ProjectionStarvation` alone. So a condition that used to resolve
> silently as last-write-wins became a **bare 500 with no receipt, no disposition and no named field**:
> the campaign's own failure shape, created by the commit that removed the campaign's own failure
> shape, and filed as such at `docs/receipts/escalated-defects-ledger-join.json`. Two readings of D-25
> were available and an implementation lane could take neither, because one widens a rule stated in the
> singular and the other absorbs a raise that exists to refuse the last write.
> **Ruling: D-25's "exactly one catch" is a rule about *where*, and never a count of the exception
> types that one handler names.** Its load-bearing half is that a named refusal is converted in one
> place and absorbed in none, and that half is untouched. The disposition is `STARVED` and **the
> invariant table owes no fifth spelling**: `STARVED` is *a projection could not answer the question a
> rule asked — a programming error*, and a ledger holding two answers for one question, or two applied
> contributions for one `(mechanic, subject, event_id)`, is a record that cannot answer either. The
> leaf has no value a rule computed, which is the whole of what the word means. Structurally, the
> class is named rather than enumerated at the catch: `ProjectionStarvation`'s base is the class of
> programming errors that surface as a `STARVED` leaf on a request, every member carries `field`,
> `producer` and `reason`, the ledger's raises join it, and the one request-boundary handler converts
> the base. The source assertion that allowlists exactly one handler and forbids every other is
> unchanged in force and now ranges over the class. **What stays forbidden**: catching any member
> anywhere else, and any handler that returns a served payload — the conversion is a 500 carrying the
> `STARVED` receipt, so a contested number is refused by name and never quietly re-answered.

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
| D-68 | Every float `phase` the compiler and the timeline write consumes `TransitionRank` in the same commit as the ladder: `program/compile.py:314` (the `action_key` phase argument), `:608`, `:837` (the inline sort tuple's second element), `:944`, `:1001`, and `participant_timeline.py:2767` — the five compiler sites were `survival/compile.py`'s until Phase 4 S4 moved the one constructor. *Why: otherwise the compiled path desyncs and only the equivalence suite can see it — and the two originally named were not the whole surface.* Landed in 0A; Phase 4 only deletes `legacy_phase`. |
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
| **H1** | Move Carve and Vile Decay to coupled-authoritative with pair preview | Moves BIS winners on real builds; the Cesàro approximation is documented balance-sensitive | **Unanswered; the dependent slice is descoped here, and criterion 11 requires the criterion restated rather than the shipment described.** Phase 4's mechanic stage ships **four of the seven authority moves** (Hypershot, Abyssal, Bloodsong, Shadowflame); Carve and Vile Decay hold for H1 and Command for H2. The dependent criterion is [Phase 4](phase-4-program-engine.md)'s criterion 11, and under this deferral it is read as it is written and not more weakly: *authority is declared for all seven moves, four land, and Command, Carve and Vile Decay each carry their blocking `[H]` id in the capability row rather than a guessed ruling.* Discharging it means the declaration and the `[H]` id are present for all three held moves — never that three moves are absent from the registry, and never that the four that landed stand in for seven. The two H1 rows of *Semantic authority* above keep saying `SPLIT` for `black_cleaver.carve` and `bloodletters_curse.vile_decay` for exactly as long as this row is unanswered, and answering H1 later re-opens the two moves as their own slice with its own `Expected qualifying occurrences` line; it does not retroactively change what Phase 4 shipped |
| **H2** | `CcScope` for Syndra E — how many roster targets does one cone stun, and on what source | Needs a sourced wiki reading with a target cap; today's answer is a construction accident of running the rotation once per defender | **Recorded ruling, 2026-08-13, at Phase 4 S7: *deferred, default shipped*.** H2 was unanswered when S7 opened, so the conditional this row carried is now the standing ruling and no longer conditional. Command stays `SPLIT` and its authority does **not** move in Phase 4; `CcScope.Unreviewed` resolves to `SingleTarget` on the pair defender with a disclosure naming the ability; and `HolderStacking` fails closed to `PER_HOLDER`, written into `imperial_mandate.command`'s capability row beside the `[H]` id rather than as an unremarked fall-through — the field has no default to fall through to. Answering H2 later re-opens the move as its own slice with its own `Expected qualifying occurrences` line; it does not retroactively change what S7 shipped |
| **H3** | Does amplification count as support value in the utility objective | A Mandate holder contributes ~0.07 points where a Locket holder contributes hundreds of HP, because a unitless multiplier is summed with health | **Unanswered; the dependent slice is descoped here, and the criterion is restated rather than the sentinel described.** Nothing blocks, because no criterion of any phase asserts that the objective's units agree. The dependent criterion is **D-14**, three rows above: *`support_value` unit mixing is pinned by a characterization test and excluded from every coverage expectation.* Under this deferral that reads exactly as written and no more — the test pins **what the objective does today**, mixing included, and is discharged by reproducing it rather than by anyone finding it right. The exclusion is the load-bearing half: a coverage expectation that counted the mixed sum would report the objective as covered, which would turn an open product question into a discharged one by arithmetic. Answering H3 re-opens the objective as its own slice, re-writes the characterization test to the answered units, and carries its own `Expected qualifying occurrences` line; until then no phase may cite the utility objective's units as settled |
| **H4** | Delete the **four** dead effect tags (`conditional_attack_speed`, `shield_reduction`, `target_state`, `target_attack_speed_aura` — read nowhere in `src/`) and make defensive dispatch consume the **six** self-referential ones (`defensive_start`, `stat_conversion`, `sustain`, `target_mitigation`, `target_threshold_health`, `target_threshold_shield` — read only by the `item_coverage` claim that cites them, while the behaviour is reached by item name) | A data-declaration edit whose only current reader is the sentence justifying it; renaming a tag silently reclassifies items with zero test signal | **Unanswered; the dependent slice is descoped here, and both dependent criteria are restated rather than the frontier described.** Ten tag-claims sit on Phase 1's frontier with explicit reasons; Phase 3 enumerates the members, and this row and Phase 3 must not disagree on which four and which six. The dependent criteria are [Phase 1](phase-1-coverage-evidence.md)'s criterion 11 and [Phase 3](phase-3-behavior-rules.md)'s ten-tag ruling, and under this deferral both are read as written and not more weakly. Phase 1's: *each of the 38 known effect types either resolves to a handler branch outside the claim system or sits in `FRONTIER` naming H4; the union is total.* Totality is the whole clause — a tag that is neither dispatched nor on the frontier naming H4 is a failure, so deferring H4 removes nothing from that criterion and only fixes which arm the ten take. Phase 3's: the four dead tags are **declared, not deleted**, and the six self-referential ones are carried in families with an explicit reason each, so the frontier holds a reason per tag rather than a silence. Answering H4 is a slice that deletes four declarations and converts six self-references into real dispatch, with its own `Expected qualifying occurrences` line; until then no phase may cite the tag set as reduced |
| **H5** | **Scope the compiled-kernel extension** — timed, typed damage modifiers (D-101) | Multi-week and unbudgeted; it decides whether the compiled lane and the performance thesis are achievable at all | **Recorded ruling: SCOPED.** The compiled kernel *is* taught timed, typed damage modifiers (D-101), and the scoping is recorded here because no phase document may write its own H5 disposition. It is folded into no existing stage: the extension **lands as its own stage after Phase 4 S7, with its own equivalence fixture**, and the flip from `ReceiptOnly` to `Compilable` is that stage's one-symbol commit under D-98 — the compiled declaration lands beside the legacy `ReceiptOnly` one with an asserted delta, and the flip is its own revert unit. The dependent criteria, restated as criterion 11 requires: **Phase 3's criterion 16 is UNCHANGED in this branch** — every `delta_amp` rule still declares `ReceiptOnly` carrying the compiled-kernel reason and the phase's compiled-lane claim still reads "declared empty, fallback receipted", discharged by the declaration and never by an unstated absence, because scoping H5 **adds a later stage and does not relax Phase 3**; **Phase 4's criterion 16 is read under this scoped ruling** — through S7 it reads exactly as written, no criterion of that phase asserting a compiled amp and every `damage_modifier` holder reporting `RECEIPT_WALK` with a named receipt, and it is re-read against the compiled lane only **once the new stage's flip lands**, on the evidence of that stage's equivalence fixture rather than on this ruling alone. Consequences under D-101 hold unchanged for everything before that flip: every amp holder falls back to the receipt walk, an amp-holding roster ally takes a fallback rung with a named cause rather than compiling (D-69), and the performance thesis that assumed a compiled amp lane **may not be cited as achieved by any phase** until the stage has landed and its fixture is green |
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
   survival, TDD and timeline — **and of `/api/bis` (`app.py:524`) and `/api/optimize` (`app.py:1429`), the
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

   > **Amendment E — 2026-08-14, how a disposition transition is adjudicated.** This criterion's
   > emission clause stood open for one reason, and it was not effort.
   > `docs/receipts/escalated-defects-P4-S9.json` measured the change that closes it — the receipt view
   > publishing a refused transition's outcome fields as `StructuralZero` carrying the walk's own
   > refusal, in place of a `Measured` zero — and found every occurrence classified `text_change` by
   > R-15, which R-19 then sends to an investigator R-18's export cannot brief: `data/` and
   > `docs/math-foundations.md` hold no cached wiki text and no formula that decides whether a zero the
   > walk refused is `MEASURED` or `STRUCTURAL_ZERO`. That is a question about *this document's own*
   > vocabulary — the four spellings in the invariant table above — and the export exists to keep
   > exactly that out of an investigator's hands. The runbook's R-15 amendment of 2026-08-14
   > adjudicates by citation only a **membership** transition and says in its own words that it does
   > not reach a disposition string, so the shape has no rule and the slice had no legal landing.
   > **Ruling: a disposition transition is adjudicated by citation, not by verdict.** A disposition
   > transition is a diff on an entry of a payload's parallel `dispositions` map — the `disposition` or
   > `view_tag` string, or the `reason` / `receipts` key that arrives beside it — and its allowlist
   > entry names the ruling that moved it, which is then the receipt. No oracle receipt is owed on one,
   > and one may not be filed as though the question were a value question. Three guards bound it, and
   > the third is this amendment's own contribution rather than a copy of the membership rule's:
   >
   > 1. The diff must be on a `dispositions` entry **as the identity-keyed `leaf_report` classifies
   >    it**, so a payload value that moved cannot be re-spelled as a change of vocabulary.
   > 2. The cited ruling must be one a reader can open — a decision id, or a committed slice receipt
   >    naming the declared change — never "ruled elsewhere". D-72 names the single writer and the
   >    invariant table names the four spellings; a citation naming neither names nothing.
   > 3. **The leaf the entry describes may not move.** An allowlist claiming a disposition transition
   >    states, path by path in that same allowlist, that the described leaf's own published value is
   >    identical on both sides. A number that moved is a value question, owes its investigator under
   >    R-19, and no citation reaches it. This guard is the whole difference between a rule and a
   >    loophole: the only thing citation can ever excuse here is a change in what the payload *says
   >    about* a number that did not change.
   >
   > Consequences, stated so that no lane has to infer them. The emission slice lands as one commit
   > against the committed coupled baseline plus its committed allowlist (R-17), owing no oracle
   > receipt and moving no baseline. `docs/receipts/rulings-owed.json`'s first row closes naming this
   > amendment. And criterion 7's Amendment B exit clause stops being *blocked* by this question —
   > which is not the same as being discharged by it, and Amendment F below is where that debt is
   > answered.
   >
   > **Amendment I — 2026-08-14, this criterion's frontend change budget.** The clause
   > "`static/js/app.js` takes exactly one budgeted change at S9" is false and was false unremarked:
   > three commits in the campaign range touch that file — `bf4a6d3`, `44331c7` (the withheld-marker
   > helper this clause names) and `f25dcfa` (a row-classification refactor) — and nothing counted
   > them until the closing pass did. Two ways out were available and a lane could take neither:
   > amending a criterion is not a lane's to do, and reverting shipped, tested rendering behaviour so
   > that a budget sentence comes true is the sentence-over-code ordering this whole campaign exists
   > to invert. **Ruling: the clause is amended to what shipped, and gains the property it was
   > reaching for.** What the budget was protecting is that the frontend does not quietly acquire a
   > rewrite under cover of a payload change — not the integer one. So the clause now reads: *every
   > commit in the campaign range touching `static/js/app.js` is named here with its reason, and a
   > commit that is not named is a budget overrun.* The three are named above, each with its
   > reason: `bf4a6d3` reads the `dispositions` map the same stage began publishing, `44331c7` is the
   > withheld-marker rendering helper this clause names, and `f25dcfa` gives "which row is an enemy"
   > one home in the script in place of three re-derivations. All three are S9's, and all three serve
   > the one property the clause protects. A fourth arriving unnamed is what this now catches, which
   > the integer never did.

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

   > **Amendment H — 2026-08-14, a leaf's own adjudicating receipt.** The non-plan half of this
   > criterion stands measured and unmet, at eleven forced restatements across six sources
   > (`docs/receipts/golden-figure-sole-home.json`, gated by `scripts/sole_home_scan.py --check`), and
   > every one of them is forced by another rule of this campaign rather than by anybody's
   > carelessness: R-19 makes an oracle receipt state the two values of the leaf it adjudicates, R-17
   > makes an allowlist state the expected old and new value of every path it claims, and R-34 makes a
   > baseline-move commit give one line of cause per moved value. The `/metadata/fingerprint/*` leaves
   > are themselves leaves of the snapshot, so a receipt adjudicating one **cannot** be written without
   > quoting it, and seven of the eleven are in commit bodies, which are history no edit reaches.
   > **Ruling: this criterion carves out a leaf's own adjudicating receipt**, on three conditions that
   > together keep the carve-out from becoming a second home. The restatement must sit inside an
   > artifact adjudicating **that exact leaf** — an oracle receipt, an R-17 allowlist entry, or the
   > body of the commit that moved it; it must name the leaf **by its path**, so a reader reaches the
   > receipt rather than a figure; and it must agree with the committed receipt, or declare, in the
   > same artifact, the entry it supersedes. What is carved out is a *quotation at its address*, which
   > is the opposite of a second home: a second home is a figure a reader cannot trace, and that is
   > what the retired one was. Everything else the criterion forbids stays forbidden, and the
   > distinction is not left to a reader — `sole_home_scan.py --check` holds the residue at zero
   > unexplained sites, fails on a twelfth, and fails on a row that outlives the site it explains.

5. **Every gate means what it says.** All eleven rows of R-01 in the
   [runbook](silent-failure-runbook.md) are green at every phase boundary; zero pair-engine golden diffs
   outside a slice that declared them in advance with an oracle receipt per qualifying occurrence.

   > **Amendment J — 2026-08-15, how a campaign-authored justification string is adjudicated.**
   > *Answers `how_a_campaign_authored_justification_string_is_adjudicated` in
   > `docs/receipts/rulings-owed.json`, the one docketed dissent whose remedy was never an
   > investigation.* This criterion's oracle-receipt-per-occurrence clause meets a leaf it cannot
   > mean what it says about. Phase 3's coverage-evidence step reworded an item's coverage reason
   > from *"the represented mechanic changes defense, not outgoing TDD"* to *"Every declared family
   > on this item is a defence: the represented mechanic changes durability, not outgoing TDD"*;
   > R-15 classified the reword a `text_change`, R-19 sent every occurrence to an investigator, and
   > R-18's export is `data/` plus `docs/math-foundations.md`. Twenty-four receipts adjudicate that
   > one pair of strings. Twenty-three certified the new one. The twenty-fourth,
   > `oracle-P3-3.8-leaf24.json`, certified the old one, and its own limitations block says why in
   > its own words: it read *"Every declared family"* against the family vocabularies that exist in
   > the cache, found no `defence` family there, and recorded that **a code-level family vocabulary,
   > if one exists, was out of bounds for this runbook and was not consulted**. One exists.
   > `item_behavior.RuleFamily` groups its members, `item_coverage` names the defence group, and
   > `item_coverage.declares_only_defence` is the predicate *the declared family set is non-empty
   > and contained in that group* — literally the sentence, evaluated.
   >
   > **Ruling: a campaign-authored justification string that asserts a fact about `src`-level
   > vocabulary is adjudicated by SOURCE ASSERTION — a machine check binding the string to the
   > predicate that produces it — and never by an R-18 investigation, whose export excludes `src/`
   > by design.** Two halves follow and both are the ruling, not commentary on it. An oracle verdict
   > on such a string is valid **only for its export-verifiable portion**: a verdict that turns on a
   > vocabulary the verdict's own limitations block declares out of bounds does not sustain a
   > dissent, because it is a reading of a question the export was built not to be asked. And the
   > string **may** assert the `src`-vocabulary fact, because the machine check is what keeps it
   > true — this campaign's own prose-must-not-outrun-code mechanism, turned on prose. A sentence
   > bound to the branch that emits it cannot become false without a gate going red, which is
   > strictly more than an investigator reading the cache could ever certify about it.
   >
   > Three guards bound it, in Amendment E's shape, and the third is what keeps it from swallowing
   > R-18's jurisdiction:
   >
   > 1. **One producer, named.** The string must be emitted at exactly one site in `src/`, and the
   >    check must bind *that* site's own predicate. A check asserting the sentence of a hand-listed
   >    set of items is not a source assertion; it is the name list this repository already forbids,
   >    wearing a test's clothes.
   > 2. **Total over what the sentence quantifies over.** *"Every declared family"* is a universal,
   >    so its check ranges over every cached item the producer can be asked about, in both
   >    directions — an item published with that reason declares only defence families, and an item
   >    declaring only defence families and carrying no more specific receipt is published with that
   >    reason. A sample of named items measures the examples somebody thought of.
   > 3. **Only the `src`-vocabulary claim is carved out.** Whatever such a string asserts about the
   >    cached corpus stays R-18's, and an adverse verdict on that portion is a value question that
   >    owes its remedy under the R-15/R-18 amendment exactly as before. Here the operative clause —
   >    a durability mechanic does not change outgoing TDD — is the export-verifiable portion, and
   >    the receipt certifies it **on both sides**: it is the added universal, and nothing else, that
   >    this ruling reaches.
   >
   > Consequences, stated so no lane has to infer them. `oracle-P3-3.8-leaf24.json` **stands exactly
   > as filed** — not re-run, not re-graded, not withdrawn; it is answered rather than superseded,
   > which is why no receipt supersedes it. Its `open_debt` row in
   > `docs/receipts/standing-dissent-adjudications.json` closes per that ledger's own rule as a
   > `citation` naming this amendment, and the docket cluster routed here leaves `clusters` by being
   > answered. The twenty-three-receipt majority stands and is **not** re-rolled: a re-run cites a
   > defect in the brief it replaces and there is none to cite. No baseline moves, no `src/` moves,
   > and the string does not move. What lands instead is the ruling's own premise, enforced rather
   > than assumed: the source assertion guard 1 and guard 2 describe, as a test, so that the day the
   > defence group or the ladder changes under the sentence, a gate goes red instead of a receipt
   > going stale.

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

   > **Amendment A — 2026-08-12, counter 2's clause.** A migration lane measured this clause
   > unreachable as written and refused to resolve it from an implementation lane, which is the
   > correct refusal; the ruling is recorded here because a phase document may not write its own
   > descope. The arithmetic: [Phase 3](phase-3-behavior-rules.md)'s criterion 14 blesses two
   > surviving name-keyed containers — `item_coverage.NO_RUNTIME_BEHAVIOR`, 21 sites, and
   > `_REVIEW_ISSUE_REFS`, 22 — and **21 + 22 = 43**, already over the bound of **21** those same
   > 21 sites are the count of; on top of that, [Phase 1](phase-1-coverage-evidence.md)'s
   > **authored** claim-evidence corpus contributes **203** further sites in the same module, which
   > may neither be derived (deriving evidence from the registries it describes makes Phase 1's
   > resolution check tautological, which is the failure that module exists to catch) nor retired
   > (Phase 1 mandates them). **Ruling:** counter 2's committed Class C exclusion set gains
   > (i) Phase 1's authored claim-evidence corpus containers — typed, machine-resolved declarations
   > under the resolution tier (D-21), which is precisely the cannot-drift-silently property
   > counter 2 exists to enforce, so they are not claim prose — and (ii) `_REVIEW_ISSUE_REFS`,
   > criterion 14's own blessed survivor, which carries issue references and not coverage claims.
   > The target is unchanged in wording — *counter 2 at or below the reviewed `NO_RUNTIME_BEHAVIOR`
   > reason count* — and is measured **net of the committed Class C exclusions**, which live in
   > `docs/behavior-frontier.json` and are diff-gated by set equality, never inside the measuring
   > tool (D-40). Measured on the commit that lands this: the two arms exclude **225** sites, the
   > counter reads **24** against a bound of **21**, and the residual **3** are
   > `bis.BIS_CERTIFIED_DEFENSIVE_EFFECTS` — neither corpus nor issue reference, so they stay
   > counted and the clause stays a live gap rather than a discharged one.
   >
   > **Amendment B — 2026-08-12, counter 4's clause.** The enumerated `RECEIPT_WALK` `(family, lane)`
   > gaps whose numbers arrive today through the pair engine's timed rows, and which only
   > [Phase 4](phase-4-program-engine.md)'s S3 `OutcomeLedger`/end-of-walk projection can retire,
   > become **committed, diff-gated deferral rows** on `docs/behavior-frontier.json`. Each row names
   > the gap, the reason its number is not a silence, and Phase 4 S3 as the retiring stage; a row
   > naming a gap the tree no longer holds, or a stage the tree's own receipt does not say, fails the
   > gate. Counter 4's Phase-3 exit target is **0 net of those recorded deferral rows**, and Phase 4's
   > exit re-asserts them retired. Measured on the commit that lands this: **14** deferral rows, all
   > on `RECEIPT_WALK`, all retiring at Phase 4 S3; `PAIR_ENGINE` defers nothing.
   >
   > **Amendment F — 2026-08-14, the retiring act Amendment B named does not exist.** Amendment B's
   > second sentence — *Phase 4's exit re-asserts them retired* — went undischarged at Phase 4's exit,
   > and the reason is that its first sentence is false against the tree. Amendment B says the rows
   > are the ones *"only S3's `OutcomeLedger`/end-of-walk projection can retire"*. Measured: a
   > `(family, RECEIPT_WALK)` row retires when `interpreters.INTERPRETERS` holds that key, and nothing
   > about projecting a ledger's quantities onto a payload leaf registers one. The retiring act is a
   > **per-family receipt-walk interpreter** — the walk pricing that family itself instead of
   > consuming the pair engine's timed rows — which is a behaviour change per family, on the fourteen
   > families whose numbers `participant_timeline._pair_run_fight` produces today. No phase budgeted
   > fourteen of those, and a clause resting on a mechanism that cannot perform it is corrected rather
   > than carried. **Ruling, in H6's shape, and it is a debt restated at its true size and not a
   > relaxation:** the fourteen rows stand as a dated acknowledged debt. Each names its gap, its
   > route (`via`, structurally validated — a route to a lane no interpreter serves already fails at
   > import), its true retiring act, and its blocker; each is `overdue` and says why; the committed
   > set is diff-gated by set equality; a row that outlives its gap, names a stage the tree does not
   > declare, or drops its blocker fails the gate. Amendment B's second sentence is superseded by
   > this one: **Phase 4's exit re-asserts that every row is either retired or carried with a named
   > retiring act, a named blocker and a machine that refuses a fifteenth** — the three facts a
   > reader needs to schedule the work, in place of a promise the named stage could not keep. What is
   > *not* ruled here: that the debt is acceptable. Retiring it is fourteen slices, one per family,
   > each carrying its own `Expected qualifying occurrences` line, and no phase document may read
   > this amendment as permission to stop counting them.
   >
   > **Amendment K — 2026-08-15, the retiring act is named per lane, not per walk.**
   > *Answers `what_retires_a_receipt_walk_deferral_whose_route_is_not_the_pair_engine` in
   > `docs/receipts/rulings-owed.json`, the seventh row that ledger opened and the one Amendment F
   > left behind it.* Amendment F names one retiring act for all fourteen rows and describes them all
   > as *"the families whose numbers `participant_timeline._pair_run_fight` produces today"*. Measured
   > against the frontier's own `via` declarations by
   > `docs/receipts/receipt-walk-retirement-schedule.json`, that description is true of eleven.
   > Three — `combat_state`, `opening_defense`, `threshold_defense` — declare `DEFENSE_RESOLVER`
   > instead, and their rows say in their own words that a walk-lane interpreter there *"would be a
   > second producer of one number"*, which is exactly what D-60 and criterion 8 forbid. Read as *a
   > **receipt-walk** interpreter*, Amendment F's act therefore names, for those three, the act the
   > campaign rules out.
   >
   > **Ruling: the retiring act for every one of the fourteen rows is a per-family interpreter in the
   > family's own declared serving lane** — `RECEIPT_WALK` for the eleven the pair engine feeds,
   > `DEFENSE_RESOLVER` for the three the resolver feeds, and in general whichever lane that row's
   > `via` names. Amendment F's act is neither narrowed nor widened; what is corrected is the lane it
   > was spelled with, which was read off eleven rows and written over fourteen. The property being
   > discharged is one property and it is criterion 8's own: **the family's numbers reach the walk
   > through exactly one interpreter, in the lane the family declares, instead of arriving already
   > priced by the pair engine.** Spelled that way the act *serves* D-60 rather than colliding with
   > it — a resolver interpreter is not a second producer of one number, it is the one producer, and
   > the walk consuming what it built is the one-engine property holding rather than breaking.
   > `delta_amp` is answered by the same sentence and needs no separate one: its structured `via` is
   > `pair_engine`, so its ruled act is a receipt-walk interpreter; the second route its prose names
   > is the `damage_modifier` packet, and prose naming two routes does not move a gated declaration —
   > the declaration is the route (D-40), and correcting `via` would be a behaviour claim owing its
   > own slice rather than a schedule's edit.
   >
   > **What this ruling does not do**, each of which was available and is refused. It registers no
   > interpreter that emits fields nothing consumes: a counter driven to zero by editing what it
   > counts is worse than the gap. It does not touch `_FAMILY_LANES`: the three families still
   > declare a receipt-walk lane, so counter 4 still counts them, and an exclusion driven from
   > inside the thing it excuses is D-40's exact prohibition. And it does not read Amendment F's
   > fourteen as eleven. Measured on the commit that lands this, `INTERPRETERS` already holds
   > `(COMBAT_STATE, DEFENSE_RESOLVER)`, `(OPENING_DEFENSE, DEFENSE_RESOLVER)` and
   > `(THRESHOLD_DEFENSE, DEFENSE_RESOLVER)`, so for those three the ruled act is already performed
   > and the one-engine property is discharged today — which is a fact about the tree and **not**
   > permission to stop counting: all fourteen rows stand, `overdue` and gated, the machine still
   > refuses a fifteenth, and the eleven are still eleven slices no phase has budgeted.
   >
   > **The rows' recorded retiring stage is refreshed** from *Phase 4 S3 — one kernel, five views*,
   > which Amendment F measured cannot perform the act, to this closeout, dated `2026-08-15` and
   > citing Amendment F as the measurement behind it. The stage record the deferrals name said in
   > its own words that *"re-dating them is a ruling and not a lane's edit"*; this is that ruling.
   > Re-dating changes what the rows are overdue **against** and nothing about whether they are
   > overdue: the closeout has shipped, it did not retire them either, and every row stays `overdue`
   > with a blocker a reader can open. A stage that made the rows read as on schedule would be the
   > debt getting smaller by being re-dated, which is the one thing a re-dating may not buy.
   >
   > **Amendment L — 2026-08-15, the full shape of a retirement act, and the three prerequisites
   > it needs.** Amendment F sizes the debt at fourteen slices; Amendment K settles which lane each
   > one is spelled in. Neither says what one slice *contains*, and a retirement lane that went to
   > start the first of them measured why that is not a detail: retiring a `(family, RECEIPT_WALK)`
   > deferral takes **both halves at once**. The walk has to price the family through the
   > interpreter in that family's declared lane, **and** the pair engine's rows for that family have
   > to become previews — the producing site stamping `pair_preview_of`, the mechanic declaring
   > `ViewTag.THEORETICAL` on its pair lane, which is the two-sided join `program.build`'s
   > `pair_preview_sources` reads and which D-62's one-`APPLIED`-per-`(mechanic, subject, event_id)`
   > uniqueness backs. Either half alone is worse than neither: the interpreter without the stamp
   > prices the family twice into one roster total, and the stamp without the interpreter deletes
   > the family's number from every total that used to hold it. That is why the act is ruled as one
   > slice and not as a sequence of tidy ones.
   >
   > **Ruling 1 — the retirement act is one behaviour slice per family**, and it carries all of:
   > the family's `MechanicCapability` declarations authored; its pair rows stamped
   > `pair_preview_of` and declared `THEORETICAL`; the lane interpreter landed and wired to the
   > pricing path; and the deferral row retired. In that same slice, and this is the half that makes
   > it a behaviour change rather than a registration: the family's **numeric consequence** — the
   > pair row leaving the roster total, the walk's own number entering it — its
   > `Expected qualifying occurrences` line with the qualifying population enumerated from that
   > family's covering scenarios **before the slice's first `src/` edit** (R-20's second half), and
   > the oracle receipt every qualifying occurrence then owes (R-19). One correction per commit
   > still binds inside the slice (R-30), and no baseline moves inside any of its semantic commits
   > (R-17, R-32, D-97).
   >
   > **This is not a D-40 exclusion**, and the distinction is the whole of why the act is legal to
   > perform. A capability authored so that counter 4 stops counting a row, while the walk goes on
   > consuming the pair engine's timed rows for that family, would be a counter driven to zero by
   > editing what it counts — the move Amendment K refuses in three places and the one D-40 exists
   > to forbid. What is ruled here is the opposite shape: every declaration arrives carrying the
   > number it moves and the receipts that adjudicate the move, in the slice that makes it, so the
   > counter falls because the tree changed and not because the declaration did.
   >
   > **The capability declarations are the closeout's to author, as a sequential handoff.** The
   > runbook's ownership map gives `trigger_stream.py` to L2 and carves the two Phase-4 capability
   > fields out to L5 — and it says in its own words that a carve-out on a file whose earlier owner
   > has already merged is a sequential handoff rather than a concurrent share. L2 merged long ago
   > and L5 with it; the map is a **liveness rule about who may write concurrently**, not a
   > permanent title, and the closeout inherits `view_tags` and the declarations beside it on
   > exactly the terms L5 held them. No lane is live to collide with.
   >
   > **Ruling 2 — the covering scenarios land first, and they are an R-12 integration act.** Nine of
   > the fourteen families have no committed coupled scenario putting one of their owners on a
   > participant; the set is enumerated in `docs/receipts/receipt-walk-retirement-schedule.json`,
   > gated by `tests/test_receipt_walk_schedule.py`, and each of those rows already publishes a
   > population of zero with the reason it is a declared emptiness and not a clean bill. Against
   > that emptiness no leaf can qualify, so the slice's R-20 line reads zero, no investigator is
   > ever owed, and the re-pricing ships unseen — which is the campaign's own founding failure shape
   > wearing the campaign's own gate as a disguise. **So the covering scenario lands first, as its
   > own act**: the coupled producer set is read rather than typed (R-12), adding a scenario moves
   > the committed coupled baseline, and a baseline moves in the integration agent's own commit and
   > never inside a semantic slice (R-17, R-32). Scenario, then re-capture, then that family's
   > retirement slice — which now has something to be seen in.
   >
   > **Ruling 3 — the from-declaration pricing path is the engine stage Amendment F said no phase
   > had budgeted, and it is hereby budgeted.** Measured on the commit that lands this: three
   > registered interpreters serve the receipt walk, and only one of them — the reactive family's,
   > the strike-back — hands the walk a damage number priced from a raw declaration. The other two
   > compile the fields the walk itself pays out and the numbers a packet producer declares. Every
   > deferral family's damage still arrives as `participant_timeline._pair_run_fight`'s
   > post-mitigation rows, which the walk re-ratios and, where it cannot recover the pre-mitigation
   > side, refuses by name rather than inventing a ratio. A per-family interpreter therefore has
   > nowhere to hand its price. The stage is one engine stage: a family's declaration priced into
   > the walk's own ledger. It **lands before the first family that needs it**, it carries its own
   > equivalence fixture — the from-declaration price against the pair-ratioed one, on a family that
   > has not yet opted in, so the stage is provably a re-spelling before it is ever a re-pricing —
   > and it is **inert until a family's retirement slice opts in**, which is what keeps it from
   > being a behaviour change smuggled in under an infrastructure heading.
   >
   > **What this amendment does not do**, each available and refused. It retires no row: all
   > fourteen stand, `overdue` and gated, and the machine still refuses a fifteenth. It does not
   > budget the fourteen slices — Ruling 3 budgets one engine stage and Ruling 2 names the act the
   > blind families owe first; the fourteen remain unbudgeted work with a shape, which is more than
   > they had and less than a schedule. It does not read the debt as smaller, re-date a row, or
   > touch `_FAMILY_LANES`. And it does not rule the debt acceptable: what it removes is the excuse
   > that nobody knew what one slice would have to contain.
   >
   > **Measured on the commit that lands this**, so the prerequisites are sized rather than
   > asserted. The fourteen families declare ninety-two mechanics between them — unique
   > `mechanic_id`s compiled from `item_behavior_catalog.behavior_rules` over every owner in
   > `rule_owners()` — and eighty-five of the ninety-two are absent from
   > `trigger_stream.CAPABILITIES`, so a family's declarations are authored by its retirement slice
   > for nearly every mechanic it holds. Two mechanics are pair-lane previews today, under four
   > declared spellings, stamped by two producing sites. The retirement lane's own figure for the
   > undeclared mechanics does not reproduce under the join above and is **not** adopted here: the
   > number that binds a slice is the population that slice enumerates before its first `src/` edit
   > (R-20), published with its predicate, because a prerequisite sized by a figure nobody can
   > regenerate is the shape this campaign spent four hundred commits removing.
   >
   > **Amendment M — 2026-08-15, the static holder-amp term, the ordering that delivers it, and the
   > producer semantic for a packet-delivered walk half.** Amendment L, Ruling 3 budgets the
   > from-declaration pricing path and requires it to be *"provably a re-spelling before it is ever a
   > re-pricing"*. A retirement lane that went to start `delta_amp` measured that the path as built
   > does not carry one term the pair engine does. `damage._add_item_active_damage` mitigates an item
   > active's raw value against the holder's magic amplifier —
   > `raw_active, source.damage_type, resists, state.magic_amp` (`damage.py:14531`) — and
   > `damage._add_item_proc_damage` multiplies its mitigated per-proc figure by the holder's ability
   > amplifier — `amp = state.ability_amp if source.is_ability_damage else 1.0` (`damage.py:11073`);
   > `survival.pricing.price_declared_packet` (`pricing.py:483`) has neither. So
   > stamping a family's pair rows `THEORETICAL` while the walk prices its declaration would delete a
   > measured contribution — the holder's own *static, pair-local* amplifiers — from every total that
   > holds it. The same lane measured a second thing: a retired family's `PAIRED` walk half, declared
   > the way Amendment L requires, would join `golden_snapshot.cross_participant_producers` and move
   > D-07's ruled six. Both are ruled here and neither is re-litigable by a lane.
   >
   > **Ruling 1 — ordering, and the amp term.** `delta_amp`/`receipt_walk` **retires first**, and its
   > retirement act **is** the walk-side delivery of the static holder amps. Amendment L's Ruling 3
   > engine stage is amended, dated, to include the **declared amp term**: a `DeclaredPacket` composed
   > with the holder's static amps, resolved at build time from the declarations that produce them and
   > applied in the pair engine's documented order — **pre-mitigation**, so the composed value is
   > mitigated once rather than a mitigated number being re-multiplied. Its equivalence fixtures
   > **must** cover `amp != 1.0`; a fixture set in which every amp is `1.0` proves the stage
   > re-spells the case that cannot fail. The two cases the lane named — an Abyssal Mask holder's item
   > active, and an Abyssal Mask holder's ability-triggered item proc — are the **seed fixtures**, by
   > their predicate; what binds numerically is what the fixture's own instrument produces, per the
   > sentence Amendment L closes with. Two shapes are **forbidden**. Folding the amp into each
   > family's own declarations is an undeclared second producer of one number (D-60). Refusing a
   > packet whose holder has an amp armed deletes the number in the other direction, which is worse
   > than the ratio path it replaces, since that path at least refuses **by name**.
   >
   > **Ruling 2 — amp-armed coverage.** The covering scenario set gains, **by integration act**
   > (R-12, R-32 — a baseline moves in the integration agent's own commit and never inside a semantic
   > slice), at least one scenario arming `magic_amp` and one arming `ability_amp`, so the amp term is
   > observed by the baselines and by the oracles rather than shipping behind a green
   > zero-occurrence line. The coverage derivation **reads the amp-kind mapping** — which declaration
   > produces which of the holder's static amps — the way `golden_snapshot.receipt_walk_families`
   > already reads the family-to-owner join, so a future amp kind that no scenario arms fails the
   > check on the commit that declares it rather than being discovered by whoever next re-prices.
   >
   > **Ruling 3 — the producer semantic.** The cross-participant producer set derives from **the
   > packet semantic — does this packet modify ANOTHER participant's damage** — for
   > **packet-delivered** walk halves exactly as Amendment C already rules it for **rider-delivered**
   > ones. A retired self-scoped family's walk half prices *its own holder's* damage, so it is **not**
   > a producer. The ruled six stand **unedited**;
   > `tests/test_trigger_stream.py::test_the_cross_participant_producers_are_the_ruled_six` stays
   > green **without the six being touched**, which is the whole test of whether this ruling was
   > honest. `golden_snapshot.capture_coupled`'s producer gate binds **producers only**
   > (`golden_snapshot.py:1277`); a retired family is covered by the deferral coverage rule beside it
   > (`golden_snapshot.py:1287`), which is the rule that already exists for exactly this population.
   > A family joining the producer set because its retirement slice had to declare a pair preview
   > would be a ruled count moved to satisfy a validator — the move Amendment C refused, on the same
   > reasoning, from the other delivery shape.
   >
   > **What this amendment does not do.** It retires no row: all fourteen stand, `overdue` and gated,
   > and the machine still refuses a fifteenth. It budgets none of the fourteen slices — it amends the
   > one engine stage Amendment L already budgeted and names one integration act. It touches no
   > `src/`, moves no baseline, re-dates nothing, edits no lane table, and does not narrow Ruling 2:
   > what is measured below is **which half of that act is already met**, never a smaller act.
   >
   > **Measured on the commit that lands this**, because three claims in the prose that opened this
   > amendment do not reproduce, and each would mislead the lane that acts on it.
   >
   > *The amp term's declaring families are two, not one.* `state.ability_amp` resolves through
   > `delta_amp.resolve_part_amp` for the attack class being priced (`damage.py:2284`) from exactly one
   > declaring owner, `actualizer.ability_part_amp`, family `DELTA_AMP` — and it is armed only while
   > that item's own window is up. `state.magic_amp` is the sum of the `magic_damage_amp` effect over
   > the holder's items (`item_effects.py:4035`), declared today by exactly one owner, as
   > `abyssal_mask.unmake`, family **`ALLY_PACKET`** — *not* `delta_amp`, and itself one of D-07's
   > ruled six. So "resolved from the `delta_amp` declarations" is true of the ability half and false
   > of the magic half. Recorded rather than smoothed over: a lane that goes looking for the magic amp
   > among the `delta_amp` declarations finds nothing and drops the term, which is the exact deletion
   > Ruling 1 exists to forbid. The third static holder amp, `basic_amp`, comes from the only other
   > part-amp declaration in the tree over every owner in `rule_owners()`, and Ruling 2 names neither
   > it nor its coverage.
   >
   > *The two seed figures do not reproduce, and their factor does.* The lane published four numbers
   > and no roster, level or target to reproduce them at; no configuration reachable from the
   > committed scenario set returns them. What an instrument reproduces exactly is the **term**: in
   > both named cases the pair engine's row is the from-declaration price times the holder's own
   > `magic_amp`, which is also the ratio the lane's own two pairs stand in. The seed cases therefore
   > stand by their predicate and their numbers come from the fixture, per Amendment L's closing
   > sentence — a number that binds comes from an instrument.
   >
   > *Ruling 2's premise is half false, and the half that is false is load-bearing.* Measured over
   > every committed coupled scenario by reading each fight's resolved combat state:
   > `mandate_abyssal_curse_roster` already arms `magic_amp` on one of its participants — an Abyssal
   > Mask holder, exactly the shape Ruling 2 names — while every other scenario sits at `1.0`; and
   > `ability_amp` is `1.0` with an empty owner in **all** of them, no committed scenario holding the
   > one item that declares it. So Ruling 2's magic half is discharged by a scenario that already
   > exists and its ability half is genuinely owed. Two consequences the acting lane needs. The
   > integration act is **one** scenario, arming `ability_amp`, and the requirement is not thereby
   > narrowed — a derivation that reads the amp-kind mapping is what keeps "already met" from
   > decaying into "never checked". And the loss is **not** invisible today: stamping this family's
   > pair rows `THEORETICAL` without the amp term would move leaves in that roster, so the coupled
   > baseline can already see the magic half of the deletion, and this slice's R-20 population is
   > non-empty there before its first `src/` edit.
   >
   > **Amendment N — 2026-08-16, the per-packet resistance term, the term census, and
   > window-armed coverage.** Amendment M added the first term the budgeted from-declaration
   > pricing stage was missing. A retirement lane that went to start `active_cast` measured the
   > second and refused half a retirement rather than shipping it:
   > `survival.pricing.price_declared_packet` (`pricing.py:483`) prices a declaration at the **one**
   > effective resistance a fight publishes, while the pair engine re-prices already-authored
   > packets once the complete ledger exists — `_apply_temporary_lethality_windows`
   > (`damage.py:9894`) for physical packets, `_apply_liandry_reprice` (`damage.py:10163`) for magic
   > ones. Voltaic Cyclosword's Firmament grants its lethality *after* its own energized packet, so
   > an item active authored earlier is re-priced afterwards; measured on `mundo_3champ`'s locked
   > build, a declared raw of `324.423936` was priced by the pair engine at `0.0` and `0.45`
   > effective armour against published baselines of `12.85` and `15.45`, and pricing it at the
   > published figure would have deleted 11.4 and 13.0 percent of the packet — the composed roster
   > leaf *Stridebreaker (active)* falling 647.4 to 568.5. Only R-01 row 8 saw it: no coupled
   > scenario arms a window, so the slice's R-20 line read a green zero over a population that
   > could not contain the defect. The finding is
   > `docs/receipts/expected-golden-diff-campaign-close-active-cast-retirement.json` and gap-ledger
   > row G4. Three things are ruled here and none of them is re-litigable by a lane.
   >
   > **Ruling 1 — the resistance term.** A declaration is priced at **the resistance its own packet
   > actually met**. `survival.pricing.DeclaredPacket` gains a **per-packet effective-resistance
   > term**, transported from the authored ledger rather than resolved again at the walk, and kept
   > in step by **every site that re-prices an authored event** — `_apply_temporary_lethality_windows`
   > and `_apply_liandry_reprice` today, and whatever Ruling 2's census adds to that list tomorrow.
   > Pricing a retiring family's declaration at the fight's published baseline is **forbidden**: the
   > baseline is the fight's resistance and not the packet's, so paying it deletes the temporal
   > windows — a behaviour change smuggled into a slice labelled a re-spelling, which is the exact
   > shape Amendment M, Ruling 1 named as its second forbidden shape and the exact shape this
   > campaign exists to stop. The stage's equivalence fixtures **must** cover a lethality-window
   > physical case and a Liandry-reprice magic case; a fixture set in which every packet met the
   > published baseline proves the stage re-spells the case that cannot fail, on the same reasoning
   > that made Amendment M's fixtures cover `amp != 1.0`. The measured `mundo_3champ` figures above
   > are the physical **seed**, by their predicate, and what binds numerically is what the fixture's
   > own instrument produces.
   >
   > **Ruling 2 — the term census.** Terms shall not be discovered one halt at a time. Two families
   > have now been stopped by the same shape — a term the pair engine applies and the pricing stage
   > does not — each found by the lane that tripped over it, and a third such term would be found
   > the same way. A **source-derived census** enumerates every **post-authoring packet-mutation
   > site** in the pair engine: every site that changes an already-authored packet's amount or its
   > mitigation, which is the amp fold, the two re-pricing sites, and anything else the scan finds.
   > A gate asserts that each enumerated site is covered by a pricing-stage term **or** by a ruled,
   > dated exclusion recorded here. **No further family retires while the census shows an uncovered
   > site.** The census is derived from source and never hand-listed — a hand list is the thing that
   > failed twice — and it ships with an R-05 negative: an injected mutation site must turn it red.
   >
   > **Ruling 3 — window-armed coverage.** By **integration act** (R-12, R-32 — a baseline moves in
   > the integration agent's own commit and never inside a semantic slice), the covering scenario set
   > gains at least one scenario arming a **temporary-lethality window** — a Voltaic Cyclosword
   > holder whose Firmament actually fires — and at least one arming the **Liandry reprice**. The
   > coverage derivation **reads the window mapping**, the way `holder_amp_declarations`
   > (`golden_snapshot.py:1271`) already reads the amp-kind mapping and `receipt_walk_families` the
   > family-to-owner join, so a future re-pricing window that no scenario arms fails the capture on
   > the commit that declares it rather than being discovered by whoever next re-prices. Armed means
   > *fired*: a holder whose window opens on no packet is the same emptiness with a scenario name on
   > it.
   >
   > **What this amendment does not do**, each available and refused. It retires no row: all
   > thirteen stand, `overdue` and gated, and the machine still refuses a fourteenth. It budgets
   > none of the thirteen slices — it amends the one engine stage Amendment L already budgeted,
   > adds one gate, and names one integration act. It touches no `src/`, moves no baseline, re-dates
   > nothing, edits no lane table, and does not read the debt as smaller. And it does not rule the
   > `active_cast` stop a lane error: refusing half a retirement is what Amendment M, Ruling 1 asked
   > a lane to do, and what is removed here is the excuse that the next lane would have had to
   > invent the ruling too.
   >
   > **Measured on the commit that lands this**, because four claims in the prose that opened this
   > amendment are checkable and one of them is wrong in the direction that would mislead the lane
   > acting on it.
   >
   > *The seed figures reproduce exactly.* Unlike Amendment M's, this lane's numbers came with the
   > configuration to reproduce them, and they do. Dr. Mundo at level 13, one rotation, holding
   > Serylda's Grudge, Stridebreaker, Voltaic Cyclosword, Bastionbreaker, Trinity Force and
   > Sorcerer's Shoes — the pinned `mundo_3champ` probe build — into that scenario's two enemies:
   > the Firmament window is armed on both fights (the `on_hit_once_Voltaic Cyclosword_ability` row,
   > 15.0 lethality for 4.0s, rescaling 3 and 4 later physical events), the published effective
   > armour is `12.850000000000001` and `15.450000000000003`, and the `active_Stridebreaker` rows
   > read `324.4239360000001` and `322.970568442011`. The declared raw is the first of those
   > exactly, because the window drives that fight's armour to zero. At the published baselines the
   > same raw prices to `287.48244217988486` and `281.00817323516674`, and the two sum to the
   > reported 647.4 and 568.5.
   >
   > *The second reported leaf is a composed figure and its "before" is not a pair row.* The receipt
   > also reports *Heart Zapper* moving 198.5 to 202.7 downstream of the first leaf. Mundo's W rows
   > across the two pair fights sum to `202.7333` on this tree, which is the receipt's **after**
   > value — so the composed roster leaf is duration-limited by something the pair rows are not, and
   > its "before" is a coupled-walk figure no pair fight publishes. Recorded rather than smoothed
   > over: the leaf stands on the receipt's own instrument, its direction is consistent with a target
   > that survives longer once the active is smaller, and a lane that goes looking for 198.5 among
   > the breakdown rows will not find it.
   >
   > *The census predicate has to cover two shapes, and the obvious one would have missed the term
   > Amendment M already ruled.* Scanned over `damage.py` for assignment to a `damage`,
   > `total_damage` or `damage_per_hit` subscript: 14 sites in 8 functions, of which **four**
   > functions write rows or events they did not author — the two the ruling names, plus
   > `_reattribute_empowered_swings` (`damage.py:17825`), which moves damage between two authored
   > rows with the fight total untouched, and `_resolve_starting_shield_outcome`
   > (`damage.py:10586`), which re-prices every max-health-scaled packet against the target's live
   > pools and then recomputes `state.total_damage` from the rewritten rows. That is a **third**
   > re-pricing site the prose does not name, which is what Ruling 2's *anything else the scan
   > finds* was written for. And the amp fold appears in that scan **not at all**:
   > `_apply_command_amp` (`damage.py:17078`) and `_apply_general_amplifiers` (`damage.py:16983`)
   > mutate no packet in place — they read the ordered ledger and author a derived bonus row beside
   > it — so a census keyed only on in-place packet writes would enumerate this amendment's term and
   > silently miss Amendment M's. The census owes both shapes.
   >
   > *Ruling 3's two scenarios are both armable, neither is armed today, and the magic one cannot
   > use the shared roster shape.* Measured by running every pair fight of every committed coupled
   > scenario and of every bench roster: **none** arms a temporary-lethality window and **none**
   > holds a Liandry burn row, so the term is invisible to both baselines exactly as the stopped
   > slice reported. The physical half is easy: a Voltaic Cyclosword holder in the ordinary roster shape
   > arms the window and fires it on 10 events for a Caitlyn roster and 8 for a Jax one. The magic
   > half is not, and this is the load-bearing correction. The reprice needs **two** participants —
   > the attacker's Liandry's Torment burn and a defender's lifeline raising maximum health
   > mid-fight — and the only declaration in the tree that raises it is Protoplasm Harness's
   > (`protoplasm_harness.lifeline_protoplasm`, the one owner of `THRESHOLD_HEALTH_BONUS`). A fight
   > that runs past that lifeline's expiry is **withheld** rather than priced, so the roster set's
   > shared 8-second duration raises `ThresholdExpiryWithheld` and captures nothing: measured, the
   > arming envelope is a 3-to-5-second fight against a level-18 Protoplasm holder, and at 5 seconds
   > an Ahri roster holding Liandry's Torment, Rabadon's Deathcap and Void Staff prices a reprice
   > delta of `10.699001426533528` onto a burn row of `260.8274`. Two consequences the acting lane
   > needs. The integration act's magic scenario must depart from the roster set's shared duration,
   > with the departure stated rather than tuned until green. And the window mapping Ruling 3 says
   > the derivation reads is **two joins, not one**: the lethality side is one holder declaration
   > (`voltaic_cyclosword.empowered_hit`, the one owner of a `TemporaryLethality` payload over all
   > 143 owners in `rule_owners()`), and the Liandry side is an attacker declaration joined to a
   > *defender's*, so a mapping keyed only on the holder's items would report the magic half covered
   > by an empty set.
   >
   > **Amendment O — 2026-08-16, authority reclassification, and the triage of every remaining row.**
   > A retirement lane that went to start `crit_profile`
   > measured that the family authors **no pair-engine row anywhere in its covering population** —
   > `infinity_edge.crit_damage_bonus` folds into the champion's own `auto_attacks` row,
   > `navori_flickerblade.cooldown_refund` authors no damage at all, and `sundered_sky.forced_crit`
   > authors one row carrying `informational: true` that is summed into no total. So Amendment L,
   > Ruling 1's shape — both halves of which name a pair row the family authors — has nothing to
   > stamp and the walk's pricing stage nothing to price, and the three ways to force it are each
   > already forbidden in terms. The lane refused all three, filed its measurement at
   > `docs/receipts/expected-golden-diff-campaign-close-crit-profile-retirement.json`, and opened an
   > owed ruling. That was correct and it is answered here. Two rulings, neither re-litigable by a
   > lane.
   >
   > **Ruling 1 — reclassification, not retirement.** Under this file's own semantic-authority rule
   > three sections above — *all-pair-local inputs ⇒ `PAIR_ONLY`* — a family whose mechanics author
   > **no pair row** and fold **only into the holder's own champion rows** is `PAIR_ONLY`: the pair
   > engine is its authoritative home, no second engine prices it, and no double-count exists for a
   > preview stamp to prevent. Its `(family, RECEIPT_WALK)` deferral row was therefore a **schedule
   > category error** rather than a debt, and it closes as `not_a_gap` **by authority
   > reclassification** — a different act from a retirement, with a different receipt, and it is not
   > available to a family that authors a row. It closes **with a machine check**: the
   > zero-authored-rows property is measured over the covering population by a derived test, and the
   > row **REOPENS** if a future mechanic of the family ever authors one. `crit_profile` closes this
   > way now. The owed row
   > `whether_a_family_that_authors_no_pair_row_can_retire_off_the_pair_engine` is answered by this
   > amendment and moves to `answered[]` under its own closure rule, keeping its question beside it.
   >
   > **This is not a D-40 exclusion and not a re-count**, and the distinction is the whole of why the
   > act is legal. A lane editing `_FAMILY_LANES` so a family stops owing the walk an answer, while
   > the walk goes on consuming that family's numbers from somewhere, is a counter driven to zero by
   > editing what it counts — the move Amendments K, L, M and N each refuse in terms and the one
   > D-40 exists to forbid. What is ruled here is the opposite: the walk consumes **nothing** from
   > this family, because the family authors nothing for it to consume, and that is measured before
   > the table moves rather than asserted after. Amendment F's fourteen are **not read as thirteen**:
   > one row leaves as mis-scheduled and says so in its own words, which is a correction to the
   > schedule and not a discount on the debt.
   >
   > **Ruling 2 — triage, once.** Before any further retirement round, **every** remaining open
   > deferral row is measured for the same property and classified in the schedule receipt.
   > **(a) authors-own-rows** — retires by the ruled act (Amendments L/M/N), unchanged.
   > **(b) pair-local fold into holder-own rows** — closes by Ruling 1's reclassification, each with
   > its own machine check. **(c) roster-relevant fold**, its numbers reaching other participants or
   > roster totals through rows it does not author — requires a **NAMED walk-side delivery term** in
   > Amendment M's shape, and **if any class-(c) row lacks one the next retirement round STOPS**,
   > with the row named, rather than a lane inventing a term for it. The triage measurement is
   > **derived**, committed to `docs/receipts/receipt-walk-retirement-schedule.json`, and diff-gated
   > by `tests/test_receipt_walk_schedule.py`. Terms were not to be discovered one halt at a time
   > (Amendment N, Ruling 2); neither are shapes.
   >
   > **What this amendment does not do**, each available and refused. It retires no row: the nine
   > that remain after the reclassification stand `overdue` and gated, and the machine still refuses
   > a tenth. It budgets none of them — a class is a fact about the shape of a slice, never a smaller
   > amount of it. It re-dates nothing, reads the debt as no smaller, and registers no interpreter.
   > And it does not rule the `crit_profile` stop a lane error: refusing to force a ruled shape onto
   > a family that cannot carry it is what Amendment M, Ruling 1 asked a lane to do, and what is
   > removed here is the excuse that the next lane would have had to rediscover the shape.
   >
   > **Measured on the commit that lands this**, because the prose that opened this amendment
   > describes one family and the ruling binds ten, and three of the checkable claims come out
   > differently from the way a reader would guess.
   >
   > *The no-row shape is the common case among what is left, not the exception.* Measured by
   > ablation over every covering coupled scenario and over a per-owner probe on a ranged and a melee
   > champion, **six** of the ten open rows author no priced pair-engine row at all — `combat_state`,
   > `crit_profile`, `damage_routing`, `opening_defense`, `resistance_shred` and `threshold_defense`
   > — and only four author one. Had Ruling 2 not been written, five further retirement attempts
   > would have hit the shape that stopped the fifth, one at a time.
   >
   > *Exactly one of the six is class (b), and the discriminator is a declaration the catalog already
   > carries.* `crit_profile` is the only family all of whose declarations name `Subject.HOLDER`.
   > `resistance_shred` and `damage_routing` declare `Subject.TARGET` payloads, which land on a
   > shared defender every roster participant meets; `combat_state`, `opening_defense` and
   > `threshold_defense` declare `DefenseField` writers with no subject, whose inputs are the
   > subject's live state under combined fire — a roster input by the authority rule's own list. So
   > Ruling 1 closes one row and not six, and the class-(b) test is read from the payload rather than
   > judged. The obvious alternative test does **not** work and is recorded so nobody rebuilds it:
   > ablating a family and watching the other participants is confounded by survival coupling —
   > measured, removing `crit_profile`'s owners from `crit_onhit_carry_roster` moves the enemy
   > Aatrox's *outgoing* damage and the holder's *incoming*, because a target that takes less damage
   > lives longer, and that would have classified the one genuine class-(b) row as class (c).
   >
   > *One class-(c) row lacks a named delivery term and it is `damage_routing`.* Three of the five —
   > `combat_state`, `opening_defense`, `threshold_defense` — have Amendment K's delivery standing in
   > the tree today, `INTERPRETERS` holding the `(family, DEFENSE_RESOLVER)` key. `resistance_shred`
   > has the `SPLIT` shape: both its owners declare a cross-participant half the walk already stages
   > (`black_cleaver.carve`, `bloodletters_curse.vile_decay`). `damage_routing`'s three owners
   > declare none, and no interpreter serves its lane, so **the next retirement round stops there by
   > name**. Also recorded, because it would otherwise be mistaken for a row: `the_collector.execute`
   > authors an `execute` row carrying `informational: true`, the same shape as
   > `sundered_sky.forced_crit`, and Bloodthirster's lifesteal authors a heal row with no
   > `total_damage` at all. The predicate the triage turns on is exact rather than a heuristic —
   > summing `total_damage` over the rows it counts reproduces the fight's own `total_damage` — which
   > is what keeps "authors no row" from being a reading of the row list.
   >
   > **Amendment P — 2026-08-16, `damage_routing`'s named walk-side delivery.**
   > *Answers the one row Amendment O, Ruling 2's stop clause fired on, published as the whole of
   > `triage_rows_stopping_the_next_retirement_round` in
   > `docs/receipts/receipt-walk-retirement-schedule.json`.* The triage landed in full — every open
   > row classified, `crit_profile` closed by reclassification, gates green — and it stopped exactly
   > where Ruling 2 said it would, on `damage_routing/receipt_walk`: Death's Dance, Serpent's Fang
   > and The Collector, class (c), with no interpreter registered in the lane the row declares and
   > no owner carrying a cross-participant half the walk already stages. Ruling 2's own words are
   > that such a row stops **rather than having a term invented for it** by the lane that finds it,
   > and the lane invented nothing, which is what it was asked to do. Naming the term is this file's
   > act, and it is performed on Amendment K's precedent: name a standing mechanism, invent nothing.
   >
   > **RULING — THE NAMED DELIVERY.** `damage_routing`'s walk-side delivery is the **program rider
   > system and the kernel state paths ALREADY IN THE TREE**. The family's declarations compile to
   > the appropriate rider or state adjustment, and what consumes each one is the kernel's existing
   > handling rather than anything this ruling asks a lane to build.
   >
   > * **Death's Dance's deferred-damage routing** is a `Defer` rider on the holder's incoming
   >   damage events. The rider family is declared —
   >   `Rider = Union[Execute, Defer, Redirect, Wound, AmpBonus]`
   >   (`src/calculator/program/events.py:259`) — the kernel action carries the state it lands in
   >   (`src/calculator/survival/actions.py:420`, `deferred_batch_slot: int = NO_SLOT`), and the
   >   batch arithmetic that pays it down already stands
   >   (`src/calculator/survival/transitions.py:1629`, `if action.deferred:`).
   > * **The Collector's threshold execute** is an `Execute` rider on outgoing damage, carried by
   >   the same action's own fields (`src/calculator/survival/actions.py:417`,
   >   `execute_threshold_ratio: float = 0.0`) and read where the kernel already decides an
   >   execution (`src/calculator/survival/transitions.py:1767`,
   >   `action.execute_threshold_ratio > 0.0`).
   > * **Serpent's Fang's shield reduction** is the kernel's **barrier-state adjustment path**: the
   >   surviving share of the shielding the defender gains
   >   (`src/calculator/shield_ledger.py:93`, `venom_factor: float = 1.0`), written by the walk on
   >   the hit that applies the venom (`src/calculator/survival/transitions.py:1680`,
   >   `pools.venom_factor = min(pools.venom_factor, venom_keep)`) and read by the ledger on every
   >   shield it grants (`src/calculator/shield_ledger.py:389`).
   >
   > **The row's retirement act is then the ruled act** — Amendments L, M and N, unchanged and
   > neither narrowed nor widened — **with rider and state compilation as the interpreter's
   > output.** That is the one substitution this amendment makes. For the four families retired so
   > far the interpreter's output is a price the walk pays; here it is a rider on an event the walk
   > already stages, or an adjustment to state the walk already holds, and Amendment C ruled that
   > substitution legal for a **rider-delivered** walk half before any of this: a rider carries a
   > stamp and no `packet_source` at all. Everything else in Ruling 1's shape binds as written: the
   > family's `MechanicCapability` declarations authored; its pair rows stamped `pair_preview_of`
   > and declared `ViewTag.THEORETICAL` — of which, measured by the triage, this family authors
   > none, so that half is discharged as an enumerated **emptiness** exactly as `delta_amp`'s was
   > and never as a step skipped; the lane interpreter landed and wired; the deferral row retired;
   > the numeric consequence, the `Expected qualifying occurrences` line with its population
   > enumerated before the slice's first `src/` edit, and the oracle receipt every qualifying
   > occurrence then owes. **Equivalence fixtures per owner**, and that plural is load-bearing:
   > three owners deliver through three different mechanisms, and a fixture set that arms one of
   > them proves nothing about the two that can still fail — the same argument Amendment M made for
   > `amp != 1.0`.
   >
   > **The stop clause is not removed; it is re-pointed at the one thing that could still stop
   > this.** IF any owner's effect has no existing rider or state path the kernel can express, the
   > implementing lane **STOPS blocked, naming exactly which** — the kernel is never extended
   > inside a retirement slice. A retirement slice that grows a sixth rider family or a new kernel
   > state field is no longer a re-spelling of what the pair engine already prices; it is a
   > behaviour change wearing a retirement's name, with no committed baseline able to see the
   > difference, which is the shape this campaign exists to invert. So the delivery term is named
   > **and machine-resolved**: the schedule receipt derives, per declaration, the mechanism this
   > ruling names for its payload family and resolves that mechanism against the tree on every run,
   > and a fourth mechanic of this family whose payload family this ruling does not name — or a
   > named mechanism that leaves the kernel — turns the term unnamed again and re-stops the row by
   > name. A ruling that could only be read is one nobody can be stopped by.
   >
   > **What this does not do**, each available and refused. It **retires nothing**: the row stands
   > `overdue` and gated with the eight beside it, the machine still refuses a tenth, and being
   > startable is not being started. It **budgets nothing** — naming a delivery is a fact about the
   > shape of a slice, never a smaller amount of it. It **moves no class letter**: the triage
   > measures a class from the pair rows a family authors, this family still authors none, and the
   > receipt goes on saying so. What lifts is the stop, and the row is thereafter treated the way a
   > class-(a) row is treated — it retires by the ruled act — while its measured class stays (c),
   > because a letter edited to match a ruling would be the measurement being written from the
   > conclusion, which is the move Ruling 2 was written to prevent. It **registers no interpreter**
   > and changes no lane table: an interpreter registered to move a counter without changing what
   > the walk prices is a counter driven to zero by editing what it counts (D-40), and this
   > amendment touches no `src/` at all. And it does **not** widen Amendment M: the pricing stage
   > gains no term here, because none of these three effects is priced — a deferral moves damage in
   > time, an execute ends a fight, and a venom resizes a barrier, and the reason the triage found
   > no term for them in Amendment M's shape is that they are not that kind of thing.
   >
   > **Measured on the commit that lands this**, because a ruling that names a standing mechanism
   > is only as good as the standing, and the conditional stop above is exactly the claim a reader
   > should not take on trust. All three mechanisms resolve in the tree today, checked through the
   > kernel's own declarations rather than by reading the citations above: the rider families the
   > kernel declares hold both `Defer` and `Execute`; the survival action declares `deferred`,
   > `deferred_batch_slot`, `execute_threshold_ratio` and `execute_source`; and the shield ledger's
   > pools declare `venom_factor`. Every declaration of the family maps to one of the three —
   > `deaths_dance.ignore_pain` is a `DamageDeferralRule`, `the_collector.execute` an `ExecuteRule`,
   > `serpents_fang.shield_bypass` a `ShieldBypassRule` — so no owner is left over, which is the
   > condition the stop clause turns on. Recorded because it comes out the other way from what the
   > triage's own prose would suggest: the row was stopped for having *no delivery anywhere in the
   > tree or in an amendment*, and what it actually lacked was an amendment, the tree having held
   > all three mechanisms since Phase 4 built the rider system.
   >
   > **No rulings-owed row closes here.** Amendment O, Ruling 2's stop clause is self-executing —
   > it names a row rather than opening a question a lane may not answer — so the stop was published
   > in the schedule receipt and never in `docs/receipts/rulings-owed.json`. That ledger's one open
   > row is still the first one it opened — whether criterion 11's first clause binds the campaign
   > backwards — and this ruling does not reach it. Its id is deliberately not written here: an
   > owed row and an amendment cannot both be true of one question, and the ledger's gate reads
   > this file for exactly that collision.
   >
   > **Amendment Q — 2026-08-16, the lane a served walk-side need does not owe.**
   > *Answers the eighth row of `docs/receipts/rulings-owed.json`,
   > `what_retires_a_deferral_whose_ruled_act_is_performed_in_another_lane`, opened by the
   > retirement lane that went to start `combat_state/receipt_walk` and measured that its ruled
   > retiring act was already performed.* That lane measured three things and refused three moves.
   > The `(family, DEFENSE_RESOLVER)` interpreters are registered for `combat_state`,
   > `opening_defense` and `threshold_defense`, so Amendment K's act is done for all three; the walk
   > consumes the resolver's resolved state rather than a pair-engine row — `force_of_nature.steadfast`'s
   > own capability names the walk-side implementation reading it
   > (`src/calculator/trigger_stream.py:1495`), and that function is in the tree
   > (`src/calculator/survival/transitions.py:360`) — and a receipt-walk interpreter there would be
   > a **second producer of one number**, which D-60 and criterion 8 forbid in terms. The rows
   > persisted anyway, because `_FAMILY_LANES` (`src/calculator/interpreters/__init__.py:114`) still
   > declared `RECEIPT_WALK` a needed lane and `interpreters.uninterpreted_pairs()` therefore kept
   > the pair. The lane stopped, filed its measurement and opened the row. That was correct and it
   > is answered here.
   >
   > **RULING — LANE-DECLARATION CORRECTION.** A family whose walk-side need is satisfied
   > **through its declared serving lane** does not need — and **must not declare** — a
   > `RECEIPT_WALK` interpreter lane. One producer is precisely what the one-engine thesis demands,
   > so a table that goes on asking a second lane for an answer the first lane already gives is
   > asking for the thing criterion 8 forbids, and the deferral row underneath it is counting the
   > absence of a defect. `RECEIPT_WALK` therefore leaves `_FAMILY_LANES` for **exactly these three
   > measured families**, on the measured ground, in Amendment O, Ruling 1's shape — **with a
   > machine check in both directions and a reopening condition**, and the three rows close as
   > lane-declaration corrections rather than as retirements.
   >
   > **The check runs in both directions, because one direction is a half-check.** Forwards: the
   > named walk-side implementation reads the resolver's resolved state, **source-asserted** — the
   > fields each declaration writes are derived by running the family's own resolver interpreter,
   > the sites consuming them are derived by walking every module outside the resolver for a read of
   > that field off a resolved defences value, and a declaration nothing consumes fails the gate by
   > name. Backwards: deleting the family's resolver interpreter must flip its items to
   > **`withheld` with a named receipt**, never to a silent zero — run on every check rather than
   > reasoned about, over every declaring owner, and an **R-05 negative** proves the red. The
   > forwards half alone would let a family whose numbers reached the walk from somewhere else keep
   > its lane dropped; the backwards half alone would let a family nothing consumes keep it. The
   > **reopening condition** is the third clause: if a mechanic of one of these families ever
   > authors walk-priced rows not fed by the resolver, the lane **re-enters** and the row reopens —
   > measured on every run by the same ablation the triage uses.
   >
   > **This is not D-40's prohibition, and the distinction is the whole of why the act is legal.**
   > D-40 forbids a counter driven to zero by editing what it counts — a lane table edited so a
   > family stops owing the walk an answer *while the walk goes on consuming that family's numbers
   > from somewhere*. Here the walk consumes this family's numbers from **the lane the family
   > declares**, that is measured before the table moves and stays measured after it, and the
   > declaration is corrected **on a ground recorded in this file with its check** rather than
   > edited to move a counter. Amendment K's three refusals stand exactly as written and none of
   > them is this act: no interpreter is registered that emits fields nothing consumes, Amendment
   > F's fourteen are not read as eleven, and what changes is a declaration that was wrong rather
   > than a debt that was owed.
   >
   > **What this amendment does not do**, each available and refused. It **retires nothing**: no
   > interpreter is registered, no walk begins pricing anything it did not price, and the five rows
   > that remain stand `overdue` and gated with the machine still refusing a sixth. It **budgets
   > nothing**. It **reads the debt as no smaller**: three rows leave as mis-declared and say so in
   > their own words, which is a correction to a declaration and not a discount on a debt, exactly
   > as Amendment O, Ruling 1's one row left as mis-scheduled. It does **not** reclassify these
   > families `PAIR_ONLY` — Amendment O, Ruling 1 measured them out of that class in its own
   > paragraph, and this is the other ground. And it **moves no triage class letter**: all three
   > stay class (c), measured from the pair rows they author, which is none.
   >
   > **Measured on the commit that lands this**, because the ruling's ground is a claim about the
   > tree and two of the checkable claims come out differently from the way a reader would guess.
   > All twenty declarations of the three families have their resolved fields consumed outside the
   > resolver, and the consuming sites are four modules rather than one — the walk's own transitions
   > and receipt state, the participant timeline, and the roster composition that hands a defender's
   > resolved state to the pair fights the walk runs. **One resolved field is consumed nowhere and
   > it is published rather than hidden**: Steadfast's move-speed bonus, which no engine in this
   > model reads, so the check is stated per declaration and the unread residue enumerated beside
   > it. And every one of the twenty declaring owners flips to `withheld` naming its own
   > `(family, defense_resolver)` pair when the resolver interpreter is removed — twenty for twenty,
   > including the owners that declare a second family as well, which is the case a spot check
   > would have missed.
   >
   > **The rulings-owed row closes here** — `what_retires_a_deferral_whose_ruled_act_is_performed_in_another_lane`
   > moves to `answered[]` under that ledger's own closure rule, keeping its question beside it.
   > The ledger's one remaining open row is the first one it opened, whether criterion 11's first
   > clause binds the campaign backwards, and this ruling does not reach it.
   >
   > **Amendment R — 2026-08-16, the basic-attack swing terms, the census's reach, and a routed magnitude's owner.**
   > *Answers the tenth row of `docs/receipts/rulings-owed.json`,
   > `what_the_from_declaration_pricing_stage_owes_a_basic_attack_delivered_packet`, opened by the
   > retirement lane that went to start `secondary_target/receipt_walk` and measured that the
   > budgeted from-declaration pricing stage cannot price a packet delivered as a basic-attack
   > swing.* Every family retired so far reaches its target through `_mitigate`
   > (`damage.py:395`) and nothing else — a resistance and the holder's own amps, which is exactly
   > what `survival.pricing.price_declared_packet` (`pricing.py:483`) carries. A Runaan's bolt is
   > priced by `_mitigate_basic_attack_swing` (`damage.py:853`), which applies three further
   > target-side terms, and the family's *other* authored row is the attack's on-hit effects copied
   > onto a second subject by `_copied_on_hit_packet` (`damage.py:15248`), for which
   > `runaans_hurricane.secondary_target` declares no magnitude at all. The lane refused four moves,
   > each already forbidden in terms by the three amendments that built the stage, filed its
   > measurement at
   > `docs/receipts/expected-golden-diff-campaign-close-secondary-target-retirement.json` and opened
   > the row. That was correct and it is answered here. Four rulings, none of them re-litigable by a
   > lane.
   >
   > **Ruling 1 — the swing terms.** The pricing stage gains the **basic-attack swing
   > composition**, in the order the pair engine applies it: the packet is mitigated at **its own**
   > resistance (Amendment N, Ruling 1), composed with the holder's static amps pre-mitigation
   > (Amendment M, Ruling 1, already carried), and then met by the target-side terms. Two of those
   > three **fold**, because a pure factor on a linear mitigation composes into the declared
   > magnitude and prices to the same real number — the target's critical-strike damage multiplier,
   > and the plating multiplier `_apply_target_basic_damage_reduction` (`damage.py:799`) applies —
   > which is the argument the `on_hit_strike` retirement already used for on-hit effectiveness and
   > is used here for the last time on these two terms. Warden's Mail's Rock Solid is **never
   > folded**. `min(flat, per_hit × cap)` is a **capped flat subtraction**, not a factor on a
   > magnitude; it is applied to the crit branch and the non-crit branch **separately, before the
   > deterministic blend**, so the cap bites on one and not the other; and it is therefore carried
   > as a term in its own right — the flat, its cap and its instance count transported on the
   > declaration and subtracted per branch, floored at zero, before the branches are blended. **A
   > subtraction is not a factor**, and no magnitude a declaration could state reproduces one. The
   > term rides **on the declaration**, transported from the authored ledger rather than resolved
   > again at the walk, for the reason Amendment N gave for the resistance: what the walk must
   > reproduce is the term this packet met and not the term the fight settled at. A declaration no
   > basic-attack swing delivered carries none and prices exactly as it prices today, so no retired
   > family's number moves. The two ways out a lane might still reach for are the two already
   > forbidden: dividing the pair engine's own mitigated figure back out is the ratio path this
   > stage exists to replace (Amendment N, Ruling 1), and refusing the packet whenever a target-side
   > term is armed is Amendment M, Ruling 1's second forbidden shape read from the defender's side —
   > it deletes the number in the other direction. **Equivalence fixtures are seeded from the
   > measured Caitlyn probe, both inert and armed**, and that conjunction is load-bearing on exactly
   > the reasoning that made Amendment M's fixtures cover `amp != 1.0` and Amendment N's cover both
   > windows: a fixture set in which every target-side term is inert proves the stage re-spells the
   > case that cannot fail. The seed figures are in the Measured section below, by their predicate;
   > what binds numerically is what the fixture's own instrument produces.
   >
   > **Ruling 2 — the census widening.** Amendment N, Ruling 2's term census ranges over
   > **post-authoring** packet mutation and the holder-amp folds beside it, and no census in that
   > shape can reach a term applied **while the packet is being authored**. Its green is therefore
   > **truthful under the old predicate**, and is recorded here as truthful: what the stopped lane
   > found is a fact about the census's reach, not a defect in it. The predicate **widens** to range
   > over **authoring-time mitigation terms** as well — every term `_mitigate` and
   > `_mitigate_basic_attack_swing` apply to a packet as they price it, target-side as well as
   > holder-side — under the same gate it already carries: each enumerated term is covered by a
   > pricing-stage term or by a ruled, dated exclusion recorded in this file, and **no further family
   > retires while the census shows an uncovered term**. Derived from source and never hand-listed,
   > for the reason it was derived in the first place, and it ships with its **R-05 negative
   > updated**: an injected authoring-time mitigation term must turn the census red, exactly as an
   > injected re-pricing site already does. Terms were not to be discovered one halt at a time, and
   > a census that ranges over one half of a mitigation is a census that discovers the other half
   > one halt at a time.
   >
   > **Ruling 3 — routing-family magnitude ownership.** `secondary_target` is a **routing family**:
   > it re-delivers **source families'** declared magnitudes at a second subject and **declares no
   > magnitude of its own** (D-60, one producer per number). The copied packet is therefore priced
   > from the **source family's** declaration composed with the router's declared `damage_share`,
   > and attributed under D-62 at **(source mechanic, secondary subject, event_id)** — the subject
   > being what keeps that key clear of the same source mechanic's primary delivery — with the
   > routing itself recorded in **provenance**, which is where a fact about how a packet reached a
   > subject belongs and is not a second number. The router's own declaration carries **exactly the
   > routing facts it carries today**, `max_targets` and `damage_share`, and gains no magnitude
   > field: a routing family that declared the magnitude it routes would be a second producer of a
   > number a source family already declares, which is what criterion 8 forbids and precisely why
   > the stopped lane could not answer this itself. So the bolt row prices from the swinging
   > family's declaration through Ruling 1's composition, and the copied on-hit row prices from the
   > already-retired `on_hit_strike` family's declarations delivered at the secondary subject — one
   > producer each, two subjects, no number declared twice.
   >
   > **Ruling 4 — coverage.** By **integration act** (R-12, R-32 — a baseline moves in the
   > integration agent's own commit and never inside a semantic slice), the covering scenario set
   > gains a scenario that **arms the enemy-held swing terms**: a defender holding **Warden's Mail**,
   > with the plating multiplier and the crit-damage reduction in reach, met by an attacker whose
   > delivery is a basic-attack swing. The coverage derivation **reads the term mapping**, the way
   > `repricing_window_declarations` (`golden_snapshot.py:1505`) already reads the window mapping
   > and `holder_amp_declarations` the amp-kind mapping, so a further target-side swing term that no
   > scenario arms fails the capture on the commit that declares it rather than being discovered by
   > whoever next prices a swing. **Armed means met**: a defender holding the item in a fight nobody
   > swings at is the same emptiness with a scenario name on it, so the mapping is a **two-sided
   > join** — the defender's declaration on one side and a basic-attack delivery on the other — in
   > the shape Amendment N, Ruling 3's magic half already needed.
   >
   > **What this amendment does not do**, each available and refused. It **retires nothing**:
   > `secondary_target/receipt_walk` stands `overdue` and gated with the row beside it, the machine
   > still refuses a third, and being startable is not being started. It **budgets nothing** —
   > naming a term is a fact about the shape of a slice, never a smaller amount of it. It **moves no
   > triage class letter**: the class is measured from the pair rows a family authors and this
   > family still authors two, so it stays (a). It touches no `src/`, moves no baseline, re-dates
   > nothing, edits no lane table and registers no interpreter. And it does **not** rule the
   > `secondary_target` stop a lane error: refusing to amend a stage three amendments say a lane may
   > not amend is what Amendment N's closing sentence asked of the next lane, and what is removed
   > here is the excuse that it would have had to invent the ruling too.
   >
   > **Measured on the commit that lands this**, because the ruling rests on four checkable claims
   > and two of them come out differently from the way the receipt that opened it reads.
   >
   > *The seed figures reproduce exactly, all four of them.* Caitlyn at level 18 holding Runaan's
   > Hurricane and Blade of the Ruined King, deterministic, one rotation at full auto uptime, a
   > roster target count of two with the bolt allocated to the second, against the snapshot
   > target's 50.0 effective armour — the receipt's own pinned probe. The bolt row prices at
   > `90.45833333333331` per hit with the three target-side terms inert, at `81.4125`
   > with the plating multiplier of 0.9 armed, at `79.60333333333332` with the crit-damage
   > multiplier of 0.7 armed, and at `75.85333333333332` with Warden's Mail's flat 15.0 capped at
   > 0.2 of the instance — the last being the 19.3 percent a walk pricing this declaration at the
   > published baseline would have paid over. The copied on-hit row's four one-rotation events are
   > the first four of the seven the receipt reports and sum to its figure exactly.
   >
   > *Arming the swing terms moves the copied row in the OPPOSITE direction, and the coupling is
   > worth a lane's time.* With Rock Solid armed the copied on-hit row rises from
   > `198.85864000000004` to `205.468`, because a secondary target that takes less from the bolt
   > carries more health into the current-health on-hit strikes that follow it. So the two rows are
   > not independently priceable even though Ruling 3 gives them different producers: the copied
   > row's magnitudes are the source family's, and what they are worth depends on a subject whose
   > live state the walk has to carry. A fixture that arms a term and checks only the bolt would
   > read green over the row that moved.
   >
   > *The census is green and blind, and its blindness is enumerable rather than argued.* Run on
   > this commit: 29 sites in 29 functions, 0 uncovered, 0 unfolded amps.
   > `_apply_target_basic_damage_reduction` appears in that enumeration **not at all**, and
   > `_mitigate_basic_attack_swing` appears in it only for the two holder amps it folds. The census
   > sees the swing function and not the swing's target-side terms, which is the reach fact stated
   > as a measurement instead of as a reading of a predicate.
   >
   > *Two of the three terms are already armed in the committed coupled baseline, and the receipt
   > that opened this says none of them is.* Measured by running every pair fight of every committed
   > coupled scenario with the defender-state hand-off instrumented: exactly one,
   > `immolate_active_bruiser_roster`, arms a non-unit target-side swing term — plating 0.9 and
   > crit-damage 0.7, on its Darius main as **defender**, in two pair fights — because
   > `target_overrides` (`roster_composition.py:251`) hands a defender's resolved
   > state to every pair fight the walk runs, and that scenario is attacked as well as attacking.
   > **Rock Solid is armed by no committed coupled scenario and by no bench roster at all.** The
   > receipt's unqualified sentence is wrong and its own rulings-owed row's qualified one is right:
   > what nothing arms is a swing term **on a defender a basic-attack router attacks**, which is the
   > join Ruling 4 makes the derivation read. Recorded rather than smoothed over, because a lane
   > that goes to add the physical half and finds the plating factor already observable will
   > otherwise conclude the mapping is covered.
   >
   > *The term mapping has four declaring owners across two rule shapes, not three of one.* Derived
   > over every owner in `rule_owners()`: `plated_steelcaps.plating`, `randuins_omen.resilience` and
   > `wardens_mail.rock_solid` declare the three terms as `OpeningDefenseRule` writes, and
   > `armored_advance.noxian_endurance` declares the same plating multiplier as a `ReactiveRule`
   > write. A mapping keyed on the opening-defence shape alone would report the plating term covered
   > by an incomplete set — the same shape as Amendment N's warning that a mapping keyed only on the
   > holder's items reports the magic half covered by an empty one.
   >
   > **The rulings-owed row closes here** —
   > `what_the_from_declaration_pricing_stage_owes_a_basic_attack_delivered_packet` moves to
   > `answered[]` under that ledger's own closure rule, keeping its question beside it. The ledger's
   > one remaining open row is still the first one it opened, whether criterion 11's first clause
   > binds the campaign backwards, and this ruling does not reach it.
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

## Owner's rulings

A ruling recorded here is the campaign **owner's**, relayed and transcribed by a
lane. It is not an amendment: an amendment above is the orchestration re-reading
its own contract on a measured ground, and every one of them is a decision a lane
could in principle have reached. A ruling in this section is one no lane could —
the questions `docs/receipts/rulings-owed.json` collects and refuses to let a lane
answer. The two are kept apart so a reader can tell, without asking anybody, which
of the campaign's own conclusions the campaign was entitled to draw. A ruling
transcribed here names its date, its question by that ledger's row id, and the
machine check that makes it more than prose; the owed row then moves to
`answered[]` naming it, so the question and its answer stay joined.

> **Owner's ruling — 2026-08-17, criterion 11's first clause: the fixed-point reading.**
> *Answers `whether_criterion_11s_first_clause_binds_the_campaign_backwards` in
> `docs/receipts/rulings-owed.json` — the first row that ledger opened, the last
> one it held open, and the campaign's one certification blocker. Relayed through
> the orchestration and transcribed on 2026-08-18 by the slice group
> `campaign-close-owner-ruling-criterion-11`.*
>
> The question offered two branches — bind the clause backwards and schedule a
> fresh R-35 pass over every uncovered range, or read it forwards and let the
> gate hold the next slice group — and the closeout measured a third, that a
> group's verdict may be recorded by a commit carrying that same group's tag.
> Close-report §16.3 measured why the first two do not terminate: recording a
> verdict is itself a commit, every commit carries a slice tag, and a tag with no
> verdict is residue, so the act of closing the residue creates residue. That
> measurement is accepted and none of the three branches is taken. What is ruled
> is the reading that has a fixed point.
>
> **Ruling 1 — the clause binds backwards, for implementation slices.** "Every
> slice" means every unit of work that changes behaviour in `src/`, `tests/`,
> `scripts/` or `data/`, and for those units the clause binds the campaign's own
> past exactly as written. It is **discharged** for them by the verdicts recorded
> in `docs/receipts/verify-ledger.json` — the fresh R-35 passes, and equally the
> verdicts the campaign rendered and never filed, transcribed through that
> ledger's own `backfill` and `residue_sweep` route. Both are recorded verdicts:
> a transcription of a verifier's rendered answer is the verifier's artifact
> reaching the ledger late, which is a different act from a lane reconstructing
> an answer out of the commit bodies of the lanes being checked. That second act
> stays forbidden, and the ledger's `what_this_block_does_not_do` stays exactly as
> written.
>
> **Ruling 2 — verification, certification, transcription and receipt-only passes
> are instruments, not subjects.** They do not enter the clause's coverage
> denominator. Their record is their own: a verifier's or transcriber's pass row
> in the ledger, or — for the terminal pass — the certifier's signed verdict in
> the close report. This is what closes the self-referential regress §16.3
> measured, and it closes it at the reading rather than at the counter: an
> instrument that grades the campaign is not a slice of the campaign, so the
> process convened to grade the clause stops adding to what it grades. **The
> denominator derivation is corrected to implementation-slice tags**, and every
> tag taken out of it is **enumerated by name beside the self-record that stands
> in place of its verdict**, under a machine check with a red it can reproduce:
> the self-record must resolve in the artifact it names, and an instrument tag
> whose commits touch `src/` fails — production behaviour makes a pass a subject
> whatever it calls itself. **This is not a D-40 exclusion.** D-40 forbids editing
> what a counter counts in order to move it; what is ruled here is what the
> counter's unit always was, recorded with its check, by the one party entitled to
> say. The three shortcuts the owed row refuses stay refused, and the second of
> them — shrinking the denominator by a lane's declaration that some tags are not
> really slices — stays refused in exactly those terms.
>
> **Ruling 3 — the one unreached range is verified, not reclassified.**
> `campaign-close-verify-p4-batch` is a transcription pass and could have been
> read out of the denominator by Ruling 2. It is not. Its prepared row in
> `docs/receipts/verify-backlog.json` is handed to a fresh R-35 pass and its
> verdict is recorded like any other, because a range no verifier ever reached is
> better answered than excused, and a ruling whose first use is to excuse the one
> thing it could excuse is a ruling nobody should trust.
>
> **Ruling 4 — every `NOT_DISCHARGED` row carries a disposition.** One of `fixed`,
> citing the commit that fixed it; superseded by later work, citing that work; or
> `documented_open` carrying the artifact that holds the open debt. A verdict is
> the verifier's and is never re-graded by a lane — the ledger's own
> `when_a_later_lane_answers_a_sweep_row` rules that and is unchanged. What this
> ruling adds is that a disposition is owed on every one of them, so an
> unanswered finding is visible as one rather than as a row nobody reached.
>
> **Ruling 5 — untagged commits.** A commit whose subject carries no trailing tag
> is outside "every slice" when it touches no behaviour. The untagged commits that
> **do** touch `src/` are enumerated, derived rather than authored, and each is
> covered by a batch verdict naming its range or by a dated acceptance note. No
> commit subject is rewritten to reach this: retro-tagging rewrites the history the
> denominator is derived from, which the owed row refuses and this ruling does not
> unrefuse.
>
> **What this ruling does not do.** It does not discharge criterion 11 — the
> residue is what the ledger's coverage block says it is, on the tip a reader
> measures it at, and Ruling 3's pass and Ruling 5's enumeration are work that has
> to land. It does not re-read "every slice" more weakly for anything that changes
> behaviour: the backwards branch is taken, not avoided. And it does not reach the
> clause's other two halves, which stand as written and as graded.
