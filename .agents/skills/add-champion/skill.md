---
name: add-champion
description: Step-by-step guide for adding a new LoL champion to the calculator. Use when creating a champion module, registering it, or writing champion ability tests.
---

# Add a New Champion

Every champion — registered or not — runs on the slot-archetype engine
(`src/calculator/champions/engine.py`). A champion is a **slot map**
`{slot: slot_parser}`; slot parsers come from the archetype factories in
`slotlib.py` or are custom functions in the champion's own module. There is
no other parse path.

## Triage: three tiers, cheapest first

Work down this ladder and stop at the first tier that fits. Most champions
stop at tier 1 — every champion that needs a file is a small failure of the
generic path, so don't skip ahead "just in case."

1. **Nothing (generic path).** Champions absent from `_CHAMPION_MODULES`
   run `GENERIC_SLOTS` (classifier-driven `simple_damage()` on Q/W/E/R,
   `on_hit_auto()` on P). Verify it already works — see "Tier 1" below.
2. **Slot map of archetypes.** The generic parser picked a wrong attribute
   or the kit matches an existing archetype (stat-buff R, option-dispatched
   Q, %maxHP on-hit, toggle DoT, ...). New `champions/<name>.py` that is
   mostly `SLOTS = {...}` of `slotlib` factory calls + one registry line.
3. **Custom slot functions.** Genuinely unique mechanics (prose-regex
   values, multi-part entry shapes, cross-slot dependencies). Still a slot
   map — the custom fn sits next to the archetype calls in the same file.

## Tier 1 — verify the generic path

```python
import json
from src.calculator.data_fetcher import get_champion
from src.calculator.champions import parse_champion_abilities
champ = get_champion("ChampionName")
stats = {"attack_damage": 150.0, "bonus_attack_damage": 50.0, "ability_power": 200.0}
result = parse_champion_abilities(champ, 13, 200.0,
                                  champion_stats=stats,
                                  target_stats={"target_max_health": 2500.0})
print(json.dumps(result, indent=2))
```

(`parse_champion_abilities` dispatches on the data's own display name, so a
cache-key spelling like `KogMaw` can never bypass a registered `Kog'Maw`
module.)

Cross-check each slot's `total_raw` / `damage_type` / `cooldown` against the
[LoL Wiki](https://wiki.leagueoflegends.com/en-us/ChampionName). If every
damaging slot is right: **done, no code**. Optionally add a skill-order
override (below). The mass-coverage tests in `tests/test_generic_path.py`
and the golden snapshot already cover the champion.

Typical generic-path failures that push you to tier 2:
- Classifier picked the single-hit attribute when the kit always lands more
  (`"Physical Damage"` instead of `"Total Physical Damage"` — the
  classifier deliberately excludes "total"/"subsequent" names).
- A zero-damage stat-buff/utility slot was dropped that should display.
- Wrong damage type (mixed kits), missed on-hit passive, charge cooldown.

## Tier 2 — slot map of archetypes

### Step 1: Inspect the JSON

```python
from src.calculator.data_fetcher import get_champion
champion_data = get_champion("ChampionName")
for slot in ['P', 'Q', 'W', 'E', 'R']:
    for k, ab in enumerate(champion_data['abilities'][slot]):
        print(f'=== {slot}[{k}]: {ab["name"]} ===')
        print(f'damageType: {ab.get("damageType")}  targeting: {ab.get("targeting")}')
        for i, effect in enumerate(ab.get('effects', [])):
            for j, lev in enumerate(effect.get('leveling', [])):
                mods = [{'values': m['values'][:5], 'units': m['units'][:5]}
                        for m in lev.get('modifiers', [])]
                print(f'  effect[{i}].leveling[{j}]: attr="{lev.get("attribute", "")}" mods={mods}')
```

The `attribute` strings you see here are what you pass to shared extractors or
the small set of factories. Per-level scaling appears as synthetic leveling
entries with ~20 values; champion-local functions pass `ctx.level` when the
mechanic scales by champion level rather than ability rank.

### Step 2: Write the module

`src/calculator/champions/<name>.py` — shared factories for ordinary slots,
short champion-local functions for unique mechanics:

```python
"""ChampionName — slot map for the archetype engine.

Why each slot is non-generic:
- Q must read "Total Magic Damage" instead of the classifier's first match.
- R has a unique multi-part output shape, so it stays champion-local.
- ... (one bullet per slot; also note deliberately-absent slots)
"""

from typing import Any
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage

def _unique_ultimate(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    return damage_entry(ability["name"], rank, extract_cooldown(ability, rank), total, "magic")

OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "Q uses the full combined hit",
]

SLOTS = {
    "Q": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "R": _unique_ultimate,
}

parse_abilities = build_parser(SLOTS, "ChampionName")
```

Rules:
- **Module docstring says WHY each slot is non-generic** — that is the
  file's reason to exist.
- **No hardcoded numbers.** Everything comes from the JSON attributes. The
  only exception: wiki-prose values with no JSON home (Annie's Tibbers
  aura, Vayne's every-3rd-hit) — quarantine them as module constants under
  a `# HARDCODED: verify on patch updates` comment with the wiki URL.
- A slot that deals no damage and shouldn't display is simply **absent**
  from the map.
- `OPTIONS` and `ASSUMPTIONS` are **mandatory** on every module (empty
  lists are fine) — the dispatcher reads them unconditionally.

### The archetype library (slotlib.py)

| Archetype | Use for | Key params |
|---|---|---|
| `simple_damage` | any single damage read | `attr` (None = classifier), `dmg_type`, `casts` (int or attribute name), `source`/`cooldown_from` `(slot, idx)`, `cooldown="recharge"`, `ranks="level"` |
| `stat_buff` | steroid R/Q (BUFF phase) | `attr`, `stat`, `mode="flat"/"percent_of"`, `apply_to` (ctx.stats keys for in-parse scaling), `damage_attr`, `couples` |
| `by_option` | option picks the parser (sweetspot / condemn_wall) | `option`, `{value: parser}`, `default` — cases must share phase and entry keys |
| `proc_damage` | option-counted proc with champion-owned extraction (Akali/Ambessa/Akshan P) | `per_proc(ctx, ability)`, `dmg_type`, `count_option`, `default_count`, optional `name` |
| `on_hit_auto` | classifier-detected passive on-hit | optional `source` |

Extraction helpers for custom fns: `extract_named` (damage for an exact
attribute), `extract_value` (raw leveling number, no scaling),
`extract_auto` (classifier detection), `extract_cooldown`,
`find_named_leveling` / `sum_modifiers` (shared modifier walk with an unusual-unit
override), `pct_health_per_hit` (shared %maxHP math), and entry builders
`damage_entry` / `on_hit_entry` / `ability_on_hit_entry`.

**Growing the library:** an archetype must have **>= 2 real users**, and no
flag may change WHICH fight-engine keys it emits — if a new user needs a
different entry shape, that user is a custom fn over the shared math
(precedent: Kog'Maw W / Vayne W around `pct_health_per_hit`).

### The phase system

The engine evaluates slots in phase order **BUFF -> DEBUFF -> DAMAGE ->
ONHIT -> AMP**, insertion order within a phase. Archetypes stamp their own
phase; a custom fn defaults to DAMAGE and opts in via
`my_parser.phase = BUFF` (import the constant from `.engine`).

- **BUFF** mutates `ctx.stats` (steroids) — every damage slot then parses
  against buffed stats automatically. Never hand-order "R first".
- **DEBUFF** documents shreds (Kog'Maw Q); damage.py applies them at fight
  time.
- **ONHIT** emits per-auto entries; **AMP** mutates other slots' entries in
  `ctx.results` after all damage is parsed (Amumu's curse pseudo-slot).
- Within a phase, `ctx.results` is readable — a slot that depends on
  another lists AFTER it in the map (Ashe P reads whether Q emitted).
- Slot keys map to results keys identically except `"P"` -> `"passive"`.
  Synthetic keys are fine (`"Q2"`, `"passive_double_shot"`); a display row
  that must land under literal `"P"` is written into `ctx.results["P"]`
  directly by a custom fn returning None (Annie/Amumu pattern).
- The engine emits every non-None entry, **including zero damage** — a
  stat-buff ultimate must never silently vanish.

### Step 3: Register

Add to `_CHAMPION_MODULES` in `src/calculator/champions/__init__.py`
(alphabetical):

```python
_CHAMPION_MODULES: dict[str, str] = {
    ...
    "NewChampion": "new_champion",
}
```

### Skill-order override (optional, any tier)

If the champion doesn't max Q>W>E, add its 18-level sequence to
`_SKILL_ORDERS` in `skill_orders.py` (R at 6/11/16). Sequences stay 18
entries even though `MAX_LEVEL` is 20 — levels 19-20 grant no skill
points; `get_ability_rank` caps the lookup.

## Tier 3 — custom slot functions

A custom slot parser is `def _my_slot(ctx: SlotCtx) -> dict | None:` living
in the champion's file, mixed freely into `SLOTS` beside archetype calls.
`SlotCtx` gives you: `ctx.ability(slot=None, index=0)` (JSON entry),
`ctx.rank_for(slot=None)`, `ctx.level`, `ctx.stats` (mutable, AP already
merged), `ctx.target`, `ctx.options`, `ctx.results`.

Standard preamble (rank-gated slots):

```python
def _my_slot(ctx: SlotCtx) -> dict[str, Any] | None:
    """One-line: what this slot emits and why it's custom."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ...
    return damage_entry(ability.get("name", "..."), rank,
                        extract_cooldown(ability, rank), total, "magic")
```

Go custom when the mechanic is single-user: prose-regex extraction (Akshan,
Ambessa P), multi-part damage (Ahri W's two-tier flames as two
`DamagePart`s), HP-scaled damage closures (Akali/Kog'Maw/Akshan R), or
coupling a buff with conditional entry parts (Ashe Q). A thin wrapper over
an archetype is also fine (Kog'Maw R = `simple_damage` + a
`hp_scaled_damage` closure swapped onto the part; Ambessa Q2 = `by_option`
+ `recast_of` stamp).

Study for patterns: `anivia.py` (unique toggle kept local), `vayne.py` (stat_buff
couples + shared on-hit shell), `amumu.py` (AMP pseudo-slot, literal-"P" display row),
`akshan.py` (the honest ceiling: mostly regex custom fns).

## Entry shape (what the fight engine expects)

Castable entries carry `name`, `rank`, `cooldown`, `total_raw`
(test/golden diagnostic — the engine reads only `parts`), `damage_type`
("magic"/"physical"/"true"/"mixed" summary
label), and `parts` — a tuple of `ability_spec.DamagePart` holding ALL
damage arithmetic (`amount`/`count` per mitigation unit, an optional
`hp_scaled_damage` closure taking the target's missing-HP ratio, and
`crit_effectiveness`) — `slotlib.damage_entry` builds the standard case.
Optional keys the fight engine dispatches on: `on_hit` (`{name,
damage_per_hit, damage_type, stacks_required?}`), `stat_buff`
(`{stat_key: value}`, applied to champion stats before the fight),
`target_debuff`, `cast_instances` (per-cast item procs, e.g. Ahri R = 3),
`proc_count`, `recast_of`, `auto_attack_override`, `double_shot`.
`engine.py` validates entry keys against `_ALLOWED_ENTRY_KEYS` — an
unknown key raises at parse time. Copy the exact shape from the closest
existing module — the golden snapshot locks key shapes, not just values.

## OPTIONS and ASSUMPTIONS (frontend, zero JS)

Champion options and assumption notes are **declared in the module** and
served to the frontend via `/api/config` (`get_champion_options_meta` in
`champions/__init__.py`). app.js renders them generically — adding an
option never touches JavaScript.

```python
OPTIONS = [
    # bool -> checkbox; int/float -> number input with min/max/step.
    {"key": "sweetspot", "type": "bool", "default": True, "label": "Q Sweetspot hits"},
    {"key": "passive_procs", "type": "int", "default": 4,
     "label": "Passive procs", "min": 0, "max": 20},
]
ASSUMPTIONS = [
    "Assumed R is always active",   # shown under the damage breakdown
]
```

Rules:
- The parse path reads options via `ctx.options.get(key, default)` or
  archetype params (`by_option(key, ...)`, `count_option=key`). Duration
  and count options with no archetype home are plain `ctx.options.get`
  reads in a custom fn (Anivia's `r_duration`).
- **Reserved keys** (`RESERVED_OPTION_KEYS` in `champions/__init__.py`)
  are pipeline-owned and must never appear in OPTIONS
  (`tests/test_champion_options.py` enforces this). Currently:
  `fight_duration_seconds` — injected by `pipeline.run_fight` for timed
  (non-one-rotation) fights so duration-driven mechanics can scale with
  the fight window (Aurelion Sol's continuous Q channel). Read it with
  `ctx.options.get("fight_duration_seconds")`: present -> model the whole
  fight (pin the entry's cooldown to 999 so it casts once); absent ->
  per-cast model (one-rotation mode and direct parse calls).
  Caller-supplied values for reserved keys are stripped by the pipeline.
- **The Python default is the source of truth** — the declared `default`
  must match what the parse path falls back to.
- Every declared key must appear as a string in the module source —
  `tests/test_champion_options.py` enforces this (pass `count_option=`
  explicitly rather than relying on a slotlib default).
- Document every simplifying assumption (always-active buffs, all hits
  land, full stacks, skipped abilities) in ASSUMPTIONS.

## Tests

Champion test files are for champions with modules (tiers 2-3); the generic
path is covered by `tests/test_generic_path.py` + the golden snapshot.
Create `tests/test_<champion>.py` using the conftest fixtures:

- **`<champion>_data`** — one line in `tests/conftest.py`:
  `<name>_data = _champion_fixture("DataKey")` (the cache data key can
  differ from the display name — `KogMaw` vs `Kog'Maw`).
- **`parse_at`** — `stats, abilities = parse_at(data, level, *, items=None,
  ap=0.0, **kwargs)` — stats + dispatcher parse in one call.

Cover: damage types; hand-validated damage values against the wiki (use
`parse_at`); cooldowns present; each champion option's effect (on vs off);
absent slots stay absent; stat-buff entries (0 damage + correct buff
value); fight-engine integration where the module adds flags. When
comparing manual math to parser output, use a pre-6 level so the R buff
doesn't distort the comparison. Validate raw JSON reads with
`slotlib.extract_named` / `extract_value` — don't add module-private
wrappers just for tests.

## Gates (run before calling it done)

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/golden_snapshot.py capture <tmpfile>
.venv/Scripts/python.exe scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

Full suite green. For a NEW champion the golden compare must be identical
for every existing entry (your champion's entries are additions); after the
champion is validated, re-capture the baseline so it's locked too. When a
refactor is involved: never re-capture to make a diff go away.

Also run `black` on touched files and check `pylint` for new findings.

## Data accuracy

- JSON is wiki-scraped; on any suspect value check the wiki page's **Patch
  history** section first — it settles buffed/nerfed/reworked/removed
  questions authoritatively.
- If the wiki disagrees with the JSON, trust the wiki and note the
  discrepancy.
- Known-good cases validated against the game client go in
  `tests/test_known_good.py`.

## Log bugs for future reference

When the user reports a bug after implementation, **immediately** append it
to `.claude/skills/analyze-champion/bug-history.md`:

```
### <Champion> — <short description>
- **What happened:** <the incorrect behavior>
- **Root cause:** <why it was wrong>
- **Pattern to watch for:** <generalized rule for future champions>
```

The "Pattern to watch for" is the important part — describe the general
class of mistake so `/analyze-champion` can flag it on future champions.
