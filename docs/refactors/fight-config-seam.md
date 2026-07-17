# FightConfig — collapsing the 15-parameter fight bundle

**Status: DESIGN — approved shape, not yet implemented.**

## Problem

The fight engine's configuration is a 15-parameter bundle spelled out in
full at four places, plus a 16th pseudo-parameter and a big test surface:

| spelling | where |
|---|---|
| `calculate_fight_damage(...)` signature | `damage.py:2191` (13 config params + 2 data args) |
| `_resolve_combat_state(...)` signature | `damage.py:669` (identical list) |
| `run_fight` hand-mapping `FightParams` → kwargs | `pipeline.py:136` |
| `conftest.fight` parallel defaults dict | `tests/conftest.py:189` |
| 123 direct test call sites | `test_item_damage.py` (92), `test_damage.py` (7), champion tests |

Costs paid today: adding one fight input (say, target healing reduction)
touches five places; the production assembler and the test assembler
drift independently; and `ability_haste` is passed as a parameter that
`run_fight` derives FROM `champion_stats` — while its sibling
`basic_ability_haste` is read from `champion_stats` inside the engine.
Same fact, two transport mechanisms.

## Design

### The shape: one frozen `FightConfig`, owned by the engine

```python
# damage.py — beside FightState, above calculate_fight_damage
@dataclass(frozen=True)
class FightConfig:
    """Everything configurable about one fight, in one spelling.

    Pure configuration — champion_stats / ability_damages / items are
    DATA and stay positional arguments. Defaults mirror the engine's
    current keyword defaults.
    """

    target_health: float
    target_armor: float
    target_magic_resistance: float
    fight_duration_seconds: float
    target_bonus_health: float = 0.0
    auto_attack_uptime: float = 0.0
    one_rotation: bool = False
    include_actives: bool = True
    cast_order: list[str] | None = None
    auto_attacks_only: bool = False
    deterministic: bool = False
```

New signatures (data positional, config last):

```python
def calculate_fight_damage(
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    config: FightConfig,
) -> dict[str, Any]: ...

def _resolve_combat_state(
    champion_stats, ability_damages, items, config
) -> FightState: ...
```

### `FightParams` extends `FightConfig` (inheritance, not duplication)

```python
# pipeline.py
from .damage import FightConfig, calculate_fight_damage

@dataclass(frozen=True)
class FightParams(FightConfig):
    """FightConfig plus the parse-layer inputs the engine never sees."""

    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
```

- The 11 config fields are defined ONCE (in `FightConfig`); `FightParams`
  adds only the two parse-layer fields.
- `run_fight` passes `params` straight to the engine — a `FightParams`
  IS a `FightConfig`, so the 13-kwarg hand-mapping is deleted outright.
- Every existing `FightParams` consumer is untouched: attribute access
  (`params.target_health` in app/optimizer), `dataclasses.replace`
  (`optimizer.py:379`), and kwargs construction (`golden_snapshot.py:113`,
  `from_request`) all survive inheritance unchanged. Verified: no caller
  constructs `FightParams` positionally, so the inherited field order is
  a non-issue.
- Import direction is already `pipeline → damage`; no cycle.

### `ability_haste` parameter: deleted

The engine reads `champion_stats.get("ability_haste", 0.0)` directly,
matching how `basic_ability_haste` already flows. `run_fight`'s
derivation disappears. (The `.get(..., 0.0)` default matches the
sibling's existing pattern; tightening the whole `champion_stats`
contract is the separate deferred finding from the 2026-07-17 audit and
is out of scope here.)

Numerically neutral in production (`run_fight` passed exactly this
value). Two `test_known_good` cases pass a hand-validated explicit
`ability_haste=15.0` that differs from their stats dicts — migration
sets `stats["ability_haste"] = 15.0` instead, which the engine then
reads: same number, one transport.

### Alternatives considered (and why not)

1. **`params.fight` composition** (`FightParams` holds a `FightConfig`
   field): also single-source, but renames every `params.target_health`
   access in app/optimizer/golden/tests, or adds passthrough properties
   (thin-wrapper smell). Inheritance gets the same SSOT with zero caller
   churn.
2. **Separate `FightConfig` + a `FightParams.fight_config()` converter:**
   keeps two spellings of the field list — the exact disease.
3. **Engine consumes `FightParams` directly:** import cycle
   (`damage → pipeline → damage`), and the engine would depend on
   parse-layer concepts. Dead on arrival.
4. **TypedDict / `**kwargs` bag:** loses frozen-ness and loud typos;
   against the repo's fail-loud ethos.
5. **Do nothing:** the bundle didn't get worse with the champion seam,
   but every future fight input still costs five edits.

Honest wart of the chosen shape: the engine receives an object that
physically carries `ability_ranks`/`champion_options`. The *typed*
contract is `FightConfig` — the parse fields are invisible at the
interface — and the alternative (composition) costs real churn for
purity. Accepted, documented here.

## Migration sketch (for the future implementation plan)

1. Add `FightConfig` to `damage.py`; rewrite `calculate_fight_damage` /
   `_resolve_combat_state` signatures; delete the `ability_haste` param
   (engine reads stats). Rebase `FightParams` onto it; delete
   `run_fight`'s kwarg mapping. Four files, ~1 hour.
2. `conftest.fight` builds a `FightConfig` internally; its
   `**overrides` interface is unchanged, so fixture users need nothing.
3. Scripted mechanical sweep of the 123 direct test call sites: wrap
   config kwargs into `FightConfig(...)`, hoist `items` to positional,
   drop `ability_haste=0.0` / stats-derived haste kwargs, relocate
   `test_known_good`'s two explicit 15.0s into the stats dicts with a
   comment. (Same scripted-transform approach that migrated the
   champion-seam test entries.)
4. Gate: this is a PURE refactor — `pytest` fully green and the golden
   gate must show **zero** diffs (FightConfig is not serialized into the
   snapshot; behavior is unchanged). Pylint ≥ 9.4, black clean.

Payoff: a new fight input becomes two edits (one `FightConfig` field +
its engine consumer); the bundle has one spelling; the haste asymmetry
is gone.
