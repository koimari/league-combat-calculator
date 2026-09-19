# Slop audit: code quality patterns in `src/` (excluding `champions/`)

Scope: 312 files, 121,427 lines. `src/*.py`, `src/calculator/*.py`, `fight/`,
`program/`, `survival/`, `interpreters/`, `rune_paths/`.
Method: AST scans under `.audit/` (`scan.py`, `ladders.py`, `bools.py`, `prose.py`,
`wrappers.py`, `consts2.py`, `unpack.py`, `rethrow.py`), one runtime probe
(`hops.py`, `chain.py`, `actionprobe.py`) on a real `calculate_payload`.

## Verdict in one line

The beginner tells are absent. The cost is concentrated in one contradiction:
**the declaration layer is over-typed (415 frozen records, 69 enums, 59 exception
classes) while the engine's own payload is `dict[str, Any]` re-defaulted and
re-shape-checked at every hop (1,616 literal-default sites, 1,656 `Mapping[str, Any]`
annotations, 570 runtime `isinstance` checks).** Every other finding is downstream of
that.

## Pattern table, ranked by instances x cost to a reader

| # | Pattern | Count | Cost to a reader | Proposal |
|---|---|---|---|---|
| 1 | Untyped engine rows: `.get(key, literal)` on a fight/event/breakdown dict | 1,616 sites in scope (repo lint: `scripts/literal_defaults.py`); 51 modules spell `"total_damage"` | Every reader re-invents the schema; a missing key silently prices 0.0 (the repo has already been bitten: 172 golden raw leaves were literal zeros) | Finish the row-reader leaves that already exist (`damage_event_row.py`, `cast_event_row.py`, `heal_event_row.py`). 6 modules use them, ~90 do not |
| 2 | `SurvivalAction`: one 96-field NamedTuple for every action kind | 96 fields; a real request sets a median of 19, and 66 fields are never set at all | Forces a 29-param constructor, 29 `_I_*` index constants, a default-row copy shim, and a 4,367-line dispatch in `survival/transitions.py` | Split per `ActionKind` group (damage / heal / shield / buff / utility); keep the flat row only if a pinned bench in `benchmarks.md` says the union is faster |
| 3 | Long functions | 151 over 80 lines; top is 1,256 lines | Nothing fits on a screen; 817 of `derive_item_support_effects`'s 1,256 lines are 16 independent `if <producer> is not None:` blocks | Dispatch table keyed by `AllyProducer`, the same shape `item_behavior_catalog._FAMILY_COMPILERS` already uses |
| 4 | Exception hierarchy nobody catches | 59 custom classes; **55 are never caught anywhere in `src/`**; 16 are one-per-interpreter `...InterpretationError(ValueError)` | A reader must learn 59 names to discover they all behave as `ValueError` and exist to make `pytest.raises` specific | Keep ~6 that are caught; delete the rest and raise `ValueError` with the same message |
| 5 | Belt-and-braces re-validation | `typed_payload` re-checks payload/family on every interpreter call; `validate_rule` already enforces `PAYLOAD_FAMILY[type(payload)] is rule.family` at declaration time | Two homes for one invariant, plus 16 exception classes that exist only for the second one | Delete `typed_payload`'s isinstance; the registry key is the proof |
| 6 | History narrated in runtime source | 61 `Phase N` / `Phase N SN`, 65 `campaign`, across 31 and ~30 files | Directly against the house rule ("current state only, never history"); a reader cannot tell a live rule from a migration note | Delete. It is a mechanical pass |
| 7 | Record explosion vs anonymous tuples | 415 records (376 dataclasses, 356 frozen; 39 NamedTuples), 69 enums, 27 one-field records, **and 49 functions returning an anonymous 3-to-9-member tuple** | The discipline is inverted: a single string gets a frozen record, a 9-value engine return gets a bare tuple | Records where the tuple is (`_evaluate_cast_parts`, `_grey_health_receipts`, `_simulate_ordered_damage`); enum members where the fieldless record is (`program/route.py`: 6 of 10 policies carry no data) |
| 8 | Parameter explosion and boolean switches | 48 functions with >=8 params (max 29); 186 `bool` params across 146 functions | `optimize_purchase` has 22 params, 8 optional, 5 boolean; `add_engine_result` has 15 and a `view: X \| None` that is read as `staging = view is None` | Group into the request records the tree already has; make `view` two call sites, not a flag |
| 9 | String-typed dispatch beside a real enum | `DamageClass` enum used 28 times; bare `"physical"` literal used 94 times in ~40 modules. `aggregate_public_results` is an 8-arm string-policy ladder with per-key special cases inside two arms | Two vocabularies for one fact; the ladder is depth 10 in 47 lines | `_PUBLIC_FIELD_POLICIES` maps key to a callable, not to a string |
| 10 | Pure forwarding wrappers | 75 functions whose body is `return other(<same args>)` | Four of them (`_compile_opening_defense`, `_compile_threshold_defense`, `_compile_combat_state`, `_compile_reactive`) are byte-identical apart from the docstring | Point all four `RuleFamily` keys at `_compile_defense` |
| 11 | Single-reader module constants | 471 of 1,163 (40%) have exactly one use in `src/`; 3 have none | Concentrated: `rune_parser.py` 126, `item_behavior_catalog.py` 65 | Mostly fine (named regexes). Retire the 3 dead ones: `cleanse_eligibility.TOOLTIP_ONLY_CONTROL_KINDS`, `ledger_inputs.SHARED_ROW_FIELDS`, `minion_stats.MINION_TEAMS` |
| 12 | Manual loops that are a comprehension | 25 `for: append`, 10 `for: +=` | Small, but each hides the shape of the result | Comprehension / `sum` |
| 13 | Deep nesting | 32 functions deeper than 4; max depth 11 (`cast_edge_inference.detect_setup_consume_edges`, 462 lines) | The depth-11 function is unreviewable | Extract the inner loops |
| 14 | `pylint: disable` markers | 94, led by `too-many-arguments` (21), `too-many-instance-attributes` (15), `too-few-public-methods` (10), `too-many-locals` (9) | 60 of the 94 suppress size warnings that findings 2, 3 and 8 are the cause of | Fix the size, retire the marker |

## What is clean (measured, not assumed)

These were scanned for and are essentially absent. They should not be re-audited.

| Check | Count in scope |
|---|---|
| `x == True` / `== False` | 0 |
| `len(x) == 0` | 2 (`data_fetcher.py:48`, `timed_stacks.py:186`) |
| `.keys()` in a membership test or `for` | 0 |
| Mutable default arguments | 0 |
| Bare `except:` | 0 |
| Broad `except Exception` | 11, all in I/O shells (`data_updater`, `rune_pull`, `db`, `metrics`, `app`) |
| `typing.cast(...)` | 2, and both are a regex `cast` variable, not `typing.cast` |
| `if TYPE_CHECKING:` blocks | 1 |
| `Generic[...]` | 0 (9 PEP 695 generics, 3 `TypeVar`s) |
| Docstrings longer than their function body | 0 (`scripts/prose_lint.py` holds this) |
| `type: ignore` | 8 |
| `noqa` | 9, each with a stated reason |
| `sightline-ok` | 8, each with a stated reason |
| Shadowed builtins | 1 (`data_updater.py:31 dir=`, a vendor signature, `noqa`d) |
| `global` | 8, all memo/singleton init |
| Module-level side effects at import | 12, and 8 are the declared `_validate_*()` load gates |
| `f"..." + "..."` concatenation | 22, all `", ".join(...)` splices |
| Self-admitted unreachable checks (`pragma: no cover - defensive`) | 2 |

Type-gymnastics is **not** a finding here. Protocols: 11, and only
`survival/transitions.SurvivalLedger` has more than zero methods (8), with three
implementers (`receipt_ledger`, `score_state`, `outcome_state`). That one earns its keep.

## Indirection budget on the request path

Runtime probe (`.audit/hops.py`), one `calculate_payload` for Ahri level 11,
2 items + boots, one enemy, `time_based`, 10 s:

- **211 distinct `src/` modules entered**, **21,374 intra-`src` calls**.
- The **call stack** is shallow: 5 module hops from `calculate_payload` down to
  `_evaluate_cast_parts` (`calculate -> pipeline -> damage -> fight/rotation/ability_rotation
  -> fight/rotation/cast_parts`), 5 up to the published breakdown leaf. No pass-through
  hop in the stack.
- The **data** path is the expensive one. Three publication leaves take **11,071 of the
  21,374 calls (52%)**: `program/views/leaf.py` 8,199, `quantity.py` 1,974,
  `program/precision.py` 898. Every published number is wrapped into a `Quantity`, a
  `LeafOut`, and a dispositions entry.
- That is **not** dead receipt machinery: `static/js/app.js` reads `combat.dispositions`
  in 12 places to render withheld markers. It is the correct call, priced at 52% of the
  request's call volume. If latency matters, the win is in the per-leaf allocation
  (one dict + one NamedTuple per number), not in deleting the feature.
- The hops that add no transformation are in the *dict*, not the stack: the fight
  `result` is a `dict[str, Any]` progressively mutated by `pipeline.run_fight`'s
  `_attach_engine_receipts` / `_attach_display_splits` and by seven `fight/after/*`
  modules that read and rewrite `row["total_damage"]` in place. 51 modules address that
  one field by string literal.

## Receipts-on-receipts

41 records have **no reader outside their own module and are referenced only by a test**.
The heaviest: `coverage_evidence.EffectTag` (14 test refs), `trigger_stream.RiderDelivery`
(9), `shield_pools.ThresholdShield` / `ThresholdHealth` (8 each),
`cleanse_eligibility.CleanseDecision` (7), `interpreters.UnservedLane` (5),
`program/scope.MultiTarget` (5), `program/identity.DerivedOrigin` (5).

A further 62 records have no external reader and no test reference at all
(`coverage_evidence.ClaimGuard`, `EvidencePolicy`, `delivery_classes.DeliveryDeclaration`,
`fight/ledger/trace.FightTrace`, `interpreters.ReachabilityReport`, ...). Most are
module-internal helpers and are fine; the 41 above are the ones whose only consumer is a
shape assertion.

---

# Top 5, with before/after

## 1. Untyped engine rows (1,616 literal-default sites)

`scripts/literal_defaults.py` reports 1,947 sites tree-wide, 1,616 in this scope.
`tests/test_literal_defaults.py` is **2,442 lines** whose entire job is to freeze 632 of
them in named buckets (`ROW_READS` 96, `CACHED_SOURCE_ROW` 212, `AUTHORED_DECLARATION`
156, `ENGINE_ROW` 83, ...) plus an 89-entry `ER5_TAIL`. The debt is ratcheted, not paid.
Its own comment names the fix: "one row dataclass retires the whole list at once".

Concentration: `participant_timeline.py` 339, `program/compile.py` 100,
`survival/transitions.py` 74, `item_effects.py` 52, `public_response.py` 50.

Before (`participant_timeline.py:1063-1067`, and ~40 near-identical readers):

```python
return (
    float(event.get("time", 0.0) or 0.0),
    int(event.get("sequence", 0) or 0),
    str(event.get("_event_id", "")),
)
```

Three defenses on one field: a literal default, an `or` default, and a coercion, on a
row whose producer stamps all three keys.

After, using the leaf that already exists (`event_row_field.required_field`, read through
`damage_event_row` / `cast_event_row`):

```python
return (event_time(event), event_sequence(event), event_id(event))
```

`damage_event_row.py` has 6 readers today. **146 modules in scope still hand-default** at least one cached or engine row (`scripts/literal_defaults.py`).
This is one mechanical campaign, and it is the highest-value change in the tree.

Aside: `fight/after/amplifiers.py:279` defaults `total_damage` to int `0` where the other
28 sites use `0.0`. Harmless today (it is multiplied straight into a float), but it is
exactly the published-zero-type trap `CLAUDE.md` records.

## 2. `SurvivalAction`: a 96-field union

`src/calculator/survival/typed_action.py`. Runtime probe (`.audit/actionprobe.py`) on the
same request: 40 actions, **median 19 of 96 fields non-default, 66 fields never set at
all**. Fields range from `sort_key` to `ward_uses`, `gold_amount`, `on_block_heal_delay`.

The width has already cost three layers of workaround, all in
`src/calculator/survival/actions.py`:

```python
# The optimizer compiles tens of thousands of damage actions per request;
# the generated NamedTuple ``__new__`` costs ~1.5 us parsing 60+ keyword
# defaults per call.
_ACTION_DEFAULT_ROW = list(SurvivalAction())
_INDEX = SurvivalAction._fields.index
_I_SORT_KEY = _INDEX("sort_key")
...                                    # 29 index constants

def compiled_damage_action(sort_key, time, kind, subject, *, attacker, aidx,
    amount, damage_type, raw_formula, raw_damage, grievous, wound, source_key,
    source, event_slot, sequence, live_amp, declared, is_ability, basic_attack,
    baseline_effective_armor, baseline_effective_mr, immobilized=False,
    cc_kind="", cc_duration=0.0, skillshot=False, damage_over_time=False,
    area_damage=False, ability_instance=None) -> SurvivalAction:   # 29 params
```

The 1.5 us claim carries **no pinned benchmark**: `benchmarks.md` has no row for
`SurvivalAction` or `compiled_damage_action`. Under the house evidence standard that
claim is unsupported.

After: a `DamageAction` of ~22 fields, a `HealAction`, a `ShieldAction`, a `BuffAction`
and a `UtilityAction`, dispatched on `ActionKind` (which already exists, 21 members).
The `_I_*` shim, the default-row copy and the 29-param constructor all disappear, and
`survival/transitions.py` stops carrying 74 fields it cannot use for the action in hand.
Gate it with a bench row, not a comment.

## 3. `derive_item_support_effects`: 1,256 lines

`src/calculator/item_support_effects.py:213`. 61 top-level statements: 37 assignments
resolving producers, then 16 independent `if <producer> is not None:` blocks totalling
**817 lines**, each appending to one `packets` list. The largest single block
(`everlasting`) is 254 lines.

Before:

```python
starlit_grace = _producer(slots, AllyProducer.STARLIT_GRACE)
soul_siphon   = _producer(slots, AllyProducer.SOUL_SIPHON)
...                                              # 12 more
if reap is not None:              #  27 lines
if rage is not None:              #  30 lines
if "Umbral Glaive" in names:      #  40 lines   <- still a name, not a producer
if everlasting is not None:       # 254 lines
...
```

After, the shape `item_behavior_catalog._FAMILY_COMPILERS` already uses one file over:

```python
_PRODUCERS: dict[AllyProducer, Callable[[SupportCtx], list[dict[str, Any]]]] = {
    AllyProducer.REAP: _reap_packets,
    AllyProducer.EVERLASTING: _everlasting_packets,
    ...
}

def derive_item_support_effects(attacker, result, all_actors, trigger_effects=()):
    ctx = _context(attacker, result, all_actors, trigger_effects)
    return [p for producer, build in _PRODUCERS.items()
            if ctx.declares(producer) for p in build(ctx)]
```

`CLAUDE.md` already records that this module sits at sightline #27's fan-out ceiling and
that "no honest move set reaches nine imports without splitting
`derive_item_support_effects`". The split is the named fix and has not been taken.
The `"Umbral Glaive" in names` branch is a producer that never got a declaration.

Runners-up worth the same treatment: `participant_timeline._compose_pass` (864 lines,
16 params, 3 booleans), `fight/rotation/ability_rotation._compute_ability_rotation` (784),
`fight/autos/on_hit_layering._layer_on_hit_effects` (686),
`item_effects.item_state_receipts` (682), `program/compile.add_engine_result` (616 lines,
15 params, 48-line docstring).

## 4. 59 exception classes, 55 never caught

Every one subclasses `ValueError`, `RuntimeError`, `KeyError` or `TypeError`. Only six are
ever named in an `except` in `src/`: `ApplicationError`, `CacheUnavailable`,
`PatchIdentityError`, `StarvedSignal`, `UncompilableActionError`, `ValueRefError`.
`ProjectionRegistryError` is raised 6 times and referenced by nothing at all, test
included.

Sixteen are one-per-interpreter and differ only in their name:

```python
# interpreters/active_cast.py:56, spellblade.py:53, cast_proc.py:71,
# charged_strike.py:64, crit_profile.py:78, damage_routing.py:81, ... (16 files)
class ActiveCastInterpretationError(ValueError):
    """A rule reached this interpreter that is not an item active."""

_payload = partial(typed_payload, payload_type=ActiveCastRule,
                   stop=ActiveCastInterpretationError, noun="an active rule")
```

`ActiveCastInterpretationError` and `SpellbladeInterpretationError` are raised **zero**
times even through `typed_payload`; their only appearance is in `__all__` and one test.

After: one `InterpretationError(ValueError)` in `interpreters/__init__.py`, message names
the family. 15 classes and 15 `__all__` entries go.

`raise ... from` used purely to rename: `champion_loadout.py:474` and `:482` and
`scenario.py:184` all convert a `KeyError` into a `LookupError`, which is its supertype;
`interpreters/part_amp.py:178`, `stat_derivation.py:196`, `sustain.py:252` and
`item_behavior.py:3895` rename a `ValueRefError` into a per-interpreter class nobody
catches. The other 45 `raise ... from` sites add a field name to a `float()` failure and
are correct.

## 5. Re-validating what the registry already proved

`item_behavior.validate_rule` enforces, at declaration time, that a rule's payload type
maps to its declared family:

```python
declared = PAYLOAD_FAMILY.get(type(rule.payload))
if declared is not rule.family:
    raise BehaviorRuleError(
        f"{rule.mechanic_id}: payload {type(rule.payload).__name__} belongs to "
        f"{declared.value}, not {rule.family.value}")
```

Then every interpreter, reached only through a `RuleFamily`-keyed registry, checks it
again per call:

```python
def typed_payload[T](rule, payload_type: type[T], stop: type[Exception], noun: str) -> T:
    payload = rule.payload
    if not isinstance(payload, payload_type):
        raise stop(f"{rule.mechanic_id} is not {noun}")
    return payload
```

Twelve call sites, 16 exception classes, one already-proved invariant, on the hot path.
Delete the isinstance and return `rule.payload`; the family key is the proof.

The same module carries the tree's only real dispatch ladder:
`item_behavior._validate_payload` (line 2833) is **22 sequential `if isinstance(payload,
XRule): ...; return` arms**. A `dict[type, Callable[[BehaviorRule], None]]` beside
`PAYLOAD_FAMILY`, which is already keyed by exactly those types, collapses it and makes a
new payload type fail closed by omission rather than by falling off the end.

---

# Per-pattern detail

## 6. History narrated in runtime source (126 sites)

61 `Phase N` / `Phase N SN` references across 31 files, 65 `campaign` across ~30.
`trigger_stream.py` alone has 14 and 4. Representative:

```
trigger_stream.py:523   # Thirteen fields: Phase 2's eleven plus the two Phase 4 writes here.
trigger_stream.py:1465  # Hypershot is Phase 4 S7's canary: the first of the seven authority moves
survival/classify.py:220 # Until Phase 4 S6 it was spelled ``ordering_slot(phase) is DEBUFF_ARM``:
item_coverage.py:2408   # this campaign closes, and "no such lane, ever" is the version of that rule a
program/views/breakdown.py:3  Two composition tails built this list, side by side ... That is the
                              arrangement the Imperial Mandate incident came out of
```

Note the collision: `phase` is also a live domain word (the survival walk's transition
phases, `survival/phases.py`). A reader cannot grep one without the other. Deleting the
work-phase references is the only way to make `phase` mean one thing.

Prose volume overall: **18,539 docstring lines + 9,697 comment lines = 23.3% of the
scope.** No docstring exceeds its body (`prose_lint.py` holds that line). The heaviest are
`survival/pricing.py` at 52.4% prose, `support_scan.py` 43.3%, `trigger_stream.py` 33.8%,
`item_behavior.py` 33.3%, `program/compile.py` 29.7%. Much of that prose exists to
explain a shape that should not need explaining: see #7.

## 7. Records vs anonymous tuples, and the worst single file

415 records (376 dataclasses of which 356 frozen, 39 NamedTuples), 69 enums.
`item_behavior.py` holds 95 records and 39 enums in 4,110 lines, including
`DefenseField` (55 members), `UtilityDimension` (29), `AllyProducer` (27),
`DefenseMechanic` (25), `RuleFamily` (18).

Against that, **49 functions return an anonymous tuple of 3 to 9 members**:

```
participant_timeline.py:2742 _grey_health_receipts -> tuple[list[tuple[float, str, float]],
                                list[tuple[float, str, float, float]], dict[str, float | str]]
fight/ledger/pool_walk.py:121 _simulate_ordered_damage -> tuple[float, dict[str, float],
                                list[dict[str, Any]], dict[str, Any]]
fight/rotation/cast_parts.py:21 _evaluate_cast_parts -> tuple[float, float, dict[str, float],
                                list[dict[str, Any]]]
fight/autos/swing_schedule.py:349 _lethal_tempo_attack_schedule -> tuple[list[float],
                                list[int], list[int], list[float]]
```

`survival/pricing.py` (471 lines, 52% prose) is where the inversion is sharpest. Two
records in one file carry the same six ideas, one typed and one deliberately detyped:

```python
class AuthoredDeclaration(NamedTuple):
    rule_id: str
    raw_amount: float
    attack_class: str
    effective_resistance: float | None = None
    swing: tuple | None = None            # really a BasicAttackSwing
    routing: tuple | None = None          # really a RoutingProvenance

    def swing_composition(self):  return None if self.swing is None else BasicAttackSwing(*self.swing)
    def delivered_as_a_swing(self, swing):  return self._replace(swing=tuple(swing))
    def routed_by(self, routing):  return self._replace(routing=tuple(routing))
    def repriced_at(self, r):  return self._replace(effective_resistance=float(r))
    def rescaled_by(self, f):  return self._replace(raw_amount=float(self.raw_amount) * float(f))

class DeclaredPacket(NamedTuple):         # 80 lines later, same ideas, typed
    swing: BasicAttackSwing | None = None
    routing: RoutingProvenance | None = None
```

The docstring's reason ("a plain tuple on the wire") does not hold: a `NamedTuple` **is**
a tuple, so nesting the typed one costs nothing on any wire, and no reader ever indexes
`swing` positionally. The pack (`tuple(swing)`) and unpack (`BasicAttackSwing(*self.swing)`)
run per packet on the walk's hot path and cancel out.

After: `swing: BasicAttackSwing | None`, `routing: RoutingProvenance | None`.
`swing_composition`, `routing_provenance`, and the two `tuple(...)` conversions delete,
and roughly 40 lines of docstring explaining the round-trip go with them.

Also in this family: `program/route.py` declares 10 routing policies as frozen dataclasses
for a `match`/`case`, and **6 of the 10 carry no fields at all** (`SelfOnly`, `Holder`,
`PairDefender`, `AllOpponents`, `AllTeammates`, `SelfAndAllTeammates`, `TriggerTarget`).
An enum member plus two payload cases says the same thing in a third of the names.

## 8. Parameter explosion and boolean switches

48 functions take >=8 parameters; 146 functions take 186 `bool` parameters.

| params | site | booleans |
|---|---|---|
| 29 | `survival/actions.py:109 compiled_damage_action` | 6 |
| 22 | `purchase_search.py:41 optimize_purchase` | 5 (+8 optional) |
| 19 | `purchase_plans.py:39 __init__` | 3 |
| 18 | `fight/ledger/pool_walk.py:121 _simulate_ordered_damage` | 0 |
| 16 | `participant_timeline.py:5088 _compose_pass` | 3 |
| 16 | `optimizer.py:50 optimize_build` | 3 (+8 optional) |
| 15 | `program/compile.py:811 add_engine_result` | 1, plus a disguised one |
| 15 | `fight/rotation/cast_parts.py:21 _evaluate_cast_parts` | 3 (+7 optional) |

The disguised one is worth naming. `add_engine_result` takes `view: PairView | None = None`
and immediately does `staging = view is None`, then branches on `staging` for the rest of
616 lines. That is a mode flag wearing an Optional's clothes: two call sites, two
functions, a shared core.

`optimize_purchase` also validates four string-typed enums against literal tuples in its
first eight lines (`objective`, `combine_policy`, plus two range checks), while the tree
has 69 real enums elsewhere.

## 9. String dispatch where a table belongs

`public_response.aggregate_public_results` (`public_response.py:400`), 47 lines, **nesting
depth 10**, eight `elif policy ==` arms with per-key special cases inside two of them:

```python
for key, policy in _PUBLIC_FIELD_POLICIES.items():
    if policy == "primary":      ...
    elif policy == "any":        ...
    elif policy == "concat":
        if key == "damage_events":  aggregated[key] = _concat_damage_events(results)
        else:                       aggregated[key] = [e for r in results for e in r.get(key, [])]
    elif policy == "sum_by_key":  ...
    elif policy == "sum":
        if key == "target_effective_health":  value = sum(_target_effective_health(r) for r in results)
        elif key == "overkill":               value = sum(_legacy_overkill(r) for r in results)
        else:                                 value = sum(float(r.get(key, 0.0)) for r in results)
    ...
    else: raise AssertionError(f"unknown combine policy {policy!r} for {key}")
```

After: `_PUBLIC_FIELD_POLICIES: dict[str, Callable[[list[dict]], object]]`. The two
special-cased keys become their own entries, the `AssertionError` arm becomes impossible
by construction, and the depth drops from 10 to 2.

Same family, tree-wide: `DamageClass` (`ability_spec.py:32`) is used 28 times; the bare
literal `"physical"` appears 94 times across ~40 modules, `{"physical", "magic", "true"}`
set literals recur in `fight/ledger/event_rows.py`, `public_response.py` and others.
One enum, two vocabularies.

## 10. Pure forwarding wrappers (75)

The four that are indefensible, `item_behavior_catalog.py:5215-5247`:

```python
def _compile_opening_defense(family, source, entry):
    """Defences already in force when the modeled exchange opens."""
    return _compile_defense(family, source, entry)

def _compile_threshold_defense(family, source, entry):   # identical body
def _compile_combat_state(family, source, entry):        # identical body
def _compile_reactive(family, source, entry):            # identical body
```

Their only use is four adjacent rows of `_FAMILY_COMPILERS` (lines 5949-5952). 34 lines,
zero behaviour. Point all four keys at `_compile_defense`; the docstrings move onto the
`RuleFamily` members, where the distinction actually lives.

The other 71 are mostly named specializations (`calculation_coefficient` /
`calculation_constant` over `_calculation_scalar`, `_lifesteal_owners` /
`_omnivamp_owners` over `_vamp_stat_owners`). Those read fine; several would read better
as `partial(...)`, which `CLAUDE.md` already records as the house move for the shape.

## 11. Deep nesting (32 functions over depth 4)

| depth | lines | site |
|---|---|---|
| 11 | 462 | `cast_edge_inference.py:45 detect_setup_consume_edges` |
| 10 | 47 | `public_response.py:400 aggregate_public_results` |
| 8 | 347 | `fight/rotation/precomputed_procs.py:41 _add_precomputed_proc_damage` |
| 8 | 79 | `item_coverage.py:1028 item_model_coverage` |
| 7 | 864 | `participant_timeline.py:5088 _compose_pass` |
| 7 | 617 | `participant_timeline.py:3185 _simulate_survival` |
| 7 | 547 | `survival/transitions.py:3730 run_survival_walk` |
| 7 | 517 | `participant_timeline.py:1510 _support_effect_templates` |

Depth 11 in 462 lines is the one that has to move. `CLAUDE.md` already baselines
`cast_edge_inference` under sightline #27's size arm as "one function over one champion's
rows through six shared closures", which is a description of the problem rather than a
reason it is fine.

## 12. Manual loops (35)

25 `for x in xs: out.append(...)` and 10 `for x in xs: total += ...`. All are one-line
comprehension or `sum()` rewrites. Concentrations: `survival/accumulate.py` (3 adjacent
appends over three parallel entry lists, lines 33-37), `fight/rotation/mana_walk.py` (3),
`participant_timeline.py` (5). Small individually; worth a single codemod pass.

## 13. Nested functions (101)

Most are legitimate closures that capture level and options and are returned as an effect
formula: `rune_paths/` accounts for 22 and `rune_effects.py` 7, and those are the
compiler pattern the architecture calls for. The ones that are module-level helpers in
disguise, taking only arguments already in scope as parameters:
`interpreters/damage_routing.py:96` and `:141` (`field -> KernelField`, twice in one
file), `interpreters/amp_magnitude.py:198` (the same `field` a third time),
`interpreters/crit_profile.py:189`, `damage_routing.py:189` (`_field -> compiled_value`,
twice). Five copies of one two-line wrapper across four interpreter modules.

## 14. Marker census

94 `pylint: disable`, led by `too-many-arguments` 21, `too-many-instance-attributes` 15,
`too-few-public-methods` 10, `too-many-locals` 9, `too-many-branches` 7,
`too-many-positional-arguments` 7, `too-many-return-statements` 6, `too-many-statements` 6,
`too-many-lines` 5. **Roughly 60 of the 94 are size suppressions**, and every one of them
sits on a function or class named in findings 2, 3 or 8. They are hiding a real smell, and
they will retire themselves when those three land.

The remainder are honest: 4 `global-statement` on memo init, 7 `unused-argument` on
protocol-shaped methods, 2 `import-outside-toplevel` closing import cycles, 1
`protected-access` paired with its `noqa`.

9 `noqa` and 8 `sightline-ok`, each with a one-line reason. Both sets are fine.

CI's pylint gate is a score (`--fail-under=9`) plus `--fail-on=E0601,E0602`; the tree has
one real `E0102` outside this scope (`rune_parser._percent_ratio` defined at 982 and again
at 1544 with identical bodies), already recorded in `CLAUDE.md`.

## 15. Validation-dominated modules

1,126 `raise` sites in scope, 27% inside a function named `validate*` / `check*` /
`require*`. Density per 100 lines, modules over 100 lines:

| raises / 100 loc | module | judgement |
|---|---|---|
| 14.7 | `request_parsing.py` (24 / 163) | Correct. This is the public boundary |
| 10.3 | `binary_roots.py` (36 / 350) | Overbuilt. See below |
| 9.3 | `champion_loadout.py` (45 / 482) | Correct. Request validation |
| 8.4 | `stack_rules.py` (13 / 155) | Declaration load gate, correct |
| 7.3 | `validation_receipts.py` (14 / 193) | Correct |
| 4.7 | `value_ref.py` (23 / 487) | Correct, this is the fail-loud accessor layer |

`binary_roots.py` is the one that reads like hand-written Java. It navigates Community
Dragon JSON with a defensive `isinstance` on every hop (29 in 350 lines) instead of one
helper:

```python
spell = spell_obj.get("mSpell") if isinstance(spell_obj, dict) else None
calcs = spell.get("mSpellCalculations") if isinstance(spell, dict) else None
node = calcs.get(calculation_name) if isinstance(calcs, dict) else None
parts = node.get("mFormulaParts") if isinstance(node, dict) else None
if not isinstance(parts, list):
    raise RuntimeError(f"calculation {calculation_name!r} not found or has no formula parts")
```

After: `parts = dig(spell_obj, "mSpell", "mSpellCalculations", calculation_name,
"mFormulaParts", want=list)`, one 8-line helper, and ~15 raise sites collapse into it
with the path in the message. The module also carries two checks that cannot fire:
`float(f"{number:.6g}")` of a finite float is finite, and both sites re-check it under
`# pragma: no cover - defensive` (lines 97 and 332).

## Asides found on the way (off-dimension)

1. **`participant_timeline.py:864-871` declares a generic it does not use.**
   `_KeystoneEffect = TypeVar("_KeystoneEffect")` sits immediately above
   `def _keystone_holder[KeystoneEffect](...)`, whose body and signature reference only
   the module-level `_KeystoneEffect`. The PEP 695 parameter `KeystoneEffect` is dead and
   the function is not generic in its own scope. Pick one mechanism.
2. **`fight/after/amplifiers.py:279** uses int `0` where the other 28 `total_damage`
   defaults use `0.0`. No live effect, but it is the published-zero-type shape.
3. **`champion_loadout.py:474`, `:482`, `scenario.py:184`** raise `LookupError` from a
   caught `KeyError`, which is a `LookupError` already. The `from exc` chain preserves it,
   so nothing is lost, but the conversion narrows nothing.
4. **Three module constants have no reader in `src/` at all**:
   `cleanse_eligibility.TOOLTIP_ONLY_CONTROL_KINDS`, `ledger_inputs.SHARED_ROW_FIELDS`,
   `minion_stats.MINION_TEAMS`. Each is referenced only from `tests/` or `scripts/`.
   Under the house rule that everything pulls its weight, either give them a reader or
   move them to the test that wants them.

## Suggested order of work

1. Row readers over `.get(key, literal)` (finding 1). Mechanical, highest value, and the
   leaves already exist. Golden compare must show zero diffs.
2. Split `derive_item_support_effects` (finding 3) and `_compose_pass`. Both are
   `scripts/extract_modules.py` assignment files, not hand moves.
3. Delete the 53 uncaught exception classes and `typed_payload`'s isinstance (findings 4
   and 5). Tests change from a specific class to `ValueError` plus a message match.
4. History prose sweep (finding 6). One pass, no behaviour.
5. `SurvivalAction` split (finding 2). Largest and riskiest; do it last, and land a
   `benchmarks.md` row first so the 1.5 us claim is measured rather than asserted.
