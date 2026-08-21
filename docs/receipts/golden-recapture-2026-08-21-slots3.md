# Golden recapture — roadmap slot session 3 wave 1, 2026-08-21

Champions: Alistar, Anivia, Aurelion Sol, Kalista.

Pre-recapture compare: **57 diffs**, partitioned exactly
**0 Alistar + 17 Anivia + 22 Aurelion Sol + 18 Kalista**, zero unattributed.

Of the 57, **53 are structural zero-damage rows** (a slot reclassified from
`out_of_scope` to `no_damage` now emits a user-visible zero row instead of
staying silently absent) and **4 are real value moves**, all four on Aurelion
Sol's magic build and all four attributed to one cast-schedule effect below.

---

## Alistar (0 diffs)

Metadata-only. P (Triumphant Roar) reclassified `out_of_scope -> modeled`:
the 5%-max-health self-heal was already wired through `SELF_HEALING_RULE` and
live-tested; `MODULE_COVERAGE` was simply a stale label. `SLOTS` is unchanged,
so no parse row and no fight row moved. R (Unbreakable Will) stays
`out_of_scope` with a named structural-blocker receipt in the module docstring.

**Expected golden impact: none. Observed: none.**

---

## Anivia (17 diffs) — attributed by the parallel stream, re-verified here

W (Crystallize) reclassified `out_of_scope -> no_damage`; P (Rebirth)
reclassified `out_of_scope -> modeled` (metadata only — the revive kernel
already closed it).

- 1 × `/champion_baselines/Anivia/abilities_level_11/W`: `<absent> -> {…}`
  (cooldown 17.0, cast_time 0.25, the knockback-wall detail; `total_raw` 0.0)
- 16 × `/registered_champion_fights/Anivia/{11,18}/{burst,sustained}/{4 builds}/breakdown_totals/W`:
  `<absent> -> 0.0`

**Zero `total_damage` diffs for Anivia in all 16 scenarios** — the new W cast
changed no proc count and crossed no threshold.

---

## Aurelion Sol (22 diffs)

P (Cosmic Creator) and W (Astral Flight) reclassified
`out_of_scope -> no_damage`.

### Structural zero rows (18)

- `/champion_baselines/AurelionSol/abilities_level_11/passive`: `<absent> -> {…}`
  (cooldown 0.0, `total_raw` 0.0, the Stardust-counter detail)
- `/champion_baselines/AurelionSol/abilities_level_11/W`: `<absent> -> {…}`
  (cooldown 22.0, cast_time 0.4, `total_raw` 0.0)
- 16 × `/registered_champion_fights/Aurelion Sol/{11,18}/…/breakdown_totals/W`:
  `<absent> -> 0.0`

P produces **no** fight-breakdown row because `P` is not in
`damage.DEFAULT_CAST_ORDER = ("Q","Q2","W","E","R")` — only the parse surface
carries it. W is in that tuple, so it books a cast.

Both rows are correctly rank-gated by `module_helpers.no_damage`
(returns `None` below rank 1): observed W absent at level 1, present from
level 5. P is level-gated and present from level 1.

### The 4 real value moves — one root cause

```
/registered_champion_fights/Aurelion Sol/11/sustained/magic_build/breakdown_totals/shadowflame_Shadowflame: 418.39 -> 417.27
/registered_champion_fights/Aurelion Sol/11/sustained/magic_build/total_damage:                            3825.91 -> 3824.79
/registered_champion_fights/Aurelion Sol/18/sustained/magic_build/breakdown_totals/shadowflame_Shadowflame: 428.12 -> 431.44
/registered_champion_fights/Aurelion Sol/18/sustained/magic_build/total_damage:                            4007.64 -> 4010.96
```

**Verdict: legitimate, cast-schedule-driven — the same class as Bard's
session-1 spellblade `1 -> 2`. No damage is invented, re-multiplied or
double-counted; the per-event amplifier values are byte-identical on both
sides and only *which* events sat past Cinderbloom's HP threshold changed.**

#### Why the schedule moved

W now books a cast, and every value it books is read from the cache
(`data/champions.json` AurelionSol W): `castTime "0.4 • None"` → 0.4 s,
`cost` rank 1 = 50 mana, `cooldown` rank 1 = 22.0 s.

```
cast_timeline, level 11, magic_build, sustained
before:  Q@0.00 (13.75 mana)              E@0.00 (90)  R@0.20 (100)
after:   Q@0.00 (13.75 mana)  W@0.00 (50) E@0.40 (90)  R@0.60 (100)
```

Each cast starts after the previous cast's `cast_time`; W's sourced 0.4 s
pushes E and R back by exactly 0.4 s. **No slot is booked twice** — four
distinct `cast_id`s `Q:1 W:1 E:1 R:1`.

#### Why a pure timing shift moves Shadowflame

Shadowflame's Cinderbloom is a **threshold** amp, not a per-cast proc:
`_calculate_shadowflame_bonus` walks the ordered damage ledger and, once the
target's modeled HP drops below 40% of maximum, grants +20% to every
*subsequent* magic/true instance. Delaying E and R by 0.4 s reorders the
ledger around that crossing, so a different set of ticks lands on the amplified
side.

#### Level 11 — exact arithmetic

Per-event amp values, **identical before and after**: Q beam tick `6.9620`,
Q burst `37.2160`, E tick `2.9216`.

| amplified event | per-event | before | after | Δ count | Δ damage |
|---|---:|---:|---:|---:|---:|
| Q beam tick | 6.9620 | 32 | 31 | −1 | −6.9620 |
| Q burst | 37.2160 | 4 | 4 | 0 | 0 |
| E tick | 2.9216 | 16 | 18 | +2 | +5.8432 |
| **total** | | **52** | **53** | **+1** | **−1.1188** |

```
418.3936 − 1.1188 = 417.2748   → 418.39 -> 417.27  ✓
3825.9136 − 1.1188 = 3824.7948 → 3825.91 -> 3824.79 ✓
```

#### Level 18 — exact arithmetic

Per-event amp values: Q beam tick `6.9620`, Q burst `37.2160`, E tick `3.3216`.

| amplified event | per-event | before | after | Δ count | Δ damage |
|---|---:|---:|---:|---:|---:|
| Q beam tick | 6.9620 | 32 | 32 | 0 | 0 |
| Q burst | 37.2160 | 4 | 4 | 0 | 0 |
| E tick | 3.3216 | 17 | 18 | +1 | +3.3216 |
| **total** | | **53** | **54** | **+1** | **+3.3216** |

```
428.1152 + 3.3216 = 431.4368   → 428.12 -> 431.44  ✓
4007.6352 + 3.3216 = 4010.9568 → 4007.64 -> 4010.96 ✓
```

The two levels move in **opposite directions** (−1.12 at 11, +3.32 at 18) —
the signature of a threshold re-crossing, not of a systematic over- or
under-count.

#### Why it cannot be a double-count

1. **Ability rows are untouched.** `Q 2322.8`, `E 292.16`, `R 465.2`,
   `auto_attacks 172.0`, `proc_Luden's Echo 155.36` are byte-identical before
   and after at level 11 (and the level-18 equivalents likewise). Only the
   amplifier row moved.
2. **Per-event amp values are identical** on both sides (`2.9216 / 6.9620 /
   37.2160` at L11). Nothing was re-multiplied — only the count of amplified
   events changed, by +1 net at each level.
3. **W's own row is 0.0** in all 16 scenarios, asserted explicitly in
   `tests/test_aurelion_sol_stardust.py::TestDefaultAbsentParity::test_golden_registered_surface_recomputes_byte_identical`.
4. **The other three builds are byte-identical.** `no_items`, `physical_build`
   and `spellblade_build` show only the structural `W: 0.0` row and **zero**
   `total_damage` diffs — Shadowflame is the only item in the golden matrix
   with an HP-threshold amp, so it is the only one that can respond to a pure
   reorder. In particular the spellblade build does **not** move: ASol already
   booked 3 casts, so the added 4th cast cannot raise a proc count already
   capped by Sheen's `1.5 s cooldown + 1.5 s weave` over a 5 s fight.

#### Side finding — the change is a *fix*, not only a reclassification

At HEAD the `w_active` option raised Q from `2322.8` to `2356.4` while booking
**no W cast at all** — the Astral Flight beam buff was granted for free, with
no cast time and no mana. With W in `SLOTS` the buff now pays its sourced
0.4 s cast and 50 mana. Verified end to end:

```
HEAD   w_active=True : Q 2356.4, casts [Q@0.0, E@0.0, R@0.2]            ← buff free
after  w_active=True : Q 2356.4, casts [Q@0.0, W@0.0(50 mana), E@0.4, R@0.6]
```

#### Documented pre-existing boundary (not introduced here)

With E cast at 0.4 s instead of 0.0 s, 2 of E's 20 ticks now fall at 5.15 s and
5.40 s — past the nominal 5.0 s `ONE_ROTATION_DURATION` — and are still priced.
This is a long-standing committed engine contract, not a wave-1 regression: the
engine clamps *item procs* to the fight window (`_CAST_SCHEDULE_EPS` guards in
`damage.py`) but prices a cast ability's full authored tick schedule. A scan of
the committed HEAD baseline finds **15 of 173 registered golden champions
already carrying post-window ability ticks** — Nasus R to 15.5 s, Heimerdinger
Q to 14.0 s, Renekton R to 15.0 s, plus Cassiopeia, Darius, Evelynn,
Fiddlesticks, Galio, Gangplank, Karma, Rumble, Viktor and Yone. E's total is
unchanged at `292.16` (L11) / `332.16` (L18) on both sides. Recorded here as a
known boundary; closing it is an engine-wide change well outside this wave.

---

## Kalista (18 diffs)

P (Martial Poise) and R (Fate's Call) reclassified `out_of_scope -> no_damage`.

- `/champion_baselines/Kalista/abilities_level_11/passive`: `<absent> -> {…}`
  (cooldown 0.0, `total_raw` 0.0, windup-dash detail)
- `/champion_baselines/Kalista/abilities_level_11/R`: `<absent> -> {…}`
  (cooldown 140.0 = sourced rank-2 row `[160, 140, 120]`, `total_raw` 0.0)
- 16 × `/registered_champion_fights/Kalista/{11,18}/…/breakdown_totals/R`:
  `<absent> -> 0.0`

**Zero `total_damage` diffs for Kalista in all 16 scenarios.** R's cached
`castTime` is `none` → 0.0 s, so unlike ASol's W it delays nothing; and the
spellblade proc count was already cooldown-capped, not cast-capped.

### Consumer tests re-pinned — `tests/test_rotation_semantics.py`

`TestKalistaSoulMarkProc` expected `["Q","E"]` / `["Q","W","E"]`; both now
carry a trailing `"R"`.

**Verdict: correct new surface; re-pinned with a comment.** The resolver's base
order admits any slot with a parsed row regardless of damage —
`derive_champion_rule` filters on `isinstance(ability_damages.get(s), Mapping)`,
and `_fit_rule_to_fight` re-appends any base slot missing from the cached order.
The convention is already committed for five champions, each verified to carry
a zero-damage R in its derived level-11 order **before** this wave:

| champion | R coverage | derived L11 order |
|---|---|---|
| Bard | `no_damage` | `['Q','W','E','R']` |
| Tryndamere | `no_damage` | `['Q','W','E','R']` |
| Twisted Fate | `no_damage` | `['W','Q','E','R']` |
| Singed | `modeled`, 0 damage | `['R','Q','W','E']` |
| Olaf | `_rank_gated_no_damage` | `['Q','W','E','R']` |

Kalista's P does **not** enter the rotation, for the same reason ASol's P does
not: `P` is absent from `DEFAULT_CAST_ORDER`. R is correctly rank-gated —
observed order `['Q']` at level 1, `['Q','E']` at level 5, `['Q','E','R']` at
level 11, so an unlearnable R books no cast (matching Olaf R's
`_rank_gated_no_damage` contract).

Both tests pin W's **option-gating** semantics, which are unchanged: W is
absent without `soul_mark_proc` and present with it, and the receipt still
cites the option, on both cold and warm resolver caches.

### Consumer test re-pinned — `tests/test_aurelion_sol_stardust.py`

The wave's interim edit asserted `totals["W"] == 0.0` and then **stripped** the
W key before comparing to the golden, because the pre-recapture fixture had no
W key. With the fixture re-pinned that stopgap is removed: the explicit
zero-leak guard is kept, and the full totals — W row included — are compared
byte-identical. Nothing is stripped from the pin.

---

Recapture executed after this attribution; compare re-verified identical.
