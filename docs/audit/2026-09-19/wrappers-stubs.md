# Slop audit: stubs, wrappers and indirection

Scope: all of `src/` except the 173 registered champion modules under
`src/calculator/champions/`. The 34 shared helpers in that package are in
scope, including `slotlib.py`, `slot_extract.py`, `inputs.py` and
`packet_module.py`.

Measured tree: 346 modules, 130,715 lines, 5,099 definitions. That is 2,252
top-level functions, 3,005 functions in all, 621 classes, 1,473 module-level
assignments.

Method: an AST index of every definition and every `Call`, `Name` and
`Attribute` reference across `src/`, `tests/` and `scripts/`. The scripts are
`.audit/wrap_*.py` and the receipts are `.audit/wrap_defs.json`,
`wrap_calls.json`, `wrap_oneliners.json`, `wrap_modrefs.json` and
`wrap_near.json`. Counts for a name that collides with a local variable, such
as `cast_time` or `value`, are upper bounds and were checked by hand. Counts
for a name reached through an aliased import such as `x as _x` are lower
bounds and were checked by hand too.

## Verdict

The style is mostly honest. 443 of 2,252 top-level functions hold a single
statement, and most of them bind a constant into a shared resolver:
`champion_stat`, `bool_option`, `int_option`, `walk_slot`. Those have tens to
hundreds of call sites and earn their names. The decay sits in four places.

1. A 16-name package facade with no consumers that costs every process 0.5 s
   of eager import. See F1.
2. A 12-member clone family in `interpreters/` whose members differ by one
   enum value. See F2.
3. About 20 single-call renames, one per module. See F8.
4. Nine closed vocabularies written twice, once as `Literal` and once as a
   `frozenset`. See F4.

Removable: about 290 lines and one module, plus a measured 0.5 s import win.
The largest single item is 72 lines.

## Counts per category

| # | Category | Found | Judged noise | Est. lines |
|---|---|---|---|---|
| 1 | Pass-through functions, one `return call(...)` forwarding its own parameters | 90, of which 21 exact and 69 near | 14 | 86 |
| 2 | Re-export modules and module-level aliases | 4 facades, 22 `partial` aliases, 12 plain aliases | 1 facade, 3 aliases | 41 |
| 3 | Single-use abstractions, one producer and one consumer | 5 single-member enums, 9 duplicated vocabularies, 11 Protocols, 1 dead record | 10 | 42 |
| 4 | Layered accessors | 6 `f` to `_f` chains, 16 bare `@property` getters, 5 slot forwards | 3 | 12 |
| 5 | Leaf modules under 40 lines | 23, of which 13 are package `__init__` or empty | 1 | 16 and 1 module |
| 6 | One-caller functions | 426 top-level with one src call site, 746 with one call site anywhere | 11, listed in F8 | 55 |
| 7 | Stubs: `...`, `raise NotImplementedError`, constant return | 8 plus 5 plus 3 | 1 | 4 |
| 8 | Kwarg plumbing, 8 or more parameters | 59 functions, tail at 29, 22, 19, 18, 16 | 0 | 0 |
| 9 | Clone families, same body one token apart | 3 families: 12 `*_rules`, 5 `def field`, 4 `_compile_*_defense` | 3 | 110 |

Totals: about 45 findings, about 290 removable lines, one removable module.

## Summary table, ranked by payoff

| Rank | Finding | Path | Payoff |
|---|---|---|---|
| 1 | Dead 16-name package facade. It forces an eager import of `champions` at 360 ms and `damage` at 175 ms on any leaf import | `src/calculator/__init__.py:1-38` | 37 lines and 0.5 s import |
| 2 | 12 `*_rules(owners)` clones differing by one `RuleFamily` member | `src/calculator/interpreters/*.py` | 72 lines, 12 concepts to 1 |
| 3 | 4 `_compile_*` wrappers that all forward to `_compile_defense` unchanged | `item_behavior_catalog.py:5215-5248` | 28 lines |
| 4 | `Literal` and a parallel `frozenset` for the same 9 closed vocabularies | `reference_vocabulary.py`, `coverage_evidence.py` | 18 lines, 9 facts to 9 homes |
| 5 | A whole module for `base + ratio * stat` with no production caller | `src/calculator/champions/common.py` | 16 lines and 1 module |
| 6 | `CastEventRow` and `cast_row`, a record and its only producer, no production consumer | `cast_event_row.py:37-74` | 19 lines |
| 7 | 5 byte-identical `def field(name, value) -> KernelField` closures | `interpreters/amp_magnitude.py`, `damage_routing.py` twice, `resistance_shred.py`, `secondary_target.py` | 10 lines |
| 8 | 11 single-call renames | various | 55 lines |
| 9 | `public_patch` and `client_patch` with no production caller | `patch_identity.py:42-47` | 9 lines |
| 10 | `is_champion_supported`, `event_damage_type`, `requires_live_pool`, dead or test-only | 3 files | 13 lines |
| 11 | `survival/__init__.py` re-exports 38 names for 1 production importer while its sibling `program/` states it re-exports nothing | `survival/__init__.py` | inconsistency, 0 lines |
| 12 | 37 imports renamed to a leading underscore | `participant_timeline.py` 18, `app.py` 12, 4 others | readability only |

## F1: a 16-name facade nobody imports

`src/calculator/__init__.py:1-38` imports 16 names from 8 submodules and lists
them in `__all__`. An AST sweep of every `from src.calculator import X` and
`from calculator import X` in `src/`, `tests/` and `scripts/` finds zero
consumers of any of the 16:

```
FightConfig                  0     ITEM_EFFECTS                 0
apply_armor_penetration      0     apply_magic_penetration      0
apply_resistance             0     calculate_ability_damage     0
calculate_fight_damage       0     calculate_total_stats        0
fetch_champion_data          0     fetch_item_data              0
get_ability_rank             0     get_champion                 0
get_item_by_name             0     growth_stat                  0
is_champion_supported        0     parse_abilities              0
```

All 182 `from src.calculator import ...` statements in the tree name a
submodule such as `item_effects` or `item_coverage`, never a facade name.

The cost is measured. `python -X importtime -c "import
src.calculator.quantity"` on this tree, where `quantity` is a leaf that costs
1.5 ms of its own:

```
import time:      2195       359740       src.calculator.champions
import time:       649       175278       src.calculator.damage
import time:     51061        63753         src.calculator.item_effects
import time:       332       538139     src.calculator
import time:        15       538153   src.calculator.quantity
```

538 ms to import a leaf, and 535 ms of that is the facade's own imports. Line
40, `publish_rune_compilers()`, is load-bearing per CLAUDE.md and costs 2.3 ms.

Proposal: delete lines 1 to 38, keep the `from .rune_paths import
publish_rune_compilers` import and the call. Nothing pins `__all__`.
`tests/test_architecture.py`'s `FRONT_DOOR_FRONTIER` covers modules, not this
list. Run the full suite afterwards. The risk is an import side effect
somebody relies on implicitly, not a named reference.

## F2: twelve `*_rules(owners)` clones in `interpreters/`

Eight of these are identical apart from one `RuleFamily` member.

| Path and line | Function | Family | Call sites |
|---|---|---|---|
| `interpreters/active_cast.py:92` | `active_rules` | `ACTIVE_CAST` | 1, own file |
| `interpreters/cast_proc.py:249` | `cast_proc_rules` | `CAST_PROC` | 2, own file |
| `interpreters/charged_strike.py:300` | `charged_strike_rules` | `CHARGED_STRIKE` | 2, own file |
| `interpreters/crit_profile.py:179` | `crit_rules` | `CRIT_PROFILE` | 1, own file |
| `interpreters/damage_routing.py:327` | `walk_rules` | `DAMAGE_ROUTING` | 1, own file |
| `interpreters/on_hit_strike.py:219` | `strike_rules` | `ON_HIT_STRIKE` | 1, own file |
| `interpreters/periodic.py:123` | `periodic_rules` | `PERIODIC` | 2, own file |
| `interpreters/spellblade.py:75` | `spellblade_rules` | `SPELLBLADE` | 2, own file |

The body in all eight:

```python
return tuple(
    rule
    for owner in owners
    for rule in behavior_rules(owner)
    if rule.family is RuleFamily.<X>
)
```

Four more add one `isinstance(rule.payload, <T>)` clause on the same skeleton:
`resistance_shred.py:216 shred_rules`, `stat_derivation.py:142
stat_derivation_rules`, `sustain.py:163 sustain_rules` and `delta_amp.py:336
slot_rules`.

No one of the twelve is imported by another module. Every call site is in the
defining file.

Proposal: one `rules_of(owners, family, payload_type=None)` in
`interpreters/__init__.py`, or a `interpreters/rule_selection.py` leaf. Each
interpreter then calls it at its one or two sites. Twelve names that carry no
information beyond the enum they pass become one. 96 lines become 24.

## F3: four identical `_compile_*` defence wrappers

`item_behavior_catalog.py:5215`, `:5224`, `:5233` and `:5242`. All four read:

```python
def _compile_opening_defense(family, source, entry) -> tuple[BehaviorRule, ...]:
    """Defences already in force when the modeled exchange opens."""
    return _compile_defense(family, source, entry)
```

Only the docstring differs. Each has exactly one reference, its row in
`_COMPILERS` at lines 5949 to 5952.

The comment above `_COMPILERS` states the rule they serve: "One module-level
`def` per key, keyed by a closed enum, totality asserted, D-52's three
conditions." So the shape is deliberate. The honest reading is that D-52 costs
28 lines here to hide the fact that four families share one compiler.

Proposal: map the four `RuleFamily` members straight to `_compile_defense` and
move the four sentences into a comment block above those four table rows. If
D-52 must hold literally, keep the wrappers and say in the D-52 comment that
the four defence keys are one compiler under four names. As written, the table
reads as four compilers.

## F4: nine closed vocabularies written twice

Each of these declares a `Literal` and, right below it, a `frozenset` with the
same members.

| Module | `Literal` | Parallel `frozenset` | Members |
|---|---|---|---|
| `reference_vocabulary.py:8,11` | `ValueRegistry` | `VALUE_REGISTRIES` | 3 |
| `reference_vocabulary.py:22,25` | `StructuralReason` | `STRUCTURAL_REASONS` | 6 |
| `reference_vocabulary.py:36,39` | `LevelScale` | `LEVEL_SCALES` | 3 |
| `reference_vocabulary.py:56,59` | `DerivedOp` | `DERIVED_OPS` | 6 |
| `coverage_evidence.py` | `ClaimLane` | `LANES` | 4 |
| `coverage_evidence.py` | `ClaimStatus` | `CLAIM_STATUSES` | 8 |
| `coverage_evidence.py` | `SymbolRole` | `SYMBOL_ROLES` | 6 |
| `coverage_evidence.py` | `OwnerPolicy` | `OWNER_POLICIES` | 3 |
| `coverage_evidence.py` | `EvidenceRegistry` | `EVIDENCE_REGISTRIES` | 4 |

This breaks CLAUDE.md rule 3 in the two modules whose job is to be the one home
for a vocabulary. 43 member strings are each written twice, with nothing
keeping the two copies in step.

Proposal: `VALUE_REGISTRIES: frozenset[str] = frozenset(get_args(ValueRegistry))`
using `typing.get_args`, nine times. The runtime set then derives from the
type, and a member added to one can no longer be missing from the other.

## F5: `champions/common.py`, a module for one arithmetic line

```python
def calculate_ability_damage(base_damage, scaling_ratio, scaling_stat) -> float:
    """Public scalar convenience for base + ratio × stat damage."""
    return base_damage + (scaling_ratio * scaling_stat)
```

The full reference set across the tree:

```
src/calculator/champions/common.py:10   def
src/calculator/__init__.py:2            re-export, the dead facade of F1
src/calculator/__init__.py:27           __all__ entry
tests/test_champion_primitives.py       3 assertions
```

No production caller. The module docstring says its only reason to exist is
"the scalar helper that `calculator.__init__` re-exports", and that facade has
no consumers.

Proposal: delete the module, the two `__init__` lines and the three test
assertions, which test `a + b * c`. Move the docstring's orientation sentence
about where the parse layer lives into `champions/__init__.py`.

## F6: `CastEventRow` and `cast_row`, a record with no consumer

`cast_event_row.py:37-46` holds a 5-field frozen dataclass, and `:66-74` holds
its only producer. The whole-tree reference set is the two definitions, the two
`__all__` entries, the single `CastEventRow(...)` call inside `cast_row`, and
three assertions in `tests/test_cast_event_row.py`. No production code
constructs or reads a `CastEventRow`.

The module's three field accessors `cast_time`, `cast_slot` and `cast_ordinal`
are used and should stay. They are the rule 5 surface the module docstring
justifies.

Proposal: delete the dataclass, `cast_row`, their `__all__` entries and the
three tests. If "a reader that wants the whole row" is a real anticipated
consumer, say so in the docstring instead of shipping the record for it.

## F7: five identical `field` closures

```python
def field(name: str, value: float) -> KernelField:
    return KernelField(name=name, value=value, lane=lane, rule_id=rule.mechanic_id)
```

at `interpreters/amp_magnitude.py:198`, `damage_routing.py:96`,
`damage_routing.py:141`, `resistance_shred.py:116` and
`secondary_target.py:66`. Black spreads the last one over six lines.

Proposal: `field = partial(KernelField, lane=lane, rule_id=rule.mechanic_id)`
at each site, one line each, or one shared `field_binder(rule, lane)` in
`interpreters/__init__.py`. CLAUDE.md already records `partial` as the house
answer to this shape, in `event_row_field._required` and
`generated_file.main`.

## F8: eleven single-call renames

Each is a `def` whose body is one call forwarding the same arguments, with one
production call site. The name restates the callee.

| Path and line | Wraps | Production call sites | Proposal |
|---|---|---|---|
| `fight/rotation/cast_schedule.py:47` `_navori_effective_cd` | `_attack_paid_cooldown` at `:57` | 0, with 6 test calls | delete, point the tests at `_attack_paid_cooldown` |
| `item_effects.py:1053` `input_option_stat_bonuses` | `_input_option_stat_bonuses` at `:1026` | 1, `stats.py:114` | rename the private to the public name, delete the wrapper |
| `survival/transitions.py:2552` `_interaction_event_key` | `stable_event_key` | 5, same file | call `stable_event_key` directly |
| `bis_candidates.py:81` `role_scoped_bis_candidates` | `role_scoped_shop_items(candidates, role)` | 1, `:112` same file | inline, and move the 6-line comment above it to the call site |
| `economy.py:71` `item_sell_value` | `sourced_sell_value` | 1, `:298` same file | inline. `sourced_total` and `sourced_combine_cost` are already called directly in the same file |
| `participant_timeline.py:489` `_rune_plating` | `_one_rune_walk_effect(c, RunePlatingEffect)` | 1, `:474` | inline |
| `participant_timeline.py:494` `_rune_regeneration` | `_one_rune_walk_effect(c, RuneRegenerationEffect)` | 1, `:438` | inline |
| `rune_paths/__init__.py:93` `keystone_compilers` | `dict(keystones.COMPILERS)` | 1, `:89` | inline, and move the 2 test calls to `dict(keystones.COMPILERS)` |
| `rune_paths/__init__.py:98` `shard_compilers` | `dict(shards.COMPILERS)` | 1, `:89` | inline |
| `champions/skill_orders.py:134` `get_skill_order` | `_SKILL_ORDERS.get(name, DEFAULT_SKILL_ORDER)` | 1, `:145` same file | rename to `_get_skill_order`. Nothing outside the module calls it, so the public name claims an API with no consumer |
| `passive_parser.py:1968` `_json_name` | `_REVERSE_ALIASES.get` | 1, same file | inline |

Kept from the same scan, with reasons:

- `ability_spec.py:45 DamageClass.named`, which wraps `_DAMAGE_CLASSES.get` and
  has 34 src sites. It is the enum's one lookup surface.
- `champions/inputs.py` `champion_stat`, `target_stat`, `bool_option`,
  `int_option` and `float_option`, which wrap `_resolve` and `_option` with
  68, 49, 106, 163 and 44 src sites. They are typed specialisations and the
  tree's most-used API.
- `interpreters/resistance_shred.py:265,275` `resolve_slot` and `walk_slot`,
  which bind `EngineLane`. architecture.md declares "one interpreter per family
  per engine lane", so the two names are the lane contract.
- `stats.py:465 resolve_pre_combat_stats`, 8 parameters into
  `calculate_total_stats`. architecture.md names it as the one composition
  every participant resolves through, with all five inputs required keywords.
- `binary_roots.py:228,235,341`, `role_quests.py:185,192` and
  `ledger_adequacy.py:112,122`, each of which binds cached-data keys or an
  enum. That is the point of rule 5.
- `ally_packet_recipient.py:82 reprice_slot`, which carries `@cache`. The
  wrapper is the memo boundary.
- `participant_timeline.py:5037 compose`, which forwards 14 arguments. It is a
  closure, not plumbing: `params`, `pair_result_cache`, `search_context` and
  `include_receipt` are rebound in the loop below it, so a `partial` bound
  before the loop would freeze stale values. Keep it, and put that reason in
  its docstring.

## F9: `public_patch` and `client_patch`

`patch_identity.py:42-47`. Both read `return canonical_patch(value).<field>`.
The only production reader, `data_registry.py:387-397`, calls `canonical_patch`
once and reads `identity.public_patch` and `identity.client_patch` off the
record, which is the better API. The two convenience functions have no
production call sites, and carry 4 and 2 test assertions.

Proposal: delete both and move the two tests onto `canonical_patch`.

## F10: three dead or test-only definitions

- `champions/__init__.py:1077 is_champion_supported`. No call sites and no
  references outside the dead facade of F1. Delete.
- `damage_event_row.py:66 event_damage_type`. No production call sites, while
  the siblings `event_time`, `event_damage` and `event_source` have 20 to 40
  each. Keep it with a note: the four accessors are the declared contract over
  `REQUIRED_FIELDS = ("time", "damage", "damage_type", "source")`.
- `item_behavior.py:385-388 LivePredicate.requires_live_pool`. A `@property`
  that always returns `True`, whose docstring says "the field exists so
  interpreters can branch on it". No interpreter branches on it. Two comments
  mention it and one test asserts it. Delete, or make it real by giving the
  union a second member that answers `False`.

## F11: `survival/__init__.py` re-exports 38 names

`survival/__init__.py:46-124` re-exports 38 names. `__all__` is declared as
"the package's declared API, so growing it is an API change". The only
production importer is `participant_timeline.py`, with three `from .survival
import` statements. Everything else that touches the kernel imports the
submodule directly: `from .survival import phases`, `survival.compile`,
`survival.receipt_state`.

The inconsistency is with its own sibling. `program/__init__.py:10` says "The
package deliberately re-exports nothing. Each module is imported by its own
dotted path so that a reader, and the derived front-door registry, can see
which module holds which concept." `program/views/__init__.py:15` sets
`__all__ = []`.

Proposal: keep the facade if the kernel API boundary is deliberate, and record
that in architecture.md beside the `program/` rule. As written, the two
packages state opposite policies with no note that the difference is intended.
Otherwise point `participant_timeline`'s three imports at the submodules and
drop the facade.

## F12: 37 imports renamed to a leading underscore

| File | Count |
|---|---|
| `participant_timeline.py` | 18 |
| `app.py` | 12 |
| `scenario.py` | 3 |
| `fight_params.py` | 2 |
| `data_updater.py` | 1 |
| `fight/setup/stat_buff_ultimates.py` | 1 |

An example: `from .roster_composition import defensive_signature as
_defensive_signature`. The rename adds no meaning, hides the real name from
grep, and makes every call-site counter under-report. It made four live
functions look dead on this audit's first pass. No lines saved, real
readability and greppability cost.

Proposal: import each name as it is spelled.

## F13: layered accessors

Six `f` to `_f` same-name chains exist.

| Chain | Callers of the outer | Verdict |
|---|---|---|
| `interpreters/crit_profile.py:119 _flat_fields` calls `flat_fields` | 1 | keep, it binds 3 extra arguments including the error type and reader name |
| `interpreters/damage_routing.py:238 _flat_fields` calls `flat_fields` | 1 | keep, same |
| `interpreters/resistance_shred.py:265 resolve_slot` calls `_resolve_slot` | 4 | keep, lane contract |
| `item_effects.py:1053 input_option_stat_bonuses` calls `_input_option_stat_bonuses` | 1 | inline, see F8 |
| `timed_stacks.py:376 materialize_expiries` calls `self._materialize_expiries` | 1 | keep, public and private split on a mutable state object |
| `value_ref.py:464 DeclaredNumbers.ramp` calls `self._ramp` | 5 | keep, `_ramp` has 2 callers |

The deepest chain in the tree is the declared-number read, at four levels:

```
DefenseSlot.value(key)            interpreters/defense_state.py:90
  DeclaredNumbers.value(key)      value_ref.py:450
    self._declared(ValueRef, ...) value_ref.py:446
      declared_reference(...)     value_ref.py:414   the only loop
```

`AllyPacketSlot.value`, `AllyPacketSlot.level_value`, `DefenseSlot.ramp` and
`DefenseSlot.late_ramp` are four more level-1 forwards onto `self._numbers`.
Every intermediate has two or more callers and layer 1 has about 1,200 call
sites, so keep them. Making `_numbers` a public `numbers` field would remove
the five forwards without touching a call site's arithmetic. Worth doing only
if the file is open anyway.

Of 91 `@property` definitions, 85 hold one statement and 16 return a bare
`self._x`. All 16 sit on mutable ledger or state objects: `ManaflowLedger`,
`ResourceAccount`, `CooldownState`, `TriggerGate`, `TimedStackState`,
`WindowStackGate`. The getter is the read-only surface over mutable private
state. Keep. The two exceptions are `value_ref.py:224,287 LevelValueRef.key`
and `LateLevelValueRef.key`, which rename a frozen dataclass field and have no
readers outside their own file. `declared_reference` reads `key` generically,
so keep them and say that in the docstring.

## F14: leaf modules under 40 lines

| Lines | Module | Verdict |
|---|---|---|
| 0 | `src/__init__.py` | keep, namespace |
| 1, nine times | `fight/__init__.py` and the 8 step packages | keep. architecture.md: "Each `__init__.py` holds one docstring line and no re-export" |
| 12 | `fight/ledger/breakdown.py` | keep. `_is_auto_stream_key` has 3 importers in 2 subpackages. Rename it off the underscore: a cross-package import of a private name contradicts itself |
| 12 | `wiki_fetch.py` | keep. `http_get = requests.get` is the monkeypatch seam `tests/test_security_utilities.py:42` uses |
| 13 | `program/__init__.py` | keep, docstring only |
| 16 | `champions/common.py` | delete, see F5 |
| 18 | `program/views/__init__.py` | keep, `__all__ = []` by rule |
| 19 | `atom_spelling.py` | keep, 2 importers. Same underscore-as-public-API nit as `breakdown.py` |
| 19 | `event_row_field.py` | keep. One `required_field` behind 3 `partial` binds, the house shape |
| 25 | `application_errors.py` | keep |
| 27 | `stat_conversion.py` | keep, one declaration, named in architecture.md |
| 28 | `ability_ranks.py` | keep, one validator, 1 importer, named in architecture.md |
| 30 | `vendor_path.py` | keep. The `sys.path` bootstrap must live in exactly one place |
| 33 | `fight/after/execute_display.py` | keep, one fight step |
| 34 | `fight/declarations.py` | keep |

The 40 to 70 line band holds 19 modules. All are single-idea fight steps or
leaves named in architecture.md. The single-importer pattern there covers
`fight/after/fight_notes.py`, `fight/ledger/execute_stamps.py`,
`fight/rotation/resource_admission.py` and `fight/items/ultimate_procs.py`,
each imported only by `damage.py`. That is architecture.md's declared "each
subpackage is one step" shape, and `damage.py` is already 545 lines and already
sits on the sightline #27 size arm, so folding them back would make it worse.
Keep all.

## F15: one-caller functions

426 top-level functions have exactly one `src/` call site and no self-call. The
overwhelming majority are registry rows: 36 `_compile_<rune>` in `rune_paths/`,
40 `_parse_<item>` in `passive_parser.py`, 14 `_<x>_owners` in
`ledger_adequacy.py`, 4 `_stage_<family>` in `program/compile.py`. In each the
single reference is a table entry keyed by a closed enum, which is a declared
house pattern with its reason written above the table. Keep all of them. The 11
worth inlining are the renames in F8.

34 Flask route handlers in `app.py` show zero calls because the decorator holds
the reference. Keep.

## F16: stubs

- 8 `...` bodies, all on `survival/transitions.py:106 SurvivalLedger`, a
  Protocol with three implementers: `ReceiptLedger`, `ScoreLedger` and
  `OutcomeLedger`. Keep.
- 5 raise-only bodies: `quantity._QuantityAlgebra.read` with 4 subclasses,
  `Withheld.read`, `Starved.read`, `OutcomeLedger.schedule_heal` and
  `crowd_control_eligibility.same_hit_ordering`. The last two are declared
  refusals that name the missing rule. Keep.
- 3 constant returns. `StructuralZero.read` returning `0.0` and
  `ScoreLedger.annotate` returning `None` are algebra members. Keep.
  `LivePredicate.requires_live_pool` is the one stub with no consumer, see F10.

11 Protocols are in scope. Ten have 1 to 25 external referencing modules.
`interpreters/damage_formula.py:233 FormulaPayload` has no external references
and two in its own file, so it is a Protocol used as a local type alias.
Inline the annotation or move it next to its user. About 8 lines.

## F17: kwarg plumbing

59 functions take 8 or more parameters. Every member of the tail states a
reason.

| Parameters | Function | Verdict |
|---|---|---|
| 29 | `survival/actions.py:109 compiled_damage_action` | keep. A documented hot-path bypass of `NamedTuple` keyword-default parsing, using `tuple.__new__` on a pre-filled row. The docstring names which 6 parameters deliberately have no default and why |
| 22 | `purchase_search.py:41 optimize_purchase` | keep, the public search entry point |
| 19 | `purchase_plans.py:39 PurchaseSearch.__init__` | keep, 15 internal readers. This is the params object |
| 18 | `fight/ledger/pool_walk.py:121 _simulate_ordered_damage` | keep |
| 16 | `participant_timeline.py:5088 _compose_pass` | keep, see the `compose` closure note in F8 |
| 14 | `champions/packet_module.py:217 build_packet_module` | keep, 76 champion modules call it |

No params object is rebuilt at each layer. `FightParams`, `FightState`,
`SlotCtx`, `BuildContext` and `PurchaseSearch` are each built once and threaded.

## F18: single-use abstractions judged keep

Five single-member enums exist, and each carries a paragraph defending the
choice.

| Path and line | Enum | Defence |
|---|---|---|
| `program/precision.py:343` | `CutoffPolicy` | names the rounded rather than raw death time, so a "more correct" refactor cannot silently move a published total |
| `item_behavior.py:528` | `HolderStat` | closed, so a magnitude names a stat that exists |
| `item_behavior.py:899` | `SecondaryDelivery` | each member carries tag, row words and targeting kind |
| `item_behavior.py:1403` | `CritOccurrence` | replaces an unnamed `i == 0` |
| `survival/typed_action.py:72` | `LiveProbe` | declared on the `survival/` side so `program/` may name it and never the reverse |

Keep all five. Each is a named decision with a stated alternative.

80 `MappingProxyType` freezes were reviewed. All are module-level declaration
tables or empty-mapping defaults, and the rune-compiler snapshots are
load-bearing per CLAUDE.md. Keep all.

22 module-level `partial` aliases were reviewed. Each binds a real constant,
such as an item name, an error type or a row kind, and most have 5 to 36 uses.
Keep all. Of 12 plain `X = Y` aliases, three are a second name for one fact:

- `item_behavior_catalog.py:1314 AMP_COMPILABILITY = COMPILED_KERNEL_CAN_AMP`,
  with 11 self uses and 5 test uses of the alias and none of the original
  outside its definition.
- `role_quests.py:54 TOP_LEVEL_CAP = TOP_QUEST_LEVEL_CAP`, with 2 self uses.
- `program/amp.py:135 ArmKey = tuple`, a type alias to the bare builtin that
  documents nothing a `tuple` annotation would not.

Delete the first two and use the one name. Give `ArmKey` members or delete it.

## Asides, outside this dimension

- `rune_parser.py` defines `_percent_ratio` twice with identical bodies, at
  lines 1088 and 1650 in this index. CLAUDE.md records the pair at 982 and
  1544, so the lines have moved but the duplicate is live. Both are dead: no
  call sites. This is the real `E0102` that CLAUDE.md says the pylint gate is
  widened around.
- `item_effects.input_option_stat_bonuses` returns a bare
  `tuple[float, float, float, float]` holding `bonus_ap`,
  `move_speed_percent`, `bonus_health` and `bonus_mana`. `stats.py:114` reads
  it positionally and `item_effects.py:6115` reads it as
  `input_bonus_ap, _, _, _`. A 4-field record is the tree's own style here, and
  the triple discard is the shape that silently swaps two floats on a future
  edit.
- Of the five view front doors, `score`, `survival` and `tdd` have no
  production caller. Production calls `score_leaves`, `survival_leaves` and
  `tdd_leaves` directly. All five are pinned by
  `tests/test_program_structure.py:275 FRONT_DOORS` as the view contract, so
  keep them. Worth knowing that three of the five exist for the contract test.
