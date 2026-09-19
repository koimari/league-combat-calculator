# Dead code audit: src/ excluding src/calculator/champions/

Scope: 312 files, 121,427 lines. Covers `src/calculator/*.py`, `fight/`,
`program/`, `survival/`, `interpreters/`, `rune_paths/`, and `src/*.py`.

## Method

`vulture src --min-confidence 80` returns zero findings on this tree.
`--min-confidence 60` returns 159, of which 141 are Flask-decorated routes or
closed-vocabulary enum members. Vulture was therefore not the instrument.

The findings below come from an AST census of every top-level definition,
method, dataclass field and class var in scope, 3,959 symbols. That census was
cross-referenced against a typed reference index over `src/ tests/ scripts/
static/ templates/ ui/ ci/ .github/ docs/ .claude/ Makefile pyproject.toml`.
The index separates code references, meaning `ast.Name`, attribute name,
keyword argument or import, from string and comment references, so a symbol
named only in a docstring does not read as used. Every finding was then
confirmed with a direct grep, quoted per finding.

Module reachability was computed from the runtime roots `src.app`,
`src.calculator` and `src.db`. 510 of 519 modules are reachable. No module in
scope is dead. All dead code sits at symbol granularity, and the largest block
is dead transitively: live modules whose only entry points are called from
tests.

These house conventions are deliberate and were excluded: closed vocabularies
with unselected members such as `Comparison.LE`, `ProcTrigger.ABILITY_DAMAGE`
and `WindowMerge.EXTEND`, all of them data-selectable or reasoned in place;
pinned frontier tables such as `item_coverage.FRONTIER`; receipt registries
consumed by `scripts/`, such as `item_source.audit_scope`,
`atomizer_domains.*`, `rune_pull.reparse_cached_rune_effects` and
`program/rung.histogram`; and fail-closed accessors with a named refusal.

## Summary

| # | Finding | File:line | Lines | Confidence | Proposal |
|---|---|---|---|---|---|
| F1 | The logical `Program` event and compile island, a closed-union event model nothing at runtime authors | `program/events.py`, `program/caches.py`, `program/build.py:41-304`, `program/compile.py:2185-2386` | 1,150 | High | Cut |
| F2 | `_STATS_ONLY_CERTIFIED_EFFECT_TEXT` and its fingerprint reader, a test fixture living in `src/` | `item_coverage.py:314`, `:732` | 432 | High | Move to `tests/` |
| F3 | `Provenance` and `AppliesTo`, an authoring invariant nothing authors | `program/amp.py:68`, `:83` | 62 | High | Cut |
| F4 | Three context-resolving interpreter siblings plus `compile_rule` | `interpreters/sustain.py:175`, `crit_profile.py:229`, `damage_routing.py:270`, `__init__.py:370` | 89 | High | Cut |
| F5 | `FightConfig.for_minion`, a second constructor for the sourced minion target | `fight/config.py:224` | 40 | High | Cut |
| F6 | `precision.ROUNDING_BY_VIEW`, `CutoffPolicy`, `damage_cutoff`, `ROUNDING` | `program/precision.py:277`, `:343`, `:363`, `:311` | 46 | High | Cut |
| F7 | Strict-API siblings of the two receipt-form eligibility decisions | `delivery_classes.py:214`, `crowd_control_eligibility.py:156`, `delivery_classes.py:160` | 42 | High | Cut |
| F8 | `TimedStackState.note_activity`, duplicate of the freeze `record_trigger` already applies | `timed_stacks.py:380` | 25 | High | Cut |
| F9 | `item_behavior_catalog.owners_for` and `declared_tags` | `:5003`, `:6170` | 34 | Medium | Cut |
| F10 | `ledger_projection` receipt trio: `unserved_conditions`, `ledger_demands`, `shield_outcome_demands` | `ledger_projection.py:158`, `:190`, `:195` | 13 | High | Cut, then collapse `_demands` |
| F11 | Write-only instance state: `_last_gain_time`, `_order`, `_prefix`, `_regen_per_second`, `assumption` | 5 sites | 26 | High | Cut, with three asides below |
| F12 | `spell_shield_rearm.rearms_within` | `spell_shield_rearm.py:101` | 14 | High | Cut |
| F13 | `starting_defenses.defense_source` | `starting_defenses.py:89` | 14 | High | Cut |
| F14 | `SumPlan.ids` | `program/sums.py:86` | 14 | High | Cut |
| F15 | `survival/receipt_state._PER_CALL_FIELDS`, a name list only a test reads | `survival/receipt_state.py:67` | 15 | High | Move to the test |
| F16 | `crowd_control_eligibility.same_hit_ordering` and `MissingSameHitRuleError` | `crowd_control_eligibility.py:356` | 22 | High | Cut |
| F17 | `item_behavior.TRIGGER_STREAM`, a second spelling of the stream vocabulary | `item_behavior.py:273` | 16 | Medium | Cut |
| F18 | `OutcomeLedger.quantities` | `survival/outcome_state.py:323` | 11 | High | Cut |
| F19 | `cast_event_row.cast_row` and `CastEventRow` | `cast_event_row.py:66`, `:37` | 14 | High | Cut |
| F20 | `_navori_effective_cd`, a wrapper over `_attack_paid_cooldown` | `fight/rotation/cast_schedule.py:47` | 9 | High | Cut |
| F21 | `FightTrace.refusals_by_source` | `fight/ledger/trace.py:68` | 7 | High | Cut |
| F22 | `CapabilityView.compilable` | `program/capability.py:67` | 6 | High | Cut |
| F23 | `atomizer.hash_domain_file` | `atomizer.py:138` | 5 | High | Cut |
| F24 | `item_behavior.policy_values` and `LivePredicate.requires_live_pool` | `item_behavior.py:3668`, `:387` | 6 | High | Cut |
| F25 | Small test-only constants: `SHARED_ROW_FIELDS`, `TOOLTIP_ONLY_CONTROL_KINDS`, `MINION_TEAMS`, `HEALING_RULE_CHAMPIONS`, `damage_event_row.event_damage_type` and `REQUIRED_FIELDS`, `heal_event_row.HEAL_REQUIRED_FIELDS` | 6 sites | 14 | Medium | Cut, except one |
| F26 | `db.CacheCounter.updated_at`, a column nothing writes or reads | `src/db.py:222` | 3 | Medium | Cut, needs a migration |
| F27 | `Field.ATTACKER_ID` and `Field.SEQUENCE`, vocabulary members no mechanic declares | `trigger_stream.py:166`, `:168` | 2 | Low | Keep |

Total removable: about 2,110 lines. F1 is 1,150 of that and F2 is 432, which is
a move rather than a delete. Excluding F2, about 1,680 lines are pure deletion.

F1 also retires `tests/test_program_events.py`, `tests/test_program_caches.py`,
most of `tests/test_program_compile.py`, `tests/test_program_build.py` and
`tests/test_program_amp.py`. Those lines are out of scope and are not counted.

## F1: the logical Program event and compile island, 1,150 lines

`program/events.py` states its purpose in its own header: close what a packet
may be into eleven payload families and five riders, so a packet whose shape
nobody anticipated cannot reach the walk and contribute zero. `build_program`
authors every event, `Projection` then selects which fields the compiler reads,
and `compile_program` is the declared entry point taking a `Program` in and a
tuple of actions out.

The composition root calls exactly one builder:

```
src/calculator/participant_timeline.py:96:   from .program.build import ParamPatch, roster_program
src/calculator/participant_timeline.py:4748: program = roster_program(all_actors)
src/calculator/participant_timeline.py:5704: program = roster_program(all_actors, focus=focus_participant_id)
```

`roster_program` returns `Program(..., events=(), ...)`. Its docstring says the
emptiness is deliberate: the composition authors its transitions as engine
packets and compiles them straight to `SurvivalAction` through `WalkCompiler`,
so no logical event list exists for those passes. No `PairEvent`, no
`RoutedEvent`, no payload family and no rider is ever constructed on the request
path.

Grep evidence, confirming no non-test caller:

```
$ grep -rn "\bcompile_program\b\|\bbuild_program\b\|\bpair_program\b\|\bderivation_order\b\|\bprogram_key\b" src scripts static templates ui ci .github docs .claude
src/calculator/program/build.py     definitions and __all__
src/calculator/program/caches.py    docstring and CacheDeclaration prose
src/calculator/program/compile.py   definitions, __all__ and docstring
0 call sites outside src/calculator/program/. tests: 25, 15, 12, 3, 14 refs.

$ grep -rn "payload_from_packet\|riders_from_packet\|PairEvent(\|RoutedEvent(" src
src/calculator/program/build.py:36,228,233,235,287   pair_program and build_program only

$ grep -rn "\bProjection\b" src
src/calculator/program/build.py, src/calculator/program/compile.py   nowhere else

$ grep -rn "program.caches\|from .caches import" src
src/calculator/program/compile.py:110-115   program_key only
```

`program/route.py`, `program/identity.py`, `program/scope.py`,
`program/rung.py`, `program/dependency.py`, `program/capability.py`,
`program/views/` and the rest of `program/amp.py` are live, reached from
`participant_timeline` and `support_event_view`. Only the event-authoring half
is dead.

The island, piece by piece:

| Symbol | File:line | Lines |
|---|---|---|
| whole module | `program/events.py` | 479 |
| whole module | `program/caches.py` | 299 |
| `Projection` | `program/build.py:41` | 12 |
| `PairProgram` | `program/build.py:70` | 5 |
| `DerivationCycle` | `program/build.py:149` | 15 |
| `derivation_order` | `program/build.py:166` | 33 |
| `pair_program` | `program/build.py:201` | 38 |
| `build_program` | `program/build.py:241` | 64 |
| `ProgramKey` | `program/compile.py:2185` | 12 |
| `program_key` | `program/compile.py:2199` | 17 |
| `_StagedPayload` and four `_stage_*` | `program/compile.py:2218-2272` | 46 |
| `_PAYLOAD_STAGING`, `_STAGED_RIDERS` and their comment blocks | `program/compile.py:2274-2295` | 22 |
| `compile_program` | `program/compile.py:2298` | 89 |
| module-docstring prose describing the above | `build.py:1-24`, `compile.py:36-40` | 25 |

Two facts in the code say this cannot be wired instead of cut.

First, `_STAGED_RIDERS: frozenset[type] = frozenset()` at `compile.py:2295` is
empty on purpose, and `compile_program` raises `UncompilableActionError` on any
event carrying a rider. `riders_from_packet` attaches an `Execute` rider to
every packet with an execute threshold and a `Wound` to every packet with a
Grievous duration. On a real fight this entry point raises before it compiles
anything. It is not one wire away from running. It is a payload compiler with
the rider axis unimplemented.

Second, `compile.py`'s own header concedes the arithmetic: the tree held nine
`SurvivalAction` construction expressions before the migration and holds ten
after it, because `compile_program` added a tenth.

What covers the purpose today: `WalkCompiler` and `action_from_event` in the
same file are the one `SurvivalAction` constructor, and
`tests/test_program_structure.py` already pins the one-constructor and
one-`run_survival_walk` invariants. The unanticipated-packet-shape concern is
covered live by `survival/compile.UncompilableActionError` on the engine-packet
path. `program/caches.py`'s `CACHES` registry declares invalidation for two
caches named "program" and "compiled_actions", whose producers are
`build_program` and `compile_program`. Neither cache exists at runtime. The
real per-search caches live in `participant_timeline.CoupledSearchContext`.

Proposal: cut. If the design is still wanted, re-land it as one change that
replaces `roster_program`'s empty-events path, with `_STAGED_RIDERS` populated.
The one part worth saving is `every_declaration`'s union with
`data_registry.GOVERNED_MEMOS`. Move those 8 lines into `data_registry.py`,
which already owns `GOVERNED_MEMOS`.

## F2: `_STATS_ONLY_CERTIFIED_EFFECT_TEXT`, 432 lines

This table pins the exact cached Wiki branch text of every item certified
`stats_only` at 2026-08-20, so `tests/test_stats_only_items.py` fails loudly
when a certified item's effect text changes. It is a golden fixture, not a rule.

```
$ grep -rn "_STATS_ONLY_CERTIFIED_EFFECT_TEXT\|stats_only_effect_fingerprint" src scripts static ui docs .claude
src/calculator/item_coverage.py:314    definition
src/calculator/item_coverage.py:732    definition of the reader
src/calculator/item_coverage.py:2478   __all__
0 other src or scripts code references. Code refs: tests only, 4 and 3.
```

`data/items.json` is the one home for the live text. The pin is the test's
baseline, and every other baseline of that kind in this repo lives under
`tests/fixtures/` or `docs/receipts/`.

Proposal: move to `tests/fixtures/stats_only_certified_effect_text.py`, or a
JSON fixture, together with `stats_only_effect_fingerprint`, 15 lines.
`item_coverage.py` drops about 432 lines and stops being the largest text blob
in `src/`. Keep `effect_entries` and `effect_text` where they are. Both are
live.

## F3: `program/amp.Provenance` and `AppliesTo`, 62 lines

`Provenance` makes two authoring defects unconstructible: a `PAIR_ENGINE` price
claiming `ALL`, which is the double count, and an amp with empty
`damage_classes` or `attack_classes`, which is incident D-04, the untyped
amplifier that multiplied a holder's true damage with a magic-only curse.

```
$ grep -rn "\bProvenance\b" src | grep -v RoutingProvenance
src/calculator/program/amp.py:7,83,370        docstring, class, __all__
src/calculator/survival/typed_action.py:270   comment only

$ grep -rn "\bAppliesTo\b" src
src/calculator/program/amp.py:68,101,118,130,364    nowhere else

Constructed only in tests/test_program_amp.py, 11 refs.
```

`RoutingProvenance` in `survival/pricing.py` is a different, live type. The rest
of `program/amp.py` is live via `participant_timeline` and `compile.py`:
`AmpRiders`, `ArmingLedger`, `live_amp_riders`, `live_amp_for`, `arm_key`.

The live typed path is `LiveAmpRider` and `LiveAmp` in
`survival/typed_action.py`, built by `live_amp_riders` from the rule's own
`payload.typing.damage_classes`. The emptiness that `Provenance.__post_init__`
refuses is already impossible there, because the classes come off the
declaration rather than off a caller.

Proposal: cut both, and `Provenance.skips` with them. If the double-count
invariant is worth keeping, put it in a `__post_init__` on `LiveAmpRider`,
which is the object the kernel reads.

## F4: three context-resolving interpreter siblings plus `compile_rule`, 89 lines

Three `interpreters/` families each ship a pair of readers: a fight-context one
and a flat one. The runtime uses the flat one in every case.

| Dead, context form | Live, flat form | Lines |
|---|---|---|
| `sustain.sustain_slot:175` | `sustain.declared_sustain:207`, `sustain.walk_slot:218` | 30 |
| `crit_profile.resolve_profile:229` | `crit_profile.declared_crit_profile:251` | 21 |
| `damage_routing.resolve_execution:270` | `damage_routing.declared_execution` | 21 |
| `interpreters/__init__.compile_rule:370` | direct `INTERPRETERS[(family, lane)]` reads | 17 |

```
$ grep -rn "sustain_slot" src
src/calculator/interpreters/sustain.py:17,175,255,333   docstring, def, message, __all__
src/calculator/item_coverage.py:1789,1794,1795          a STRING, the pricing-home label

$ grep -rn "declared_sustain" src
fight/autos/on_hit_healing.py:4,23   fight/rotation/energy_walk.py:7,42   item_sustain_events.py:13,60

$ grep -rn "resolve_profile\|resolve_execution\|\bcompile_rule\b" src
Only their own modules' def, __all__ and docstrings. 0 call sites.
```

Aside worth fixing, evidence drift rather than dead code:
`item_coverage._TARGET_MODELED_IMPLS` names `"interpreters.sustain.sustain_slot"`
as the declared pricing home for Catalyst of Aeons, Doran's Blade and Doran's
Ring, at `item_coverage.py:1789,1794,1795`. That receipt resolves only because
the symbol exists. Nothing checks it is reached. The real home for those three
is `declared_sustain`. Whoever cuts `sustain_slot` must repoint those three
strings or `tests/coverage_resolver.py` fails on an unresolvable symbol, and
the repoint is the actual correction.

Proposal: cut all four. `compile_rule`'s named refusal,
`InterpreterRegistryError`, is worth preserving. Either fold it into the two
live lookups, or route the live call sites through `compile_rule`. That second
option is the one wire-rather-than-cut candidate in this audit, because the
registry-is-the-dispatch property it asserts is real and currently unenforced.

## F5: `FightConfig.for_minion`, 40 lines

This is meant to be the one constructor that fills a fight config's target
durability from a lane minion's own CommunityDragon record, so sourced and
caller-supplied never both answer for one field.

```
$ grep -rn "for_minion" src scripts static ui docs .claude
src/calculator/fight/config.py:86,216,224,250,320   its own def plus three prose and message mentions
Call sites: tests/test_minion_stats.py only, 8 refs.
```

The request path builds the same fields through
`fight_request_bounds._request_target_durability` and
`fight.config.sourced_minion_target`, reached from `fight_params.py:204-240`.
`FightConfig._validate_minion_target`, which is live and called from
`__post_init__`, enforces the identical invariant on any config however built.
`for_minion` is a second home for a fact `sourced_minion_target` already owns.

Proposal: cut, and update the two error messages that name it at
`fight/config.py:250` and `:320` to point at `sourced_minion_target`.
`MINION_TEAMS` at `minion_stats.py:60`, 1 line, tests only, goes with it.

## F6: precision view grouping and cutoff policy, 46 lines

```
$ grep -rn "ROUNDING_BY_VIEW\|CutoffPolicy\|damage_cutoff\|\bROUNDING\b" src
src/calculator/program/precision.py only, definitions and __all__.
Code refs: tests only, 1, 4, 3 and 19.
```

`ROUNDING_BY_VIEW`, 11 lines, is a second per-view grouping of the same seven
tables that `_TABLES` and `_FLAT` already flatten for the live `digits_for` and
`round_field`. `CutoffPolicy`, 18 lines, is a one-member enum whose docstring
explains that a second member is what a decision to change it would look like,
and `damage_cutoff`, 14 lines, is its only reader. No view computes a damage
cutoff this way. `ROUNDING` is the flat map re-exported for a test that
`digits_for` already serves.

Proposal: cut all four. `round_field`, `digits_for` and `UnregisteredField`
stay.

## F7: strict-API siblings of two eligibility decisions, 42 lines

Both functions say in their own docstring that they are the strict API for a
decision that must resolve, and that the eligibility decision path uses the
receipt form instead. The receipt form is what runs.

```
$ grep -rn "required_delivery_class" src   -> delivery_classes.py:214, the def, only
$ grep -rn "required_control_class"  src   -> crowd_control_eligibility.py:156,382 only
$ grep -rn "\.has(" src | grep -i delivery -> 0.  DeliveryProfile.has: tests only.
```

`classify_delivery` and `classify_control`, the receipt forms, are live.
`UnknownDeliveryError` and `UnknownControlError` are raised elsewhere, so the
exception classes stay.

Proposal: cut `required_delivery_class`, 23 lines, `required_control_class`, 16
lines, and `DeliveryProfile.has`, 3 lines.

## F8: `TimedStackState.note_activity`, 25 lines

```
$ grep -rn "note_activity" src
src/calculator/stack_rules.py:49    docstring, "each gain or note_activity (Rengar's in-combat rule)"
src/calculator/timed_stacks.py:380  def
Call sites: tests only, 3 files.
```

`TimedStackState.record_trigger` at `timed_stacks.py:218-235` already re-arms
`_freeze_until` from `combat_extension_seconds` and records the same
`combat_freeze` transition. Rengar is the only declarer, at
`champions/rengar.py:136` with `combat_extension_seconds=10.0`, and his freeze
runs through the gain path.

Aside: the modelled behaviour is therefore that the freeze re-arms on a stack
gain, not on any damage event. If those differ for Ferocity, that is a modelling
gap the dead method was meant to close and never did. Worth a sourced check
before deleting the name.

Proposal: cut.

## F9: `item_behavior_catalog.owners_for` and `declared_tags`, 34 lines

```
$ grep -rn "owners_for\|declared_tags" src
src/calculator/item_behavior_catalog.py:5003,6170   defs
src/calculator/item_behavior_catalog.py:6619,6623   __all__
owners_for: tests only, 4 files. declared_tags: tests only, 1 file.
```

Both are migration-counter readers derived from the registries. `producers_for`,
the inverse of `owners_for`, is live. `undeclared_entry_count`, 3 lines, is
tests plus scripts and stays.

Proposal: cut. If the counters are still a gate, move them to `scripts/` beside
the other counter readers.

## F10: `ledger_projection` receipt trio, 13 lines plus a dead branch

```
$ grep -rn "unserved_conditions\|ledger_demands\|shield_outcome_demands" src
src/calculator/ledger_projection.py:158,190,195   defs
src/calculator/ledger_projection.py:227,229,231   __all__
Call sites: tests only.
```

The live reader is `ledger_projection(inputs)`, which calls `_demands(...,
stop_at_first=True)`. With the three dead readers gone, `_demands`'s
`stop_at_first` parameter has one value at every call site and the loop
simplifies to first-match-wins.

Proposal: cut the three, then inline `stop_at_first`.

## F11: write-only instance state, 26 lines

All five are assigned and never read.

| Symbol | File:line | Evidence | Note |
|---|---|---|---|
| `TimedStackState._last_gain_time` | `timed_stacks.py:55,142,187,301,323,331,349,454` | 8 assignments, 0 reads | goes with F8 |
| `StateTimeline._order` | `state_timeline.py:152,171` | set to 0, then incremented, never read | see aside |
| `LeafBlock._prefix` | `program/views/leaf.py:79,97` | in `__slots__` and assigned. Only `_dot`, derived from it, is read | hot path: one slot per block, per participant, per candidate |
| `ResourceAccount._regen_per_second` | `resource_ledger.py:117` | assigned, never read | see aside |
| `AllyStatEffect.assumption` | `ally_effects.py:37,138` | set once to a real disclosure sentence, never read anywhere including tests | see aside |

Aside: `StateTimeline._order` is the fix for an O(n squared) sort. The class
docstring promises the sort key `(time, tier, sequence, insertion_order)`, and
`_order` is plainly the intended insertion counter. `transitions()` instead does
`key=lambda t: (t.time, t.tier, t.sequence, self._transitions.index(t))`.
`list.index` is O(n) with `__eq__` per element, so the sort costs O(n squared
log n) comparisons on a per-fight timeline. Either stamp `_order` onto each
`Transition` and sort on it, or drop the fourth key element entirely, since
`sorted` is stable and insertion order is already the tie-break. Do not delete
`_order` without picking one.

Aside: `ResourceAccount` takes a regen it never applies. `regen_per_second` is
a parameter on both `ResourceAccount.__init__` and `ResourceLedger.__init__`,
with a 5-line finiteness validation, threaded from
`fight/rotation/mana_walk.py:52-58`. The account never uses it.
`mana_walk.py:193-204` computes `regen_amount` from its own local `regen` and
emits an `OP_REGEN` event. The parameter, the validation, the attribute and the
call-site keyword are about 11 lines pulling no weight.

Aside: `AllyStatEffect.assumption` carries an undisclosed disclosure.
`ally_effects.py:138` sets it to a sentence saying the ally healed or shielded
the attacker immediately before combat. Nothing publishes it. This is the one
candidate where wiring beats cutting: the sentence is a real modelling
assumption and the response already has a disclosure channel for unmodeled
context.

## F12 to F24: individually confirmed test-only symbols

Each was confirmed with `grep -rn "<name>" src tests scripts static templates ui
ci .github docs .claude`, showing zero `src/` code references outside the
defining module's own `def`, `__all__` and docstring.

| # | Symbol | File:line | Lines | Purpose, and what covers it today |
|---|---|---|---|---|
| F12 | `SpellShieldRearmClock.rearms_within` | `spell_shield_rearm.py:101` | 14 | Whether the rearm lands inside the fight window. `rearmed_at`, live, answers the question the walk asks off the same `ready_at` |
| F13 | `starting_defenses.defense_source` | `starting_defenses.py:89` | 14 | One owner's `DefenseCitation`. The live producers call `receipt_for(...)` directly |
| F14 | `SumPlan.ids` | `program/sums.py:86` | 14 | The ids a plan folds. `receipt.py:681` only mentions it in a comment. The live fold reads the rows |
| F15 | `_PER_CALL_FIELDS` | `survival/receipt_state.py:67` | 15 | Name the 14 fields resolved per call rather than memoized. The per-call resolution is hand-written beside the pools, so this tuple exists only for a test to assert against. That is a second name list |
| F16 | `same_hit_ordering` and `MissingSameHitRuleError` | `crowd_control_eligibility.py:340,356` | 22 | A declared refusal for an unverified ordering rule. The function body is a single `raise` and no caller ever asks |
| F17 | `item_behavior.TRIGGER_STREAM` | `item_behavior.py:273`, plus 7 lines of prose at `:257` and `:21` | 16 | Join `TriggerEvent` to `trigger_stream.Stream`. Its own comment says the projection is asserted in the test front door. `trigger_stream.CAPABILITIES` is the one place a mechanic declares its stream, and CLAUDE.md forbids a second name list |
| F18 | `OutcomeLedger.quantities` | `survival/outcome_state.py:323` | 11 | Every numeric outcome field of one slot. `quantity(slot, field)`, live, is what the views call, per field |
| F19 | `cast_row` and `CastEventRow` | `cast_event_row.py:66`, `:37` | 14 | A whole-row reader for a caller wanting more than one field. Every live reader uses `cast_time`, `cast_slot` or `cast_ordinal` |
| F20 | `_navori_effective_cd` | `fight/rotation/cast_schedule.py:47` | 9 | Navori's share-of-remaining refund. A 3-line pass-through to `_attack_paid_cooldown(..., refund_percent=...)`, which live callers use directly |
| F21 | `FightTrace.refusals_by_source` | `fight/ledger/trace.py:68` | 7 | Per-source refusal rollup. `published()` emits `line.refusals` per line, and `scripts/fight_trace.py` can group |
| F22 | `CapabilityView.compilable` | `program/capability.py:67` | 6 | Whether every mechanic can compile. `refusals()`, live, answers it and names why |
| F23 | `atomizer.hash_domain_file` | `atomizer.py:138` | 5 | Re-hash a domain file from disk. `content_hash(json.loads(path.read_text()))` is two live lines |
| F24 | `policy_values`, `LivePredicate.requires_live_pool` | `item_behavior.py:3668`, `:387` | 6 | Flatten policy sites, and let interpreters branch. `policy_walk(rule).sites` is live. `requires_live_pool` returns a literal `True` and no interpreter branches on it, they `isinstance` on `LivePredicate` |

## F25: small test-only constants, 14 lines

| Symbol | File:line | Evidence |
|---|---|---|
| `ledger_inputs.SHARED_ROW_FIELDS` | `:61` | 6 lines. `grep -rn SHARED_ROW_FIELDS src` finds the definition only. Tests: 9 refs |
| `cleanse_eligibility.TOOLTIP_ONLY_CONTROL_KINDS` | `:117` | 1 line, definition only in src |
| `minion_stats.MINION_TEAMS` | `:60` | 1 line, definition only in src. `tests/test_minion_stats.py` compares the teams from the file names |
| `healing.HEALING_RULE_CHAMPIONS` | `:65` | 1 line. Src uses `_HEALING_RULES` directly. Keep it: `architecture.md` and eight champion module docstrings name it as the public surface |
| `damage_event_row.event_damage_type` and `REQUIRED_FIELDS` | `:66`, `:48` | 4 lines. The siblings `event_damage` and `event_time` are live |
| `heal_event_row.HEAL_REQUIRED_FIELDS` | `:41` | 1 line |

Proposal: cut all but `HEALING_RULE_CHAMPIONS`.

## F26: `db.CacheCounter.updated_at`, 3 lines

```
$ grep -rn "updated_at" src tests scripts docs
src/db.py:222                    the column
src/rate_limit.py:38,65,85,89    a different table's SQL column, token_buckets
docs/database-schema.md:99       documentation of this column
```

The column is populated by its `default=_utcnow` on insert and never written or
read again, so its value is the row's creation time under a name that promises
otherwise. Cutting it needs a schema migration. The cheaper honest fix is to
stamp it wherever `hits` and `misses` are incremented. Low payoff either way.

## F27: `Field.ATTACKER_ID` and `Field.SEQUENCE`, 2 lines, keep

```
$ grep -rn "Field.ATTACKER_ID\|Field.SEQUENCE" src tests scripts docs   ->  0 hits
```

No mechanic's `needs=frozenset({...})` declares either, and `Field` is never
constructed from a value string, so both members are genuinely unreferenced.
They are members of a closed raw-row-field vocabulary of the kind CLAUDE.md
protects, `control_spec.CC_KIND_VOCABULARY` being the canonical example, and
both fields exist on the raw rows. Listed for completeness. Do not cut.

## Dimensions checked that came back clean

Modules nobody imports outside tests: 510 of 519 modules are reachable from the
runtime roots. The 9 unreachable are `atomizer_domains`, live via
`scripts/atomize.py` which the `atomizer` skill documents, and eight one-line
`fight/*/__init__.py` docstring files, which are packages.

Exception classes never raised: zero. The three flagged by the AST scan,
`CastDependencyError`, `ActiveCastInterpretationError` and
`SpellbladeInterpretationError`, are respectively a base class of ten
subclasses and two `stop=` injection parameters.

Function parameters never used in a body: 17 hits, all no-op protocol
implementations in `survival/score_state.py`, `survival/transitions.py`'s null
ledger, and `program/views/leaf.py`'s recorder. Not dead.

`item_behavior` payload fields flagged by vulture, such as `basis_unit`,
`per_lethality_ratio`, `grants_level_at_max`, `trigger_window`,
`nonchampion_damage_cooldown`, `overrides_cached_stat` and `flat_base`: all
read via `getattr` through `STAT_DERIVATION_REQUIRED_REFERENCES` and
`STAT_DERIVATION_OPTIONAL_REFERENCES` at `item_behavior.py:3334-3392`. Not
dead.

`cast_edge_resolution` ledger fields `inactive`, `suppressed`, `latent` and
`confirmed_by_inference`: written by the resolver and published through
`scripts/cast_dependency_audit.py`'s `DECLARATION_ROUTES`. Not dead.

`src/*.py`, meaning `app.py`, `db.py`, `metrics.py`, `rate_limit.py`,
`beta_gate.py` and `service_auth.py`: clean apart from F26. Every one of the 28
zero-reference functions is a Flask route, `before_request`, `after_request` or
`errorhandler`.

`rune_paths/`: zero dead symbols. The published-compiler-table discipline in
`publish_rune_compilers` leaves no orphans.

`survival/`: two findings only, F15 and F18. The kernel is tight.

`__all__` entries: no entry names a missing symbol. The entries that export
dead code are covered by the findings above.

## Suggested order of work

1. F1, one change, about 1,150 lines. No runtime behaviour to verify beyond
   `pytest` and both golden compares. A pure deletion must show zero diffs.
2. F2, a mechanical move of about 432 lines out of `src/`.
3. F4 plus the `item_coverage._TARGET_MODELED_IMPLS` repoint. This is the only
   finding with a correctness tail.
4. The three asides under F11. The `StateTimeline` sort is the one item here
   with a measurable payoff beyond line count.
5. Everything else as one sweep, about 450 lines.
