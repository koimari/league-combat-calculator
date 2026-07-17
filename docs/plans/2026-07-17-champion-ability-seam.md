# Champion Ability Seam — Full Plan

## Implementation status — COMPLETE (2026-07-17)

All four tasks executed same-day. Final state: 832 tests green, golden
snapshot identical, pylint 9.42, black clean. Deviations from the plan
as written, each deliberate:

- **The golden snapshot captures entry shapes**, so a "zero diffs"
  invariant was impossible while keys changed. The baseline was
  re-captured three times, each time only after verifying by category
  that EVERY diff was shape-only (parts added / legacy keys removed /
  `total_casts`→`cast_instances`) with zero numeric changes to stats,
  fights, or breakdown totals. `DamagePart.__repr__` is custom so
  closures serialize deterministically (no memory addresses).
- **Champions that post-process builder entries (Akshan R, Kog'Maw R,
  Amumu curse) migrated in Task 2**, not Task 3 — once `damage_entry`
  emitted parts, the engine's parts-first path would have silently
  ignored their legacy add-on keys (caught by tests + golden).
- **Three engine consumers of `total_casts` outside the ladder**
  (Shadowflame event split, burn refresh spread, Malignance Hatefog
  duration) were found via a numeric regression in `test_known_good`
  and repointed at `cast_instances`.
- **`total_raw` was kept** as the single producer-side diagnostic
  (heavily asserted, display-useful); the per-type keys
  (`magic_damage`/`physical_damage`/`true_damage`) were deleted
  everywhere. `parts_raw_total()` in `ability_spec.py` is the shared
  accessor for tests and the engine's mixed split.
- **`_ALLOWED_ENTRY_KEYS` includes champion display metadata**
  (`damage_per_tick`, `total_ticks`, `tibbers_aura`, `initial_burst`) —
  parse-layer keys never read by the engine, asserted by tests.



**Goal:** Delete the champion-specific key-presence ladder from
`damage.py::_compute_ability_rotation` by giving ability entries a typed
damage contract, so champion arithmetic lives in `champions/<name>.py`
and the engine evaluates one generic shape.

**Architecture (approved design):** Ability entries stay dicts for
scheduling metadata (`name`, `cooldown`, `recast_of`, `stat_buff`,
`on_hit`, `target_debuff`, `proc_count`, auto profile keys), but ALL
damage arithmetic moves into `parts: tuple[DamagePart, ...]` — frozen
dataclasses defined in a new leaf module `src/calculator/ability_spec.py`
that sits BETWEEN the champion layer and the fight engine (neither
imports the other; both import the contract). Champion-unique scaling
math (Akali R2 interpolation, Kog'Maw R curve, Akshan R missing-HP)
becomes a `hp_scaled_damage` closure built in the champion file — the
same pattern the item seam blessed with `RawDamageFormula`. The engine's
~10-branch ladder collapses to one part-evaluation loop that threads
running target HP through parts and casts.

**Prior art:** `docs/refactors/item-engine-boundary.md` (the item↔engine
seam this mirrors); three parallel design explorations (typed-categories /
callbacks / minimal-schema) run 2026-07-17 — the shipped design is the
minimal-schema shape with the callback hatch narrowed to per-part
HP scaling.

**Verification invariant:** every task ends with
`python -m pytest -q` fully green AND
`python scripts/golden_snapshot.py compare scripts/golden_baseline.json`
reporting `OK: snapshot identical`. This is a pure refactor: any golden
diff at any step is a bug in the step, not a baseline to re-capture.

## Old-key → new-shape mapping (complete inventory)

| legacy key (producer) | new shape |
|---|---|
| `magic_damage` / `physical_damage` / `true_damage` / `total_raw` | one `DamagePart(amount, type)` |
| mixed split (damage_entry `"mixed"`) | two parts: (total/2 magic), (total/2 true) |
| `initial_damage` + `subsequent_damage` (Ahri W) | `(P(initial, magic), P(subsequent, magic, count=2))` |
| `damage_per_cast` + `total_casts` (Ahri R) | `(P(per_dash, magic, count=3),)` + `cast_instances: 3` |
| `total_casts` (Muramana proc cadence) | `cast_instances` (plain int key, default 1) |
| `r2_min`/`r2_max`/`missing_hp_scaling` (Akali R) | part 2 `hp_scaled_damage=lambda r: r2_min + (r2_max - r2_min) * r` |
| `r_base_damage`/`missing_hp_scaling` (Kog'Maw R) | `hp_scaled_damage=_living_artillery_scaled(base)` piecewise closure |
| `crit_effectiveness` (Akshan R) | `DamagePart.crit_effectiveness` |
| `missing_hp_max_bonus` (Akshan R) | `hp_scaled_damage=lambda r: base * (1.0 + 2.0 * r)` |
| `name, rank, cooldown, damage_type, recast_of, stat_buff, target_debuff, on_hit, proc_count, auto_attack_override, double_shot` | unchanged dict keys |

Non-goals (explicitly out of scope): the Ashe/Fiendhunter/Sundered-Sky
crit interleave stays in `_simulate_auto_attacks` (item×champion timing
is engine-owned; all three designs agreed); `auto_attack_override` /
`double_shot` remain dict keys; the 15-param `calculate_fight_damage`
signature is a separate deferred cleanup.

## File map

- `src/calculator/ability_spec.py` (new) — the champion→engine damage
  contract: `DamagePart` only.
- `src/calculator/damage.py` (modify) — `_evaluate_cast_parts()` generic
  evaluator; rotation ladder → parts loop (legacy fallback during
  migration, deleted at the end); `_add_precomputed_proc_damage` reads
  parts; `total_casts` → `cast_instances`.
- `src/calculator/champions/slotlib.py` (modify) — `damage_entry` /
  `ability_on_hit_entry` / `proc_damage` emit `parts`; legacy damage
  keys removed at the end.
- `src/calculator/champions/{ahri,akali,kogmaw,akshan,ashe,amumu,annie}.py`
  (modify) — hand-rolled entries emit parts; scaling closures move in.
- `src/calculator/champions/engine.py` (modify, last slice) — entry-key
  validation: unknown keys raise with champion+slot context.
- `tests/test_ability_spec.py` (new) — evaluator unit tests.
- `tests/test_engine.py`, `tests/test_<champion>.py` (modify) — entry
  shape assertions updated per slice.
- `architecture.md` (modify, last slice) — contract documented.

---

## Task 1 — the contract and the evaluator (pure addition)

**Files:** `src/calculator/ability_spec.py` (new),
`src/calculator/damage.py`, `tests/test_ability_spec.py` (new).

`ability_spec.py`:

```python
"""The champion→engine ability-damage contract.

An ability entry carries its damage arithmetic as a tuple of DamageParts;
the fight engine evaluates parts generically (damage.py::
_evaluate_cast_parts) and never branches on champion-specific keys.
Champion-unique scaling math lives in the champion module as a
``hp_scaled_damage`` closure on the part.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DamagePart:
    """One mitigation unit of one ability cast.

    The engine evaluates parts in order, threading the target's running
    mitigated damage: a part's ``hp_scaled_damage`` sees the damage of
    parts (and casts) evaluated before it — Akali R2 scales off the HP
    remaining after R1.

    Attributes:
        damage_type: "magic" | "physical" | "true".
        amount: Raw damage when ``hp_scaled_damage`` is None.
        count: Times the part hits per cast (Fox-Fire subsequent ×2).
        hp_scaled_damage: missing_ratio (0..1) → raw damage for one hit;
            overrides ``amount``.
        crit_effectiveness: >0 — the part crits at this effectiveness
            (Akshan R: 0.3).
    """

    damage_type: str
    amount: float = 0.0
    count: int = 1
    hp_scaled_damage: Callable[[float], float] | None = None
    crit_effectiveness: float = 0.0
```

`damage.py` gains (near the rotation, no callers yet):

```python
def _evaluate_cast_parts(
    state: "FightState",
    parts: tuple[DamagePart, ...],
    num_casts: int,
    ability_mr: float,
    running_damage: float,
) -> tuple[float, float]:
    """Evaluate an ability's typed damage parts over its casts.

    Returns (total mitigated damage pre-amp, first part's mitigated
    damage on the first cast — the Horizon Focus trigger value for
    mixed entries). Threads running target damage through every part
    and cast so HP-scaled parts see prior hits.
    """
    resists = state.resists
    target_health = state.target_health
    total = 0.0
    first_part_first_cast = 0.0
    for cast_index in range(num_casts):
        for part_index, part in enumerate(parts):
            if part.hp_scaled_damage is not None:
                hp_now = max(0.0, target_health - running_damage)
                missing_ratio = (
                    1.0 - hp_now / target_health if target_health > 0 else 1.0
                )
                raw = part.hp_scaled_damage(missing_ratio)
            else:
                raw = part.amount
            if part.crit_effectiveness > 0:
                eff = part.crit_effectiveness
                bonus_crit = state.crit_multiplier - BASE_CRIT_MULTIPLIER
                raw *= (
                    1
                    + eff * state.crit_chance
                    + eff * bonus_crit * state.crit_chance
                )
            if part.damage_type == "true":
                mitigated = raw * part.count
            elif part.damage_type == "physical":
                mitigated = (
                    apply_resistance(raw, resists.effective_armor) * part.count
                )
            else:
                mitigated = (
                    apply_resistance(raw, ability_mr) * state.magic_amp * part.count
                )
            if cast_index == 0 and part_index == 0:
                first_part_first_cast = mitigated
            total += mitigated
            running_damage += mitigated
    return total, first_part_first_cast
```

**RED:** `tests/test_ability_spec.py` — construct a minimal FightState
via the existing conftest `fight` harness? No — unit-test the evaluator
directly with a stub state (namespace with `resists`, `target_health`,
`magic_amp`, `crit_chance`, `crit_multiplier`). Cases:
1. single magic part == `apply_resistance(raw, mr) * magic_amp`;
2. two-part Akali shape: part2's closure receives missing ratio that
   includes part1's mitigated damage;
3. physical part with `crit_effectiveness=0.3` reproduces
   `raw * (1 + 0.3*cc + 0.3*(cm-2.0)*cc)`;
4. `count=2` doubles one part; `num_casts=2` re-evaluates HP per cast;
5. true part ignores resists and magic_amp.

**Verify:** `python -m pytest tests/test_ability_spec.py -q` green; full
suite green; golden identical (nothing calls the new code yet).

## Task 2 — builders emit parts; engine consumes parts when present

**Files:** `src/calculator/champions/slotlib.py`,
`src/calculator/damage.py`, `tests/test_engine.py`.

1. `slotlib.damage_entry` appends parts (keeping legacy keys for one
   slice so unmigrated readers keep working):
   - magic/physical/true → `(DamagePart(dmg_type, total),)`
   - mixed → `(DamagePart("magic", total/2), DamagePart("true", total/2))`
2. `ability_on_hit_entry` adds `"parts": ()`.
3. `proc_damage`'s emitted entry adds
   `"parts": (DamagePart(dmg_type, per_proc),)` (per-proc, NOT
   `per_proc * count` — assert against its `total_raw` semantics when
   editing; `proc_count` still owns the count).
4. `_compute_ability_rotation`: where the `damage_type` ladder begins,
   insert the new path:

```python
        if "parts" in ability_info:
            ability_total, first_part_damage = _evaluate_cast_parts(
                state,
                ability_info["parts"],
                num_casts,
                ability_mr,
                mitigated_damage_dealt,
            )
        elif damage_type == "mixed":
            ... legacy ladder unchanged ...
```

   and the Horizon Focus block prefers the parts result:
   `mixed → first_part_damage`, otherwise `ability_total / num_casts`.
5. Muramana cadence: read `cast_instances` first, fall back to legacy
   `total_casts` until Task 3 migrates Ahri:
   `ability_info.get("cast_instances", ability_info.get("total_casts", 1))`.
6. `_add_precomputed_proc_damage`: prefer `parts[0].amount` /
   `parts[0].damage_type` when parts present, legacy chain otherwise.

**Verify:** full suite green; golden identical (every builder-produced
champion now flows through the evaluator — this is the highest-risk
slice, run golden FIRST if iterating).

## Task 3 — hand-rolled champion entries migrate, one file per commit

Order: **ahri → akali → kogmaw → akshan → ashe → amumu → annie**, then
grep-sweep `total_raw|magic_damage|physical_damage|true_damage` over
`src/calculator/champions/*.py` for stragglers. Each champion: emit
`parts` (+ `cast_instances` where relevant), delete that file's legacy
damage keys, update its shape-asserting tests, run suite + golden.

- `ahri._fox_fire` →
  `parts=(DamagePart("magic", initial), DamagePart("magic", subsequent, count=2))`
- `ahri._spirit_rush` →
  `parts=(DamagePart(damage_type, per_cast, count=3),)`, `cast_instances=3`,
  still NO `cooldown` key (spacing rule unchanged).
- `akali._perfect_execution` →

```python
    span = r2_max - r2_min
    return {
        "name": ability.get("name", "Perfect Execution"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "parts": (
            DamagePart("magic", r1_damage),
            DamagePart(
                "magic",
                hp_scaled_damage=lambda missing: r2_min + span * missing,
            ),
        ),
    }
```

- `kogmaw._living_artillery` — closure beside the slot fn:

```python
def _living_artillery_scaled(base: float) -> Callable[[float], float]:
    """R missing-HP curve: +50% linearly to 60% missing, then +100%."""

    def scaled(missing_ratio: float) -> float:
        if missing_ratio >= 0.6:
            return base * 2.0
        return base * (1.0 + 0.5 * (missing_ratio / 0.6))

    return scaled
```

  entry: `parts=(DamagePart("magic", hp_scaled_damage=_living_artillery_scaled(base)),)`.
- `akshan._comeuppance` →
  `parts=(DamagePart("physical", hp_scaled_damage=lambda m: total * (1.0 + _R_MISSING_HP_MAX_BONUS * m), crit_effectiveness=_R_CRIT_EFFECTIVENESS),)`
  (where `total = per_bullet * bullets`).
- `ashe._rangers_focus` / `_frost_shot` → replace
  `"total_raw": 0.0` / `"physical_damage": 0.0` with `"parts": ()`.
- `amumu` / `annie` hand entries → read the files, same mechanical move
  (amumu's mixed true-bonus becomes an explicit second true part).

**Verify per champion:** suite + golden identical.

## Task 4 — delete the legacy path; validate; document

**Files:** `damage.py`, `slotlib.py`, `engine.py`, `architecture.md`.

1. `damage.py`: delete the legacy ladder (`elif damage_type == "mixed":`
   through the `else: total_raw` arm), the legacy `total_casts` fallback,
   and `_add_precomputed_proc_damage`'s legacy chain. `parts` becomes a
   required key for castable entries — `ability_info["parts"]`, KeyError
   is the loud failure.
2. `slotlib`: builders stop emitting `magic_damage`/`physical_damage`/
   `true_damage`/`total_raw` (keep `damage_type` — breakdown label,
   Bloodletter check, Horizon mixed rule).
3. `engine.py::build_parser`: validate every emitted entry against

```python
_ALLOWED_ENTRY_KEYS = frozenset({
    "name", "rank", "cooldown", "damage_type", "parts", "cast_instances",
    "recast_of", "stat_buff", "target_debuff", "on_hit", "proc_count",
    "auto_attack_override", "double_shot", "stacks_required",
})
```

   (confirm the exact set against `build_parser`'s result handling and
   any keys the on-hit path adds — e.g. `stacks_required` — while
   editing; unknown key → `ValueError` naming champion, slot, and key.)
   RED first: `test_engine.py` test that a slot parser returning
   `{"r2_mn": 1}` raises naming the key.
4. `architecture.md`: add `ability_spec.py` to the module map (champion
   layer), update the `damage.py` description ("consumes typed
   DamageParts, never champion-specific keys"), update champion-file
   docstrings that referenced the old keys (ahri/akali/kogmaw headers).
5. Grep gates (all must return nothing in `src/`):
   `grep -rn "total_raw\|initial_damage\|damage_per_cast\|r2_min\|r_base_damage\|missing_hp_scaling\|missing_hp_max_bonus\|crit_effectiveness.*in ability_info" src/calculator/damage.py`

**Verify:** full suite green; golden identical;
`python -m pylint src/` ≥ 9.4; `python -m black src/ tests/` clean.

## Self-review notes

- Numeric-equivalence traps encoded above: the mixed true-half is
  unmitigated and un-amped; Akshan is `apply_resistance` against armor
  with NO magic_amp; Akali R2's missing ratio includes R1's UNAMPED
  mitigated damage; `ability_total *= state.ability_amp` stays OUTSIDE
  the evaluator; `mitigated_damage_dealt += ability_total` (amped)
  after each ability, while intra-ability threading is unamped. The
  evaluator's `running_damage` reproduces exactly this.
- R never multi-casts (`one_rotation or ability_key == "R"` → 1), so
  per-cast HP re-evaluation is numerically identical for Akali/Akshan
  (single cast) and matches Kog'Maw's existing per-cast loop.
- Every legacy key has a named new home (table above); no TBDs.
