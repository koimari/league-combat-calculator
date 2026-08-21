# Golden recapture — roadmap session 5 batch K, 2026-08-21

Champions: Rammus (P,E), Rumble (P,W), Seraphine (P,W), Sivir (P,R), Sylas (P,R).

Pre-recapture compare: **57 diffs, zero unattributed.**

| champion | baseline diffs | fight diffs | total | cause |
| --- | ---: | ---: | ---: | --- |
| Rammus | 5 | 42 | 47 | W phantom-proc fix (27.4 -> 0.0 zeroing) + P bonus-AD steroid (new) |
| Rumble | 4 | 0 | 4 | P Overheated on-hit closure (label + structural fields; default option 0) |
| Seraphine | 4 | 0 | 4 | P Note-damage closure (label + structural fields; default option 0) |
| Sylas | 2 | 0 | 2 | P Petricite Burst closure via `auto_attack_conversion` (default count 0) |
| Sivir | 0 | 0 | 0 | P label-only reclassification (parser already emitted zero rows) |

Attribution method: the diff itself is a full deterministic before/after
compare of a single working tree (batch K's uncommitted edits), so every
line is directly caused by one of the five named module changes — no
recapture-then-guess step was needed. Recapture was executed only after
this attribution was written and verified against the arithmetic below.

## 1. Rammus W (Defensive Ball Curl) — the 27.4 -> 0.0 verdict

**Verdict: sound fix, not a regression.** The old `27.4` was a phantom-proc
artifact of a floor bug, not a real sourced W damage number being dropped.

### The bug

`src/calculator/champions/rammus.py::_defensive_ball_curl` (pre-edit) built
the thorns damage part unconditionally:

```python
entry["parts"] = (DamagePart("magic", per_auto, count=max(autos, 1)),)
```

`autos` is the `w_thorns_autos` option — the count of enemy basic attacks
landing on Rammus during the stance, explicit state because the fight
engine has no incoming-auto hook (documented in the module's own header).
Its default value is `0` (no enemy autos land). `max(autos, 1)` floors
that to `1` regardless, so the module priced **one full thorns proc even
when zero enemies attacked Rammus** — a fight computed at the option's own
documented default silently charged for damage that, by that default,
never happened.

### The source (thorns is real, the zeroing is correct)

Cached wiki description (`data/champions.json` Rammus W, single effect
row): "enemies that use a basic attack on-hit against Rammus are dealt
15 (+ 10% total armor) (+ 10% total magic resistance) magic damage." This
is unchanged and still modeled — `_THORNS_BASE = 15.0`,
`_THORNS_ARMOR_RATIO = 0.10`, `_THORNS_MAGIC_RESISTANCE_RATIO = 0.10`, all
pre-existing constants untouched by this edit.

Live verification (level 11, no items, golden's own stat context —
`scripts.golden_snapshot.snapshot_champion_baselines`):

```
armor = 74.0, magic_resistance = 50.0
per_auto = 15 + 0.10*74.0 + 0.10*50.0 = 15 + 7.4 + 5.0 = 27.4
```

`w_thorns_autos=0` (default): `_defensive_ball_curl` now skips the
`entry["parts"]` override entirely, so `damage_entry`'s own single
zero-amount magic part stands -> `total_raw = 0.0`. Matches the diff:
`parts[0]: amount=27.4 -> amount=0.0`.

`w_thorns_autos=1` (real hit, verified live, not shown in golden since
golden runs default options): `total_raw = 27.4476...`, i.e. the exact
same sourced arithmetic still fires the moment a real auto is supplied.
The mechanic was not touched — only the phantom default-state proc was
removed. `tests/test_rammus_spiked_shell.py` pins both the zero-at-default
and the nonzero-at-`autos=1` cases (the "phantom-proc regression pin"
noted in the session log).

### Fight-row propagation (42 of the 47 Rammus diffs)

Every `registered_champion_fights` `W` breakdown row for Rammus (levels
11 and 18, all four builds, one-rotation and sustained) drops to `0.0` and
`total_damage` falls by exactly the removed W amount — the golden
fixture's default option state was never supplying a real enemy auto onto
Rammus, so removing the phantom floor removes exactly one full thorns
instance per fight row, nothing more and nothing less. No other Rammus
mechanic changed in this half of the diff.

## 2. Rammus P (Spiked Shell) — new closure, the other 5 baseline + 0 direct fight-row diffs, but the AD steroid also drives fight-row movement

P was `out_of_scope`; the packet declared `no_damage` (a stale label —
Spiked Shell is a self stat-conversion passive, not a thorns/reflect
mechanic, which is W). Cached description, `leveling: []` (empty array,
prose-only): "Rammus gains bonus attack damage equal to the sum of 15%
total armor and 15% total magic resistance." Corroborated by
`data/bin/characters/rammus.bin.json` `RammusP`: `ArmorRatio` /
`MagicResistRatio` = 0.15 at every rank index, and the spell's only
formula, `TotalDamage`, is exactly those two `StatByNamedDataValueCalculationPart`
terms — the binary's stray `BaseDamage` DataValue (10.0) is **not**
referenced by the formula and is correctly not modeled.

Live verification (level 11, golden's stat context, armor 74.0 / MR 50.0):

```
bonus_ad = 0.15*74.0 + 0.15*50.0 = 11.1 + 7.5 = 18.6
```

Matches the diff exactly: `detail: "+18.60 bonus attack damage: 15% total
armor (74.0) + 15% total magic resistance (50.0)"`, and
`stat_buff: {"bonus_attack_damage": 18.6}` (new field, previously absent).

Modeled as a BUFF-phase `stat_buff` on `bonus_attack_damage` (the
Dr. Mundo `_passive_bonus_ad` precedent), so it lands in `ctx.stats`
before autos/on-hit items read AD. This is why the 42 W-side fight-row
diffs also carry `auto_attacks` and `on_hit_Kraken Slayer` increases in
the *same* rows (e.g. level 11 sustained no-items `auto_attacks`
237.33 -> 286.93, `on_hit_Kraken Slayer` in the level-11/18 sustained
physical builds 132.14 -> 133.83 / 162.7 -> 165.66): both the W removal
and the P addition land in the same fight rows, and both are attributed
above — the auto/on-hit gains are the P steroid's flat +18.6/+level-18-
equivalent bonus AD flowing through every AD-scaling consumer in the
fight, not a third, unexplained mechanic.

Rammus E (Frenzying Taunt) was also reclassified `out_of_scope ->
no_damage` in this batch (stale label: the cached "Monster Magic Damage"
row is restricted by the wiki description to monsters, and this engine's
`target_class` has no monster value; the sourced taunt control event is
unaffected). Zero golden movement from E — it contributes none of the 47
Rammus diffs.

## 3. Rumble P (Junkyard Titan / Overheated) — 4 baseline diffs, 0 fight diffs

`out_of_scope -> modeled`. Cached: on-hit magic damage,
5:44.12(level) + 25% AP + 4% target max HP, corroborated by
`RumbleHeatSystem` in the binary (`TotalBaseDamage` ByCharLevel ladder,
`OverheatPercBonusDamage 0.04`). New option `overheat_autos` defaults to
`0` (fail-closed batch convention), so at golden's default options the
entry is a real sourced zero-damage row — `name` gains the `(Overheated)`
suffix, `rank` moves `0 -> 11` (previously state-only/unranked), `detail`
gains the sourced formula text, and a placeholder zero `parts[0]` appears
where none existed before. None of this touches `registered_champion_fights`
because the option is 0 there too — zero behavior change, only richer
metadata on an already-zero row. (Live non-default verification, from the
session log: `overheat_autos=1` at L20/AP200/target-maxHP2500 prices
194.12 = 44.12 + 50.00 + 100.00, matching the wiki and the binary exactly;
not exercised by golden.)

The separate `scaling.py` fix in this batch — the missing `"% of maximum
health"` alias in `_SIMPLE_UNITS` that was silently zeroing Rumble W's
4%-max-HP shield term (and Galio W's shield entirely, and Soraka W, which
has no runtime consumer) — produces **zero golden-visible diffs**, because
none of the three fixed rows are damage rows: Rumble W and Galio W are
support-scanner shields, priced through a separate ally-effects pipeline
that this golden snapshot does not capture. Verified live instead (session
log): Rumble W rank5/AP200/HP2000 scanner output moved from 205.0 to
285.0 (the missing 80.0 = 4% of 2000 restored), and Galio W from 0.0 to
270.0 (13.5% of 2000, previously computed as 0.0 entirely).

## 4. Seraphine P (Stage Presence / Notes) — 4 baseline diffs, 0 fight diffs

Same shape as Rumble P. `out_of_scope -> modeled`, option-gated
(`p_notes_fired`, default 0). Cached per-level "Bonus Magic Damage" row
4 -> 27.47 across levels 1-20 + 4% AP, corroborated by binary
`SeraphinePassive` (`AutoDamage` ByCharLevelInterpolation 4.0->25.0 +
`NoteAPRatio` 0.04 — exactly two `mFormulaParts`, pinned so no third term
can be invented later). `name` gains the `(Notes)` suffix, `rank` moves
`0 -> 11`, `detail` gains the sourced per-note formula text, placeholder
zero `parts[0]` appears. `notes=0` (default) -> `total_raw = 0.0`,
identical to the Rumble shape — zero fight-row movement. (Live non-default
verification, from the log: L18/AP200 per-note 33.00 = 25.00 + 8.00.)

## 5. Sylas P (Petricite Burst) — 2 baseline diffs, 0 fight diffs

`out_of_scope -> modeled`, but via a different kernel than Rumble/Seraphine:
`auto_attack_conversion` (the Galio Colossal Smash precedent), not an
additive on-hit row. The wave-0 draft plan (additive magic row) was
overturned mid-batch (session log) because Petricite Burst's cached ratio
is 130% AD + 30% AP — more than a full auto — and the cached note states
"Spellblade damage does NOT get converted to magic damage," i.e. the
*attack's own* damage converts; an additive row would have double-counted
a full phantom swing on top of the real one. `bonus_raw = 1.30*AD +
0.30*AP - AD = 0.30*AD + 0.30*AP` is supplied to the engine's existing
conversion channel, which mitigates `bonus_raw + swing_ad` as magic and
lets the ordinary swing path keep crits/AD scaling for the *unconverted*
swings. New option `passive_procs` (reusing Galio's registered option key)
defaults to `0`, clamped `0<=n<=3`. The two baseline diffs are the new
`auto_attack_conversion` field itself (`{"bonus_raw": 26.1, "count": 0,
"damage_type": "magic", "name": "Petricite Burst"}` at level 11, AD-only
context: `0.30 * 87.0 = 26.1`, AP=0) and the sourced `detail` text
replacing the stub. `count=0` means the engine's conversion path is a
true no-op (`converted_auto_limit = min(num_autos, count) = 0`), so zero
fight-row movement — verified live in the session log's mutation test
(reverting the conversion contract back to an additive read broke 14 of
52 new Sylas tests, concentrated exactly in the
`TestConversionNotBonusRow` family, proving the suite would have caught
the double-count regression the draft plan would have shipped).

## 6. Sivir P (Fleet of Foot) — 0 diffs

Pure label fix, `out_of_scope -> no_damage`. The parser already emitted
`total_raw=0.0, parts=()` for P before this edit (MS-only innate, no
damage formula ever existed in the packet or the cache) — `MODULE_COVERAGE`
was the only stale artifact, the Olaf-P shape. Sivir R (On the Hunt) stays
`out_of_scope` deliberately: two named unmodeled kernel gaps (percent
move-speed has no flat/percent decomposition available at fight time to
feed the one live MS consumer, `swiftmarch_adaptive_force`; the on-attack
cooldown refund has no ability-cooldown-refund channel) plus a source
conflict (`HuntAttackSpeed` exists in the binary at 5/6/7% but is absent
from the wiki text — not modeled either way, flagged as unsourced-conflict
rather than guessed). Zero golden movement, confirmed.

## Validation

- Per-slice: `.venv/bin/pytest -q -k "rammus or rumble or seraphine or sivir or sylas" --tb=short`
  — **249 passed, 8362 deselected.**
- Full suite: `.venv/bin/pytest -q --tb=no -rf` — **8611 passed, 0 failed.**
- `black --check src/ tests/ scripts/` — **600 files, all clean** (no
  reformatting needed; batch K's black pass already applied before this
  recapture).
- Golden: `scripts/golden_snapshot.py compare scripts/golden_baseline.json`
  pre-recapture — 57 diffs, all attributed above.
  `scripts/golden_snapshot.py capture scripts/golden_baseline.json` then
  `compare` — **`OK: snapshot identical to scripts/golden_baseline.json`.**

No assertions were weakened to reach these counts. Not committed per task
instruction.
