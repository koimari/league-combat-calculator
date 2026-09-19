# Slop audit: code quality, duplication and drift in src/calculator/champions/

Scope: 207 files, 57,976 lines. 174 are champion modules totalling 49,001 lines.
The other 33 are shared helpers. Every count below comes from a script over all
174 modules, not a sample. Scripts live in `.audit/pat_clones.py`,
`.audit/pat_census.py`, `.audit/pat_census2.py`, `.audit/pat_census3.py`, outside
the repo tree.

Modules read for style drift: `akali.py` from 2026-03-15, `kogmaw.py` from
2026-07-10, `xayah.py` and `naafiri.py` from 2026-08, `yunara.py` from 2026-09,
plus the helpers `slotlib.py`, `module_helpers.py`, `slot_context.py`,
`slot_entries.py`, `inputs.py`, `healing_helpers.py`, `ability_prose.py` and
`module_survey.py`.

Headline: the contract itself is in good shape. Declaration spelling is
near-uniform, zero options go unread, zero `MODULE_COVERAGE` declarations restate
the derivation, zero mutable defaults, zero builtin shadowing, three
`sightline-ok` markers in 58k lines. The slop sits in four places. Prose is 24.8%
of the tree. A six-parameter healing contract forces 60 copies of one signature
and 53 pylint suppressions. Two guard idioms are typed out 146 times where a
decorator already proves the shape absorbable. Four helpers shipped and were then
half-adopted: `CachedSentence` at 12 of 37, `no_damage_slot` at 13 of 30,
`at_level` at 11 of 17, and the three typed event-row readers at 0 of 60.

## Findings table

| # | Finding | Count | Lines | Proposal |
|---|---|---|---|---|
| 1 | `derive_self_healing` repeats one six-positional signature, leaves 113 parameters unread, and carries 53 pylint suppressions | 60 modules | 2,490 total, 420 removable | One frozen `SelfHealCtx`. One call site changes, in `healing_contract.ChampionHealingRule.derive`. Codemod. |
| 2 | Module docstrings over 30 lines, carrying changelogs and trap knowledge | 69 modules | 3,062, cap at 20 to remove 1,680 | Move traps to `TRAPS.md`, delete campaign narration. Per file, not a codemod. |
| 3 | `ASSUMPTIONS` strings average 252 characters | 162 modules | 3,606, 900 removable | Cap each string at 120 characters, enforced in `scripts/prose_lint.py`. |
| 4 | `ctx.ability()` and `ctx.ranked()` None-guards typed out on the parser's own slot | 80 of 146 sites | 160 removable | Add `@ability_slot` beside the existing `@ranked_slot`. Codemod. |
| 5 | Single-use rule classes: one instance, one `public_receipt()` reader, two with no state | 10 classes | 474, 250 removable | Module-level frozen dict, or one shared `state_receipt(name, rule)`. |
| 6 | Trivial `no_damage(...)` wrapper functions where `module_helpers.no_damage_slot` already exists | 17 functions | 193, 160 removable | Give `no_damage_slot` a `name=` and `phase=`. The slot becomes one line in `SLOTS`. |
| 7 | Hand-built ability-entry dict literals where `slot_entries.damage_entry` is the home | 82, of which 27 are core-expressible | 1,381 total, 379 core, 220 removable | Give `damage_entry` a `parts=` and `detail=` path, then codemod the 27. |
| 8 | Hand-rolled cached-prose regex readers where `ability_prose.CachedSentence` is the home | 25 modules, 56 `re.*` sites, 7 of them silent | 180 removable | Finish the migration. The 7 silent readers are a correctness class, not style. |
| 9 | History narration in comments and docstrings | 146 lines across 67 and 36 files | 146 removable | Extend `scripts/prose_lint.py` from `.md` to `.py` under `champions/`. |
| 10 | Two homes for one fact: `_ROTATION_CLASSIFICATIONS` holds 253 rows, and an OPTIONS row already accepts an inline `rotation=` | 253 central, 37 inline, 4 dead | 385 relocated | Move every row onto its OPTIONS entry, delete the table and the fallback branch. Codemod. |
| 11 | Hand-rolled level-bracket readers where `module_helpers.at_level` is the home | 6 modules | 40 | Codemod to `at_level`. |
| 12 | Module-level numeric literals with no provenance note. Nine restate a cached `castTime` | 122 unnoted of 326, 9 proven | 9 | Read through `slot_extract.extract_cast_time`. Lint the rest. |
| 13 | `MODULE_CC` spelling drift: 10 all-`"none"` dict literals against 1 `dict.fromkeys` | 11 | 10 | Pick one spelling. |
| 14 | `event.get("damage", 0.0)` inside healing resolvers, while `damage_event_row`, `heal_event_row` and `cast_event_row` exist and no champion module imports them | 69 sites in 41 modules | swap, not delete | Route the resolvers through the three typed readers. The frontier ratchet drops to zero. |
| | Total | | about 4,100 lines, 8.4% of the champion tree | |

## 1. Copy-paste across modules

### Whole-function AST clones

`.audit/pat_clones.py` renames every bound name positionally, flattens numeric
and string literals, and hashes the resulting body. Across 1,072 functions it
finds 13 cross-file groups, of which 6 hold three or more members. Those 6 cover
30 functions and 218 redundant lines. That is a low number, and it means the
champion formulas really are per champion.

| Members | Shape | Owner that should hold it |
|---|---|---|
| 8 | `return no_damage(ctx, name="...", reason="...")` | `module_helpers.no_damage_slot`, which exists and these do not call |
| 6 | `return f(g, "lit", h)`, stack-state readers | none, incidental |
| 5 | `return no_damage(ctx, name="...", reason="...", slot="...")` | same as the group of 8 |
| 5 | `return damage_entry(a, "x", "y", time_offset=0)` | incidental, fine |
| 3 | `return f(x) if pred(x) else g(x)`, form switches at `gnar.py:263`, `gnar.py:319`, `jayce.py:196` | a `form_switch(pred, a, b)` in `module_helpers` |
| 3 | `return lo + (hi - lo) * t` at `aurora.py:97`, `lee_sin.py:62`, `naafiri.py:354`, plus the same expression inline at `akali.py:66` | a one-line `lerp` in `module_helpers` |

The two `no_damage` groups are the real finding. All 17 members:

```
elise.py:96 _cocoon              fiora.py:72 _grand_challenge
garen.py:38 _courage             gwen.py:146 _hallowed_mist
heimerdinger.py:253 _upgrade     jayce.py:570 _hextech_capacitor
lucian.py:80 _relentless_pursuit zac.py:144 _cell_division
evelynn.py:18 _demon_shade       fiddlesticks.py:20 _scarecrow
fizz.py:19 _nimble_fighter       garen.py:18 _perseverance
gragas.py:19 _happy_hour         and 4 more, 193 lines total
```

`module_helpers.no_damage_slot(reason)` at line 392 is exactly this shape, and 13
modules call it. The 17 hold-outs pass a hard-coded `name=` instead of the cached
`ability_name(ability)`, and one needs `.phase = BUFF`. Adding
`name: str | None = None, phase: str = DAMAGE` to `no_damage_slot` absorbs all 17,
and each slot then reads as one line inside `SLOTS`.

### Statement-block clones, which are the guard idioms

Block-level hashing returns 901 cross-file groups, dominated by import blocks and
runs of constant assignments, so the useful signal is the named idiom census.

| Idiom | Sites | Files | Absorbable |
|---|---|---|---|
| `x = ctx.ability(...)` then `if x is None: return None` | 110 | 95 | 71 on the parser's own slot, 30 on `"P"` or `"W"` |
| `ranked = ctx.ranked(...)` then `if ranked is None: return None` then `ability, rank = ranked` | 36 | 29 | 9 on the own slot |
| `if x is None: return None`, all forms | 201 | 127 | |

`@ranked_slot` at `module_helpers.py:66` already proves the pattern absorbs: 124
files carry 215 decorations. There is no `@ability_slot`. Add one:

```python
def ability_slot(slot: str | None = None, index: int = 0): ...   # (ctx, ability) -> entry
```

80 own-slot sites collapse from three lines to zero, and the 30 cross-slot sites
become `@ability_slot("P")`. That is about 160 lines, and it gives one home to
the question of what `None` means here, which `SlotCtx.ranked` documents once and
110 call sites restate.

### The rule-class clone group

Ten classes, 474 lines, one shape.

| File and line | Class | Lines | Uses | State |
|---|---|---|---|---|
| `aurelion_sol_stardust.py:42` | `_StardustRule` | 88 | 5 | `__init__` copies module constants |
| `gangplank.py:106` | `_RemoveScurvyRule` | 60 | 1 | same |
| `ksante.py:108` | `_PathMakerRule` | 57 | 1 | same |
| `vladimir.py:116` | `_TidesOfBloodBoundaryRules` | 57 | 1 | none |
| `heimerdinger.py:90` | `_MicroRocketsRule` | 46 | 1 | `__init__` copies constants |
| `heimerdinger.py:141` | `_GrenadeRule` | 41 | 1 | same |
| `zeri.py:42` | `_LivingBatteryExecuteRule` | 40 | 1 | none |
| `bard.py:91` | `_TravelersCallRule` | 39 | 1 | `__init__` copies constants |
| `vladimir.py:74` | `_TidesOfBloodChargeRule` | 37 | 1 | none |
| `senna.py:65` | `_MistRule` | 34 | 1 | `__init__` copies constants |

Every one is instantiated once at module level, and one reader calls its
`public_receipt()`. `zeri._LivingBatteryExecuteRule` has no `__init__` and no
fields, so `public_receipt` returns a constant dict literal and the class is
ceremony around that dict. `senna._MistRule.__init__` assigns five module
constants onto `self`, and `public_receipt` reads them back.

`public_receipt()` is a real house convention in `cleanse_eligibility.py`,
`crowd_control_eligibility.py` and `defense_composition.py`. There it sits on
frozen dataclasses with fields and several readers. Here it is a one-call
accessor. For the four stateless classes, a module-level
`SENNA_MIST_RECEIPT: Mapping[str, Any]` cuts about 190 lines to 60. For the rest,
a frozen `NamedTuple` plus one shared `state_receipt(name, rule)` does it.

## 2. Helper reinvention

| Reinvented | Home that exists | Adopters | Hold-outs |
|---|---|---|---|
| cached-prose regex | `ability_prose.CachedSentence` | 12 modules | 25 modules, 56 `re.*` sites |
| own-slot `ability` guard | none yet, `@ranked_slot` is the shape | 124 files use `@ranked_slot` | 110 `ability` sites |
| `no_damage` wrapper | `module_helpers.no_damage_slot` | 13 | 17 |
| level brackets | `module_helpers.at_level` | 11 | 6 |
| typed event-row reads | `damage_event_row`, `heal_event_row`, `cast_event_row` | 0 champion modules | 69 `.get(key, literal)` sites in 41 modules |
| entry dict | `slot_entries.damage_entry` at 219 uses, `on_hit_entry` at 22 | | 82 literals |
| cast time | `slot_extract.extract_cast_time` | 10 files touch `castTime` | 9 literals that equal the cache |
| `effects[].description` walk | `ability_prose.effect_description` | | 20 sites in 18 files |
| `["leveling"]` walk | `slot_extract`, which architecture.md calls the one such walk | | 10 sites in 10 files |

### CachedSentence is a half-finished migration with a correctness tail

`TRAPS.md` records that six modules folded into
`ability_prose.CachedSentence(pattern, missing)` so the clone group would
dissolve. Twelve modules use it now. Twenty-five do not. Of those 25, 22 raise on
a reworded cache and 7 degrade silently:

```
akshan.py:84 _extract_e_per_shot          akshan.py:107 unusual_unit
akshan.py:135 _parse_passive_proc_damage  chogath.py:89 _vorpal_spikes
chogath.py:106 _stack_rider               sett.py:310 derive_self_healing
taric.py:263 _starlights_touch
```

`sett.py:328` is the representative case. It runs two `re.search` calls and then
`if base_match is None or max_match is None: return []`. A wiki rewording
silently zeroes Sett's whole passive regeneration, and the fight publishes a
`MEASURED` zero. `CachedSentence.match` raises `ValueError(self.missing)`, which
is the reason the type exists. Fix these 7 first.

### at_level reinvented six ways

`module_helpers.at_level` at line 482 is five lines. The hand-rolls:

- `jayce.py:147 _level_tier` and `miss_fortune.py:72 _love_tap_tier`. The
  clone detector groups these two as identical bodies.
- `sett.py:297 _level_breakpoint_value`.
- `xayah.py:118`, an inline `for min_level, index in _CLEAN_CUTS_LEVEL_BRACKETS`
  loop over a bracket tuple declared at `xayah.py:69`. That is `at_level` typed out.
- `graves.py:22 _level_scaling`.
- `akshan.py:169` through `akshan.py:173`, a five-deep `if level >= N` chain.

### Two functions named event_source, reading different keys

`healing_helpers.py:98` reads `event.get("source_key", "")`, returns silently,
and carries no docstring. `damage_event_row.py:71` reads
`_required(event, "source")` and raises.

They read different row shapes. The engine's reconstructed rows carry
`source_key`, built at `fight/ledger/event_rows.py:138`, and the published
breakdown rows carry `source`. So this is not a bug today. It is one name, two
homes, two failure modes, and the undocumented one wins on a typo. Rename the
healing one `ledger_source_key`.

## 3. Contract style

Declaration spelling is near-uniform. Module-level uppercase declarations
appearing in three or more modules:

```
MODULE_CC 173   ASSUMPTIONS 162   OPTIONS 139   SLOTS 98   SOURCES 97
PACKET_SHA256 76   MODULE_COVERAGE 74   SELF_HEALING_RULE 62
CHARGE_RULES 20   COVERAGE_CHANNELS 16   CAST_ORDER 6   CAST_DEPENDENCIES 3
ULTIMATE_RECASTS 1   MODULE_STAT_CONVERSION 1
```

- `SOURCES`: 97 of 97 spelled `load_champion_sources("Name")`. One spelling.
- `MODULE_COVERAGE`: 74 of 74 spelled `coverage(...)`. Zero dict literals.
- Zero modules declare a `MODULE_COVERAGE` equal to the derivation. The six
  no-argument `coverage()` calls all sit in packet modules whose `SLOTS` is an
  override map, so the derivation would be wrong there. Each is a real statement.
- Two parser lanes, both consistent. 100 modules call
  `build_parser(SLOTS, "Name", cc_kinds=MODULE_CC)`. 76 of 77 packet modules
  write `parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(...)`.
- `MODULE_CC` is the one drift. 159 dicts carry real kinds. 10 write a full
  all-`"none"` dict literal, in `akshan`, `ezreal`, `garen`, `kaisa`, `katarina`,
  `lucian`, `master_yi`, `nidalee`, `sivir` and `zed`. One writes
  `dict.fromkeys(SLOTS, "none")` at `corki.py:415`. Same fact, two spellings.

### The one real two-homes problem: _ROTATION_CLASSIFICATIONS

`champions/__init__.py:579` holds a 385-line table of 253 rows keyed by option
name. `get_champion_option_rotation` at line 970 reads an inline `rotation=` dict
off the OPTIONS row first and falls back to the table. So one fact, what an
option does to the rotation, has two homes, and 37 options in 31 modules already
use the inline form.

The table key is not unique. 29 option keys are declared by more than one module,
covering 86 declarations: `passive_procs` seven times, `w_active` seven,
`q_variant` five, `q_secondary_targets` four, and `e_active`, `e_active_from`,
`e_active_seconds` three each. The table carries a `"slot": {champion: ...}`
escape hatch for those collisions. Four rows match no declared option anywhere
and are dead: `overheat_autos`, `p_backstab`, `p_notes_fired`, `r_variant`.

Proposal: codemod every table row onto its declaring OPTIONS entry as
`rotation={...}`, then delete the table and the fallback branch. Net line change
is near zero, but the collision hatch and the four dead rows go, and the
`add-champion` step "classify every option in `_ROTATION_CLASSIFICATIONS`"
becomes "declare it on the option", which one grep resolves.

## 4. Options never read

Zero. All 313 `*_option(...)` declarations resolve to a read somewhere in `src/`.
The split is 163 int, 106 bool, 44 float, or 362 counting dict-literal rows. My
first pass flagged 41, and every one reads outside the declaring module. That
cross-module reading deserves its own name:

- `projectile_defense.py:128` reads `f"{key}_active_from"` and
  `f"{key}_active_seconds"` by string convention across Fiora, Gwen, Jax,
  Pantheon, Samira and Braum.
- `interaction_atoms.py:97` through line 135 hard-code `"w_blocked_skillshots"`
  and `"e_blocked_sources"` as option-name strings.
- `aphelios_weapons.py` reads four `aphelios_*_points` keys.

That is a naming contract with no type. It works, but renaming an option in a
champion module fails at runtime rather than at import. A `declared_by` field on
the OPTIONS row, or a module-side constant the reader imports, closes it.

Related counts:

- Options with `minimum == maximum`, which would be a constant wearing an
  option's clothes: zero.
- Option defaults restated as a bare literal elsewhere in the same module: 46.
  Examples: `braum.py:313 e_active_from=0.0` where the literal `0.0` appears ten
  times, `corki.py:340 w_patch_uptime=1.0` six times, `fiddlesticks.py:168
  r_ticks=20` three times, `annie.py:367 tibbers_aura_seconds=5.0` three times.
  Most are `0.0` sentinels and harmless. `r_ticks=20` and
  `tibbers_aura_seconds=5.0` are two homes for one number.

## 5. Docstring and comment bloat

Measured over the 174 champion modules, 49,001 lines:

| Kind | Lines | Share |
|---|---|---|
| module docstrings | 4,700 | 9.6% |
| function docstrings | 2,379 | 4.9% |
| comment lines | 5,072 | 10.4% |
| prose total | 12,151 | 24.8% |
| imports | 2,432 | 5.0% |
| declaration blocks | 7,997 | 16.3% |

69 modules carry a module docstring over 30 lines, 3,062 lines in total. The
worst:

```
naafiri.py 125   rumble.py 100   sylas.py 99   twitch.py 83   sivir.py 75
seraphine.py 75  jayce.py 75     anivia.py 62  yuumi.py 60    tristana.py 60
aurelion_sol.py 57  rammus.py 53  kaisa.py 51  shen.py 48     warwick.py 47
```

`naafiri.py` is the archetype. It opens with
`"""Naafiri, CP10.5 full-entry-reviewed packet module (E2/E9-2 fixes)."""`, then
narrates `E2 DoT fix:` and `E9-2 gap fixes:`, which the house rule forbids
outright. It then carries 60 lines of load-bearing trap knowledge: the game-file
slot labels swap W and R. That trap belongs in `TRAPS.md`, where the next session
reads it without opening Naafiri, and the module needs a two-line pointer to it.
`rumble.py`, `sylas.py` and `gnar.py` share the shape.

Docstrings longer than their function body: zero. The per-function discipline
holds. The module headers are what ran away.

History narration:

| Pattern | Lines | Files | Examples |
|---|---|---|---|
| campaign and phase ids such as `E9-2 fix`, `P4-14`, `D-24`, `CF9`, `batch C`, `roadmap`, `session 4` | 101 | 67 | `aatrox.py:25`, `akshan.py:31`, `anivia.py:13`, `__init__.py:581` |
| history words such as `previously`, `no longer`, `retired`, `was priced` | 45 | 36 | `ambessa.py:151`, `annie.py:242`, `galio.py:42` |
| a `CP10.x` patch label on the docstring's first line | 95 | 84 | |

The patch labels are their own drift signal. The tree carries nine review stamps:
CP10.3 thirteen times, CP10.4 fifteen, CP10.5 nine, CP10.6 thirteen, CP10.7
fourteen, CP10.8 nine, CP10.9 nine, CP10.10 eleven, CP10.11 twice. Either 84
modules are stale against the current patch, or nobody maintains the label.
Either way a docstring should not own that fact. `SOURCES`, through
`source_receipts.load_champion_sources`, already carries the reviewed revision.

`ASSUMPTIONS` holds 162 blocks, 3,606 lines, 769 strings and 194,041 characters.
That averages 252 characters per assumption. The largest blocks are `sivir.py` at
93 lines, `jayce.py` at 85, `rumble.py` at 77, `darius.py` at 62 and `mel.py` at
61. The median block is 19 lines.

The API publishes these strings, so they cannot simply go. But 252 characters is
an essay. Kog'Maw's fourth assumption spends 191 characters saying the Living
Artillery stack cost has no damage impact. A 120-character cap in
`scripts/prose_lint.py` roughly halves the block, about 900 lines, and makes the
published list readable.

Receipt and citation blocks repeated in both a docstring and a constant: zero
modules cite the same wiki revision id twice.

## 6. Per-module constants that are data

101 modules hold 326 module-level numeric literals. 204 carry a `# HARDCODED`,
`sourced`, `wiki` or `binary` note within eight lines. 122 carry no provenance
note at all. 64 modules hold 70 explicit
`# HARDCODED: verify on patch updates` blocks, so the convention is real and
mostly followed.

The proven violations are cast times. `data/champions.json` carries `castTime`
per ability, and `slot_extract.extract_cast_time` reads it. Nine constants
restate it exactly:

```
ambessa.py:274 _R_CAST_TIME_S=0.7     galio.py:23 _Q_CAST_TIME=0.25
galio.py:31 _E_CAST_TIME=0.4          karthus.py:31 _W_CAST_TIME=0.25
karthus.py:32 _Q_CAST_TIME=0.25       karthus.py:43 _R_CAST_TIME=0.25
taliyah.py:49 _W_CAST_START=0.25      taliyah.py:55 _Q_CAST_TIME=0.25
vi.py:68 _R_CAST_TIME=0.25
```

Six more `*_CAST_TIME` constants deliberately differ from the cache, at
`darius.py:83` through `darius.py:85`, `brand.py:62`, `taliyah.py:48` and
`taliyah.py:50`. Those are composites carrying a wind-up or an offset, which is
fine, but none says so beside the number.

Adoption of the sourced path is good. 113 of 174 modules import `binary_roots`
for `spell_object`, `data_value` and `calculation_constant`. 57 modules import
neither `binary_roots` nor `ability_prose`, and those are the frontier where an
unsourced literal can hide.

### Marker counts

| Marker | Count | Breakdown |
|---|---|---|
| `# pylint: disable` | 67 comments, 209 rule tokens | `too-many-arguments` 59, `too-many-positional-arguments` 59, `unused-argument` 52, `too-many-locals` 39, plus one each of `no-value-for-parameter` at `fiddlesticks.py:74`, `too-many-branches` and `too-many-statements` at `maokai.py:159`, and `duplicate-code` at `yone.py:22` for Yone mirroring Yasuo |
| `# sightline-ok` | 3 | all reading `": 32 - module_contract reads it by name"` |
| `# noqa` | 0 | |

53 of the 67 `too-many-arguments` disables sit on `derive_self_healing`. That is
not 53 messy functions. It is one contract shape charged 53 times. Finding 1
covers it.

## 7. Overbuilt shapes

| Shape | Count | Verdict |
|---|---|---|
| functions over 100 lines | 3 | `briar.py:243 _chilling_scream` at 151, `briar.py:531 derive_self_healing` at 117, `maokai.py:160 derive_self_healing` at 113 |
| functions over 60 lines | 45 | acceptable for a two-form kit. The healing resolvers dominate |
| closure nesting of 3 or more | 6 | three in helpers, at `healing_contract.self_healing_rule`, `module_helpers.with_detail` and `packet_parsers._packet_parser`, all decorator factories and correct. Three in champions, at `teemo.py:123`, `udyr.py:187`, `zilean.py:49` |
| NamedTuple, dataclass or Enum in a champion module | 11 | ten are the single-use rule classes above. `rengar.py:201 _FerocityBranch` is a seven-field NamedTuple with four uses and is legitimate |
| mutable default arguments | 0 | |
| builtin-shadowing parameters | 0 | |

### Top 15 champion modules by total length

| Module | Total | Module doc | Fn doc | Comments | Imports | Declarations | Formula | Judgement |
|---|---|---|---|---|---|---|---|---|
| kaisa.py | 704 | 51 | 55 | 39 | 20 | 96 | 443 | earns it, evolutions across three slots |
| briar.py | 651 | 37 | 45 | 78 | 20 | 80 | 391 | the 151-line `_chilling_scream` should split by charge phase |
| vi.py | 638 | 25 | 46 | 31 | 16 | 86 | 434 | earns it |
| kindred.py | 623 | 46 | 41 | 48 | 23 | 65 | 400 | earns it |
| jayce.py | 618 | 75 | 71 | 70 | 19 | 109 | 274 | 344 lines of prose and declarations against 274 of formula |
| darius.py | 570 | 32 | 55 | 72 | 21 | 101 | 289 | 13 module constants plus a bleed ledger |
| mel.py | 566 | 44 | 60 | 54 | 24 | 85 | 299 | borderline |
| naafiri.py | 552 | 125 | 17 | 54 | 12 | 73 | 271 | the docstring is 23% of the file |
| dr_mundo.py | 527 | 36 | 47 | 92 | 14 | 85 | 253 | comments are 17% |
| aphelios.py | 512 | 34 | 19 | 78 | 28 | 64 | 289 | five weapons, earns it |
| rumble.py | 497 | 100 | 41 | 47 | 17 | 79 | 213 | the docstring is 20% against 213 of formula |
| syndra.py | 485 | 39 | 45 | 61 | 20 | 120 | 200 | declarations exceed formula by 60% |
| aurelion_sol.py | 481 | 57 | 25 | 58 | 20 | 102 | 219 | Stardust already split to a leaf |
| vladimir.py | 477 | 21 | 25 | 58 | 17 | 53 | 303 | two stateless rule classes, 94 lines |
| sivir.py | 468 | 75 | 36 | 36 | 18 | 96 | 207 | a 93-line `ASSUMPTIONS` |

### Top by longest single function

```
151 briar.py:243 _chilling_scream        117 briar.py:531 derive_self_healing
113 maokai.py:160 derive_self_healing     86 vladimir.py:179 _tides_of_blood
 86 shen.py:165 _twilight_assault         84 darius.py:307 _noxian_guillotine
 82 braum.py:114 _concussive_blows        81 varus.py:166 _piercing_arrow
 79 talon.py:50 _blades_end               79 kindred.py:332 _hunters_vigor
 77 aphelios.py:432 derive_self_healing   77 aphelios.py:114 _q
 76 dr_mundo.py:448 derive_self_healing   75 udyr.py:107 _wilding_claw
 75 shyvana.py:163 _inferno_aegis
```

Five of the fifteen are `derive_self_healing`. That is the function in the tree
most in need of a shape, and finding 1 is the shape.

## 8. Beginner-grade Python

Almost none. The full census over the 174 champion modules:

| Pattern | Hits |
|---|---|
| `len(x) == 0`, `> 0`, `!= 0` | 0 |
| `for i in range(len(x))` | 2, at `jayce.py:386` and `sett.py:303` |
| chained `.get(k, d).get(...)` | 2, at `aphelios.py:447` and `ziggs.py:85` |
| `x += "str"` in a loop | 4, at `aphelios.py:293`, `aphelios.py:297`, `shyvana.py:194` |
| append in a loop where a comprehension fits | 2, at `kaisa.py:222` and `kindred.py:606` |
| `== True`, `== False`, `type(x) ==`, `.keys():` | 0 |
| mutable defaults | 0 |
| boolean-flag parameters | 1 |
| builtin shadowing | 0 |

The one systemic `.get(key, literal)` population is the 69 sites inside
`derive_self_healing`. `scripts/behavior_frontier.py` already pins those as
`produced_fallbacks_by_receiver`, 13 receivers with `event` at 46, `cast` at 13
and `entry` at 13, while `forbidden_input_fallbacks` holds at 0. The guard works.
Nobody has paid the frontier down, and the three typed readers built for it,
`damage_event_row.py`, `heal_event_row.py` and `cast_event_row.py`, have eight
consumers elsewhere in `src/` and zero in the champion tree.

`inputs.py` deserves credit here. It retired about 370 literal-fallback call
sites and the guard holds at zero.

## 9. Registry and contract overhead

Measured on the ten median-sized modules by total lines:

| Module | Total | Module doc | Imports | Declarations | Comments | Formula | Boilerplate |
|---|---|---|---|---|---|---|---|
| aurora.py | 248 | 35 | 12 | 49 | 30 | 122 | 39% |
| ivern.py | 250 | 1 | 15 | 67 | 38 | 129 | 33% |
| anivia.py | 251 | 62 | 12 | 39 | 51 | 87 | 45% |
| brand.py | 251 | 22 | 17 | 57 | 45 | 110 | 38% |
| zeri.py | 253 | 15 | 8 | 15 | 31 | 184 | 15% |
| vex.py | 257 | 34 | 10 | 33 | 31 | 149 | 30% |
| olaf.py | 258 | 30 | 16 | 39 | 37 | 136 | 33% |
| smolder.py | 265 | 40 | 13 | 40 | 26 | 146 | 35% |
| wukong.py | 265 | 44 | 18 | 58 | 27 | 118 | 45% |
| galio.py | 267 | 8 | 11 | 54 | 8 | 186 | 27% |

Tree-wide the split is 30.9% boilerplate, counting docstring plus imports plus
declaration blocks, and 24.8% prose, leaving about 44% champion formula.

What a slimmer contract drops, in payoff order:

**1. The `derive_self_healing` signature, about 420 lines.** All 60 resolvers
share one signature of eight lines, and 113 of the 360 parameters go unread. The
distribution of parameters actually used is: one parameter in 2 modules, two in
7, three in 8, four in 17, five in 17, six in 9. Exactly one call site exists,
`healing_contract.ChampionHealingRule.derive` at line 38, so:

```python
@dataclass(frozen=True, slots=True)
class SelfHealCtx:
    champion_data: dict
    champion_stats: dict
    ability_damages: dict
    damage_events: list
    cast_timeline: list | None = None
    fight_duration_seconds: float | None = None
```

turns 60 eight-line signatures into 60 one-liners and deletes 53
`# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals`
comments. The codemod is mechanical: the resolver bodies need a `ctx.` prefix on
six names, which is an exact-string rewrite.

One aside found on the way. The receipts sort twice. `self_healing_rule`'s
`ordered` wrapper in `healing_contract.py:78` sorts by `heal_receipt_order`, and
`healing.derive_self_healing` at line 98 sorts the result again by the same key.
The `healing_contract` docstring says the declaration owns the receipt order, so
one of the two sorts is dead.

**2. The module docstring, about 1,680 lines.** Cap at 20 lines holding what each
slot is and why it is not generic. Traps go to `TRAPS.md`, patch labels to
`SOURCES`, campaign ids to the bin.

**3. `ASSUMPTIONS`, about 900 lines.** Cap each string at 120 characters.

**4. The guard decorator, about 160 lines, and `no_damage_slot`, about 160 lines.**

**5. `_ROTATION_CLASSIFICATIONS`, 385 lines relocated and 4 rows deleted.**

What should stay: `PACKET_SHA256`, `MODULE_CC`, `SOURCES` and `MODULE_COVERAGE`.
Each runs one line to ten, each fails closed, and the census shows zero spelling
drift across 174 modules. That part of the contract carries its weight.

## Codemods worth writing

Each of these touches more than ten modules, so each gets a script.

| Codemod | Modules | Mechanism |
|---|---|---|
| `SelfHealCtx` signature rewrite | 60 | AST rewrite of the `FunctionDef` args, prefix the six parameter names in the body, drop the pylint comment, plus one edit in `healing_contract.py` |
| `@ability_slot` guard removal | 95 | AST match on `x = ctx.ability(...)` plus `if x is None: return None` as the first two statements, hoisted to a decorator |
| docstring cap and history strip | 69 | regex over the module docstring. The trap text needs a human to route it to `TRAPS.md` |
| inline `rotation=` move | 129 | AST read of `_ROTATION_CLASSIFICATIONS[key]`, inserted as a keyword on the matching `*_option(` call |
| `CachedSentence` migration | 25 | per module, the 7 silent readers first |
| `no_damage_slot` collapse | 17 | AST replace of the wrapper `FunctionDef` with a `SLOTS` entry |
| `damage_entry(parts=...)` | 27 | AST dict literal to call, after the helper gains `parts=` and `detail=` |
| `at_level` | 6 | by hand |
| `extract_cast_time` | 5 files, 9 constants | by hand |

Every codemod above runs `black`, then `pylint src/`, then both golden compares,
`golden_baseline.json` and `golden_coupled_baseline.json`. Two traps from
`CLAUDE.md` bear directly on this work.

Compiled slot order is Q, W, E, R, P, and the ledger replays insertion order for
float sums. A decorator that changes when a slot parser binds, or a `SLOTS` dict
whose key order moves, is a numeric change. The `no_damage_slot` collapse and the
`@ability_slot` rewrite both touch this.

A published zero's type is load-bearing. The `damage_entry` conversion must not
turn an `int` 0 into a `float` 0.0 on any leaf.

Run the codemods one at a time, with a green golden compare between each, never
batched.
