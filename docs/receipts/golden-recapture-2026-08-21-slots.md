# Golden diff attribution — 2026-08-21 slot-modeling streams (Taric P + Bard W/E/R)

Two roadmap-session-2 slot-modeling streams landed on the same dirty tree:

- **Taric P (Bravado)** — reclassified from a non-damaging/state row to a
  priced on-attack packet.
- **Bard W / E / R** — reclassified from `out_of_scope` (silently absent) to
  `no_damage` (explicit, user-visible zero-damage state rows).

Pre-recapture gate:

```bash
.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json
```

produced **77 differences** at 21:59 local. Every one is attributed below with
arithmetic. **0 unattributed paths.**

> **The recapture in this receipt was NOT performed.** See
> [Recapture status](#recapture-status--blocked) at the bottom: a third,
> concurrent stream (Kai'Sa) landed a golden-visible change mid-session, so a
> recapture taken now would bake an unaudited, still-in-flight row into the
> shared baseline. `scripts/golden_baseline.json` is deliberately left
> byte-identical to `HEAD`.

## Attribution summary — 77 paths, 0 unattributed

Assigned by path-shape classification of the full compare output (not
eyeballed); the categories partition the 77 lines exactly.

| # | Stream | Category | Paths |
| --- | --- | --- | --- |
| B1 | Bard | `champion_baselines/Bard/abilities_level_11/{W,E,R}` — new zero-damage rows | 3 |
| B2 | Bard | `registered_champion_fights/Bard/.../breakdown_totals/{W,E,R}` = `0.0` | 48 |
| B3 | Bard | `.../sustained/spellblade_build/breakdown_totals/spellblade_Trinity Force` | 2 |
| B4 | Bard | `.../sustained/spellblade_build/total_damage` (+1 proc) | 2 |
| T1 | Taric | `champion_baselines/Taric/abilities_level_11/passive/*` reshape | 6 |
| T2 | Taric | `registered_champion_fights/Taric/.../breakdown_totals/on_hit_ability_passive` | 8 |
| T3 | Taric | `registered_champion_fights/Taric/.../total_damage` | 8 |
| | | **Bard 55 + Taric 22 = total** | **77** |

B2's 48 = `2 levels × 2 fight modes × 4 builds × 3 slots`.

## Bard — per-slot disposition

`MODULE_COVERAGE` moved `W`/`E`/`R` from `out_of_scope` to `no_damage`. Each
slot now emits a `module_helpers.no_damage` row: `total_raw = 0.0`,
`parts = ()`, plus a sourced `detail` reason. This matches the pattern already
carried by **93** other registered champions in the current baseline (Braum,
Blitzcrank, Elise, Illaoi, …) — Bard was a holdout, not a new precedent.

| Slot | Ability | Sourced basis for zero enemy damage | Verified |
| --- | --- | --- | --- |
| W | Caretaker's Shrine | `data/champions.json` Bard W leveling carries only **Minimum Heal** `25/50/75/100/125 (+40% AP)`, **Maximum Heal** `50/87.5/125/162.5/200 (+70% AP)`, **Bonus Movement Speed** `20/22.5/25/27.5/30% (+6% per 100 AP)`. `damageType: null`. Ally-only heal. | yes — leveling arrays read from cache; the detail string's `25-125 / 40% AP` and `50-200 / 70% AP` endpoints match exactly |
| E | Magical Journey | All three effect rows carry `leveling: []`; `damageType: null`. Terrain portal. | yes |
| R | Tempered Fate | `damageType: null`, all effect rows `leveling: []`; the cached R **notes** state verbatim *"Tempered Fate deals 0 proc true damage, which triggers in-combat effects such as drawing turret and monster aggression, Sudden Impact or applying Elixir of Sorcery."* | yes — substring present in `data/champions.json` Bard R notes |

The W ally heal remains a **documented missing engine hook** (the support
scanner's heal-attribute lookup reads `Total Heal` / `Heal` / `Heal Per Tick`
and cannot see `Minimum Heal` / `Maximum Heal`) — unchanged by this stream, now
stated on a visible row instead of an invisible absence.

### Why the zero rows change any number at all

Being present in `ability_damages` puts W/E/R on the shared timed-cast
timeline. In the snapshot's sustained scenario (5.0s, `auto_attack_uptime=1.0`)
they cast once each:

```
cast_events: Q@0.00  W@0.25  E@0.50  R@0.75      (cast_time 0.25/0.25/0.25/0.50)
total_ability_casts: 1 -> 4
```

W's cached `cooldown` is `null` (Bard W is charge-based: `rechargeRate 18`,
max 2 stocked charges), so `extract_cooldown` yields `0.0` and the scheduler's
pre-existing rule `single_cast = {R} ∪ {cooldown <= 0}` casts it **exactly
once**. No recast spam is possible, and the model under-counts rather than
over-counts (in-game, 2 stocked charges could both be spent in 5s).

Zero-damage casts add **no damage of their own** — every non-spellblade build's
`total_damage` is byte-identical, and Bard's `Q` / `auto_attacks` /
`on_hit_ability_passive` rows are untouched in all 8 scenarios.

## Red flag resolved — `spellblade_Trinity Force` doubling is NOT a double-count

Observed: `137.33 -> 274.67` (L18) and `104.0 -> 208.0` (L11), both exactly ×2.

**Verdict: legitimate, cast-schedule-driven. Per-proc damage is unchanged; the
proc *count* went 1 → 2.**

### Sourced rule

`data/items.json` Trinity Force → Spellblade (via `item_source.effect_text`):

> After using an **ability**, your next basic attack within 10 seconds deals
> **200% base AD** bonus physical damage on-hit (1.5 second cooldown, starts
> after using the empowered attack).

"After using an ability" — no damage requirement. `item_effects.py` encodes
`base_ad_ratio 2.0`, `cooldown 1.5`, `weave_delay 1.5` (CD starts after the
empowered attack), matching the text.

### Per-proc arithmetic (unchanged before and after)

Target armor 50 → physical multiplier `100/(100+50) = 2/3`. No armor pen in the
spellblade build (Trinity Force / Infinity Edge / Berserker's Greaves carry
none).

```
L11: base AD 78   → 2.00 × 78  = 156.0 raw → 156.0 × 2/3 = 104.00 per proc
L18: base AD 103  → 2.00 × 103 = 206.0 raw → 206.0 × 2/3 = 137.33 per proc
```

### Proc-count arithmetic (this is the whole delta)

```
procs = min(total_ability_casts, 1 + floor(fight_duration / (cd + weave_delay)), attack_limit)

before: min(1, 1 + floor(5.0/3.0) = 2, 5 autos)  = 1   ← capped by CASTS (Q only)
after:  min(4, 1 + floor(5.0/3.0) = 2, 5-6 autos) = 2   ← capped by SPELLBLADE COOLDOWN
```

L11 `104.00 × 1 → 104.00 × 2 = 208.00`; L18 `137.33 × 1 → 137.33 × 2 = 274.67`.
Scenario totals move by exactly one proc: `1264.46 → 1368.46` (+104.00) and
`1597.25 → 1734.58` (+137.33) — nothing else in either fight moved.

### Why it cannot be a double-count

1. **Each cast is booked once.** `cast_events` holds four distinct
   `(slot, ordinal)` pairs / `cast_id`s — `Q:1 W:1 E:1 R:1` — at four distinct
   timestamps. No slot appears twice.
2. **Two of the four charges are never consumed.** `procs = 2 < casts = 4`. The
   binding cap is Sheen's own `1.5s cooldown + 1.5s weave = 3.0s` over a 5.0s
   fight, *not* the cast count — so adding three castable slots can raise the
   count by at most +1 no matter how many are added.
3. **`_spellblade_proc_times` appends at most one proc per cast** and restarts
   the cooldown at each consumption. Emitted times: `[1.5, 4.5]` —
   `max(0.00, -∞) + 1.5 = 1.5`; cooldown ends `1.5 + 1.5 = 3.0`; next armed
   cast (W@0.25) → `max(0.25, 3.0) + 1.5 = 4.5`. Both inside the 5.0s window,
   spaced by exactly `cooldown + weave_delay`.
4. **Per-proc damage is identical before and after** (`137.33` both sides), so
   nothing was re-multiplied.
5. **Precedent is exact.** Braum — whose W and E are already `no_damage` rows in
   the *committed* baseline — runs the identical path today:
   `casts 4 → procs 2 → 145.33/proc`. Bard now reproduces it with
   `casts 4 → procs 2 → 137.33/proc`. The engine has always armed spellblade
   charges from utility casts; Bard was simply not supplying any.

## Taric — 22 paths (attribution from the Taric stream, independently re-verified)

Bravado's magnitude is the cached P `Per-Level Scaling` leveling row,
`25 : 101` across levels 1-20 → `+4.0` per level:

```
L11: 25 + 10 × 4 = 65
L18: 25 + 17 × 4 = 93
```

Every Taric cast arms Bravado (2 charges per arming) → **2 procs** per sustained
scenario, confirmed live (`count: 2` in every build).

| Level | Build | Effective MR | Multiplier | Arithmetic | Snapshot |
| --- | --- | --- | --- | --- | --- |
| 11 | no_items / physical / spellblade | 40 | `100/140 = 0.714286` | `65 × 0.714286 × 2` | **92.86** |
| 11 | magic (Shadowflame flat MPen 15) | 25 | `100/125 = 0.80` | `65 × 0.80 × 2` | **104.00** |
| 18 | no_items / physical / spellblade | 40 | `100/140 = 0.714286` | `93 × 0.714286 × 2` | **132.86** |
| 18 | magic (Shadowflame flat MPen 15) | 25 | `100/125 = 0.80` | `93 × 0.80 × 2` | **148.80** |

T2 = 8 paths (`2 levels × 4 builds`, sustained only — one-rotation has no auto
stream to carry an on-attack packet). T3 = the same 8 scenario totals, each
moving by exactly the T2 amount. T1 = 6 `champion_baselines` paths: the passive
entry reshapes from a state row (`rank`, `cooldown`, `resource_cost`,
`resource_type` removed) to an on-hit packet (`on_hit` added, `detail`
rewritten).

## Gates run

| Gate | Result |
| --- | --- |
| `.venv/bin/pytest -q -k bard --tb=short` | **90 passed**, 8063 deselected |
| `.venv/bin/pytest -q --tb=no -rxX` | **8153 passed**, 0 failed, 0 xfail, 0 xpass |
| `.venv/bin/black --check` (bard.py, test_bard.py, test_bard_chimes_ledger.py) | **3 files unchanged** |
| `.venv/bin/pylint src/calculator/champions/bard.py` | **9.52/10** (CI gate `--fail-under=9`) |

The three pylint messages (`R0902`, `C0116`, `R0903`) all sit inside
`_TravelersCallRule` (bard.py:80-107), which this stream did not touch —
pre-existing, and above the gate threshold.

## Recapture status — BLOCKED

`scripts/golden_baseline.json` is **unchanged from `HEAD`** and the golden gate
is still red at 78 diffs. It was **not** recaptured, on purpose.

Timeline (local):

| Time | Event |
| --- | --- |
| 21:59:41 | `compare` → **77 diffs**, all Bard + Taric, all attributed above |
| 22:04:27 | concurrent worker writes `src/calculator/champions/kaisa.py` |
| 22:05:39 | concurrent worker writes `tests/test_kaisa.py` |
| 22:06:42 | `capture` run → absorbed **1 extra Kai'Sa path** |
| 22:07 | capture reverted; `golden_baseline.json` restored byte-identical to `HEAD` |

The absorbed path was:

```
/champion_baselines/Kaisa/abilities_level_11/E: <absent> -> {... "name": "Supercharge", "total_raw": 0.0 ...}
```

i.e. the Kai'Sa stream performing the *same* kind of slot reclassification,
still in flight. Recapturing would have written an unaudited row from another
stream into the shared numeric baseline and destroyed that stream's own gate
signal — the exact "stale value silently wins" failure this repo's rules exist
to prevent. A re-run of `compare` against the restored baseline confirms
**78 diffs = the 77 above + that single Kai'Sa line**, and nothing else.

### To finish once the Kai'Sa stream closes

```bash
.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # confirm 77 + Kai'Sa's own, all attributed
.venv/bin/python scripts/golden_snapshot.py capture scripts/golden_baseline.json
.venv/bin/python scripts/golden_snapshot.py compare scripts/golden_baseline.json   # expect: OK, identical
jq empty scripts/golden_baseline.json
```

## Known risk carried forward (pre-existing, engine-wide)

`rotation.total_ability_casts` has a second consumer besides spellblade:
`cast_spread = (total_ability_casts - 1 + r_extra) × 0.5` in the item-burn step,
which widens a burn's refresh window as cast count rises. No golden build
carries a burn item (`Liandry's` / `Blackfire` are absent from all four sweep
builds), so it produced no diff here. This affects all 93 champions that
already carry `no_damage` rows identically — it is not introduced by this
stream, but a Bard-plus-burn build will now integrate a wider burn window than
before.

## Addendum — recapture executed (orchestrator, 2026-08-21)

Final pre-recapture compare: 78 diffs = the 77 Bard+Taric diffs attributed
above + 1 Kai'Sa line (`champion_baselines/Kaisa/abilities_level_11/E`:
new ghosted Supercharge baseline row, total_raw 0.0 — the E slot's
no_damage reclassification from the Kai'Sa stream; its P/R work produced
zero fight-scenario diffs). Recaptured; compare identical.
