# Item ↔ Fight Engine Boundary — Design and Implementation Plan

**Status:** implemented in full on 2026-07-15. The numbered sections below are
retained as the decision record and acceptance checklist.

**Goal:** make item knowledge compile into a small typed build projection so
`damage.py` owns fight sequencing without reading registry dictionaries or
dispatching on item names.

**Chosen architecture:** `item_effects.resolve_damage_effects(items)` compiles
the live registry into immutable, phase-aligned specs. Each spec closes over
validated item values and exposes a raw-damage formula. `damage.py` decides
when a spec applies, tracks target HP and stack cadence, mitigates the raw
damage, and records breakdown rows. One item may emit multiple specs (Titanic
Hydra and Muramana prove that a single `type` is not a sufficient model).

**Prior art:** the current generic on-hit/spellblade/burn/proc loops already
establish phase dispatch as the successful local pattern. Standard-library
frozen dataclasses are a good fit for read-only compiled values; Python's
`singledispatch` is not, because it dispatches on the first argument's Python
type while the source data is registry records, which would require artificial
wrapper classes solely to trigger dispatch.

## Alternatives considered

1. **More typed getters.** Lowest migration cost, but the public surface still
   grows once per item and the engine still needs item identity. Rejected.
2. **Universal trigger/event DSL.** Smallest apparent caller surface, but it
   moves fight scheduling, refresh windows, and cross-item ordering into item
   code. That is a combat-engine rewrite disguised as a boundary refactor.
   Rejected.
3. **Typed phase batches (chosen).** Slightly more carrier types, but every
   caller reads like the fight model and each side owns one kind of knowledge.

## Invariants

- `damage.py` contains no `ITEM_EFFECTS` access and no item-name dispatch.
- Every required value is read through one validator that raises a `KeyError`
  naming both item and key.
- `item_effects.py` owns item identity, value formulas, labels, damage types,
  and structural behavior flags.
- `damage.py` owns application timing, cast/auto order, stack cadence,
  decreasing target HP, mitigation, amplifiers, and breakdown accumulation.
- The web calculation remains stochastic; optimizer and golden calls remain
  deterministic.
- Existing public result/breakdown keys stay compatible.
- Pure migration stages produce zero golden diffs.
- Runtime refresh observes the new registry immediately; compiled projections
  are per-fight and are not cached.

## Offline and parser policy

The former `_DEFAULT_ITEM_EFFECTS` mixed three concerns. The implementation
split them deliberately:

- `_STATIC_ITEM_EFFECTS`: structural fields and values the parser cannot
  obtain (formula/model identifiers, damage types, cooldowns absent from JSON,
  flags, labels).
- `_OFFLINE_ITEM_EFFECTS`: a complete, last-known-good registry used only when
  cached data cannot be loaded or the whole parser fails.
- Successful online parsing builds `static | parsed` and never borrows a
  missing parseable value from the offline snapshot. Compiling a registered
  behavior with a missing key fails loudly.

A parity test compares every parseable key shared with the offline snapshot to
the checked-in cached data. Balance changes therefore force the offline
snapshot to be consciously refreshed instead of silently aging.

## File map

- `src/calculator/item_effects.py` — typed specs, formula builders, resolver,
  strict value validation, and offline/static registry policy.
- `src/calculator/damage.py` — phase loops over compiled specs; one mitigation
  helper; no registry or item-name knowledge.
- `tests/test_item_effects.py` — compilation, schema, formula, refresh, and
  offline/parser policy tests.
- `tests/test_damage.py` — mitigation and phase scheduling unit tests.
- `tests/test_item_damage.py` — item-level full-fight compatibility tests.
- `tests/test_architecture.py` — static boundary guard.
- `.agents/skills/add-item-effect/SKILL.md` and mirrored `.claude` copy — final
  operator workflow after the new boundary is live.

## Public and internal contracts

```python
DamageType = Literal["physical", "magic", "true"]

@dataclass(frozen=True, slots=True)
class DamageInputs:
    champion_stats: Mapping[str, float]
    level: int
    is_melee: bool
    target_max_health: float
    target_current_health: float

RawDamageFormula = Callable[[DamageInputs], float]

@dataclass(frozen=True, slots=True)
class DamageSource:
    item_name: str
    breakdown_key: str
    display_name: str
    damage_type: DamageType
    raw_damage: RawDamageFormula
    is_ability_damage: bool = False

@dataclass(frozen=True, slots=True)
class PerHitEffect:
    source: DamageSource
    tracks_current_health: bool = False

@dataclass(frozen=True, slots=True)
class SpellbladeEffect:
    source: DamageSource
    cooldown: float
    weave_delay: float
    double_on_hit: bool = False
    expose_weakness_melee: float = 0.0
    expose_weakness_ranged: float = 0.0

@dataclass(frozen=True, slots=True)
class BurnEffect:
    source: DamageSource
    duration: float

@dataclass(frozen=True, slots=True)
class FirstAutoEffect:
    source: DamageSource
    max_procs: int = 1

@dataclass(frozen=True, slots=True)
class StackingOnHitEffect:
    source: DamageSource
    hits_required: int
    tracks_target_health: bool = False

@dataclass(frozen=True, slots=True)
class BuildDamageEffects:
    per_hits: tuple[PerHitEffect, ...] = ()
    spellblade: SpellbladeEffect | None = None
    burns: tuple[BurnEffect, ...] = ()
    immolates: tuple[DamageSource, ...] = ()
    periodic: tuple[DamageSource, ...] = ()
    cooldown_procs: tuple[DamageSource, ...] = ()
    ultimate_procs: tuple[DamageSource, ...] = ()
    actives: tuple[DamageSource, ...] = ()
    first_autos: tuple[FirstAutoEffect, ...] = ()
    stacking_on_hits: tuple[StackingOnHitEffect, ...] = ()
    per_ability_hits: tuple[DamageSource, ...] = ()

def resolve_damage_effects(
    items: Sequence[Mapping[str, Any]],
) -> BuildDamageEffects:
    """Compile a build's registered item behaviors from the live registry."""
```

The implemented projection also carries typed fight modifiers: general,
magic-only, basic-attack, ability, and Hypershot amplifiers; stacking armor/MR
reduction; crit rules; penetration cadence; execute display; and ultimate-auto
rules. Unknown effect types and missing required fields fail with item context.
The former public per-item calculation helpers were removed, so tests and the
fight engine exercise the same compiled formulas.

Additional private spec fields may be added only when a generic engine phase
needs them. A field named for one item is a design failure.

## Execution plan

### 1. One mitigation path

**Acceptance**

- `_mitigate(raw, damage_type, resists, magic_amp)` covers physical, magic,
  and true damage.
- Every copied mitigation block uses it; golden output is identical.

**RED → GREEN**

- Add focused physical/magic/true/magic-amp tests in `test_damage.py`.
- Implement the helper and mechanically replace duplicate branches.

**Verify**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_damage.py -q
.\.venv\Scripts\python.exe scripts\golden_snapshot.py compare scripts\golden_baseline.json
```

### 2. Compile a build without changing callers

**Acceptance**

- Add the typed carriers and `resolve_damage_effects` beside the legacy API.
- Registered malformed effects fail with item+key.
- Resolver observes monkeypatched/refreshed registry values on the next call.
- Titanic emits per-hit and empowered-auto behavior; Muramana emits per-hit
  and per-ability behavior.

**RED → GREEN**

- Add resolver/schema/multi-behavior tests in `test_item_effects.py`.
- Implement one `_RequiredValues` reader and formula builders.

**Verify**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_item_effects.py -q
.\.venv\Scripts\python.exe scripts\golden_snapshot.py compare scripts\golden_baseline.json
```

### 3. Migrate the existing generic phase loops

Migrate, one vertical slice at a time: per-hit → spellblade → burn/immolate/
periodic → cooldown/ultimate proc → active. Resolve once in fight setup and
store `BuildDamageEffects` on `FightState`.

**Acceptance**

- These phases do not scan `ITEM_EFFECTS` or inspect effect dictionaries.
- Dusk and Dawn, Bloodsong, Malignance burn refresh, Stormsurge ability amp,
  and Titanic's existing active-toggle behavior remain exact.

**Verify after each slice**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_item_effects.py tests\test_item_damage.py tests\test_damage.py -q
.\.venv\Scripts\python.exe scripts\golden_snapshot.py compare scripts\golden_baseline.json
```

### 4. Replace the single-proc item ladder

Migrate first-auto, auto-cooldown, stacking-on-hit, max-HP proc, and
per-ability-hit behaviors as separate slices.

**Acceptance**

- `_add_single_proc_on_hits` contains only generic loops or is deleted.
- Statikk count caps at autos; Heartsteel remains one proc; Voltaic uses
  current HP; Kraken and Hullbreaker count phantom/double applications;
  Kraken tracks falling HP; Eclipse and Muramana retain current cadence.
- No item-name condition exists in `damage.py`.

**Verify after each slice:** same focused tests and golden command as Task 3.

### 5. Migrate engine modifiers and remaining raw reads

Compile typed modifier specs for phantom-hit cadence, crit rules, Navori,
Shadowflame, damage amps, shreds, execute display, and other remaining engine
queries. Return a typed MR-reduction value instead of a raw dict.

**Acceptance**

- `rg "ITEM_EFFECTS" src/calculator/damage.py` has no matches.
- `damage.py` has no item-name comparisons/membership tests.
- Obsolete narrow getters are removed only after their last caller is gone.
- Golden output remains identical.

### 6. Enforce parser/offline provenance

**Acceptance**

- Split static fields from the complete offline snapshot.
- Successful parsing never fills a missing parseable key from offline data.
- Whole-load/whole-parser failure uses the complete snapshot.
- Cached parseable values and offline snapshot agree in tests.
- Current known drift is corrected: Lich Bane AP ratio `0.45`; Staff of
  Flowing Water Rapids AP `40.0`.

**Verify**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_item_effects.py tests\test_wiki_parser.py -q
.\.venv\Scripts\python.exe scripts\golden_snapshot.py compare scripts\golden_baseline.json
```

### 7. Lock the boundary and update operator docs

**Acceptance**

- `tests/test_architecture.py` guards against raw registry reads and item-name
  dispatch in `damage.py`.
- Both add-item-effect skill copies describe parser → structural/offline data
  → compiled behavior → phase handler, and are byte-identical.
- Full repository verification is green.

**Final verify**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\golden_snapshot.py compare scripts\golden_baseline.json
.\.venv\Scripts\python.exe -m pylint src\ --fail-under=9
git diff --check
```
