# Golden recapture — roadmap slot session 3 wave 3 (Mel, Mordekaiser, Naafiri), 2026-08-21

Pre-recapture compare: **141 diffs, zero unattributed.**

| champion | baseline diffs | fight diffs | total | cause |
| --- | ---: | ---: | ---: | --- |
| Naafiri | 25 | 90 | 115 | W hunt steroid + P Packmate coupling |
| Mel | 8 | 18 | 26 | P Searing Brilliance projectiles |
| Mordekaiser | 0 | 0 | **0** | label-only reclassification |

Attribution method — beyond per-row arithmetic, every golden fight scenario
(2 levels x 4 builds x burst/sustained) was re-run with each champion's new
behaviour switched off through its own option, and checked against the
recorded baseline numbers:

- Naafiri with `w_hunt=False`: **88 pre-existing rows reproduce the baseline
  exactly**; the only residual is the new `passive` row, which is a separate
  mechanic and fires with or without the hunt.
- Mel with `p_searing_brilliance_missiles=0`: **108 rows, zero residual** —
  the whole 26-diff set is the projectiles and nothing else.
- Mordekaiser at defaults: 104 rows, zero residual, matching its zero diffs.

## Naafiri (115)

### W — The Call of the Pack (was `out_of_scope`, now a `stat_buff`)

The hunt grants bonus attack damage equal to **20% of TOTAL AD**. The number
lives in wiki W prose only (no leveling row), corroborated by the game
binary's `NaafiriADPercentBoost = 0.20` (unranked across all 7 padded rank
slots). Modeled as a BUFF-phase `stat_buff(bonus_attack_damage)`, so Q/E/R,
autos, on-hit items and the Packmate row below all price off the buffed
bonus AD.

Because the buff is `0.2 x total AD`, any row that scales purely with AD
moves by exactly **x1.2**, and any row with a flat term gains exactly
`(its bonus-AD ratio) x buff`:

- Level 11, no items: total AD 73.0 -> buff **14.6**.
  - Q `parts[0]` 55.0 -> **57.92** (`55 + 0.20 x 14.6`); Q bleed tick
    13.5 -> **14.668** (`13.5 + 0.08 x 14.6`); Q `total_raw`
    270.0 -> **290.44** (gain `1.4 x 14.6 = 20.44`, ratio
    `0.20 + 10 x 0.08 + 0.40`).
  - E `parts[0]` 15.0 -> **20.84**, `parts[1]` 60.0 -> **71.68**,
    `total_raw` 75.0 -> **92.52** (gain `1.2 x 14.6 = 17.52`).
  - R `parts[0]`/`total_raw` 200.0 -> **214.6** (gain `1.0 x 14.6`).
- Level 18, no items: total AD 89.0 -> buff **17.8**; sustained
  `auto_attacks` 237.33 -> **284.8** = exactly x1.2; level 11 the same
  (146.0 -> 175.2), and with the physical build (1342.0 -> 1610.4,
  1254.0 -> 1504.8). `on_hit_Kraken Slayer` (2 rows) moves because Kraken's
  own damage carries an AD term.
- Fight-row Q gains slightly **more** than `1.4 x buff` (level 11 no-items:
  +14.55 mitigated vs +13.63). That is not a new nonlinearity: the fight
  interpolates Q's recast bonus between the Minimum and Maximum rows *by
  target missing health*, so every added damage source feeds it. Proved by
  isolating it — with `q_recast=False` the level-11 no-items Q gain is
  **exactly** `1.0 x 14.6 x 100/150 = 9.73333`.

### P — We Are More (was `out_of_scope`, now the pack's damage coupling)

The innate summon deals no damage of its own; what the Packmates contribute
is R's sourced `Physical Damage per Packmate` row (12.5/20/27.5 + 10% bonus
AD) times the sourced pack size (cap 2/3/4/5 by level, +2 while the hunt is
up). Pre-level-6 it fails closed: R unlearned -> `total_raw 0.0` with an
explicit "no sourced damage row" detail, never a guessed number.

All six published wiki R-note bands reproduce exactly:

| level | R rank | hunt off | hunt on |
| ---: | ---: | --- | --- |
| 6 | 1 | `12.5 x 2` = **25.0** | `(12.5 + 0.1 x 12.6) x 4` = **55.04** |
| 11 | 2 | `20.0 x 3` = **60.0** | `(20 + 0.1 x 14.6) x 5` = **107.3** |
| 18 | 3 | `27.5 x 5` = **137.5** | `(27.5 + 0.1 x 17.8) x 7` = **204.96** |

Golden's 50-armor scenario shows these mitigated: level 11 no-items
`passive` = `107.3 x 100/150` = **71.53**; level 18 no-items =
`204.96 x 100/150` = **136.64**.

### The 7x overstatement this closure introduced and fixed

The first cut of P carried the pack size in **both** `DamagePart.count` and
`proc_count`. `damage.py::_add_precomputed_proc_damage` prices
`sum(part.amount * part.count) * proc_count`, so a 7-Packmate pack was
priced as **49 hits — 1434.72 instead of 204.96, an exact 7x** — and also
told `_apply_basic_amp` about 49 damage instances. Fixed to one hit per part
with the pack size as the proc count. `TestProcCountSemantics` pins the
contract and, at zero resistances, that the fight row equals `total_raw`
rather than a multiple of it.

### WARNING — Naafiri's binary spell slots are SWAPPED

The record named `NaafiriR` **is wiki W**; the record named `NaafiriW`
**is wiki R**. The binding is re-derived from cooldowns, the only quantity
both channels publish independently (`NaafiriR.cooldownTime` ranks 1-5 =
26/24/22/20/18 = wiki W; `NaafiriW.cooldownTime` ranks 1-3 = 110/95/80 =
wiki R). A silent re-bind would swap a 20% AD steroid with an ultimate's
damage row, so `TestSlotLabelsAreSwapped` asserts the swap directly and
that neither record fits the other's cooldowns. Treat any future re-read of
`data/bin/characters/naafiri.bin.json` as swapped until those tests say
otherwise.

## Mel (26)

P (Searing Brilliance) was previously a non-damaging stub. It is two
mechanics; the Overwhelm execute was already documented, and the
**priceable** half is the projectiles: an ability cast arms one empowered
attack that fires **3 blazing projectiles (max 9 stacked)** dealing
`8 -> 30 by level + 4% AP` each. Corroborated by the binary's
`MelPassive`: `PassiveBonusMissiles = 3`, `Max = 9`, 5s window,
`PassiveBonusMissileDamage = ByCharLevel 8 -> 30 + 0.04 AP`.

The magnitude is read from the **cached wiki row** and the binary
interpolation is asserted against it (0.01 tolerance), plus the all-9 row
is asserted to be exactly 9x the per-projectile row — a patch that moves
either source raises instead of pricing a stale projectile.

- Baseline (8 diffs): the passive slot flips from a state-only stub
  (`rank`/`cooldown`/`resource_*` dropped) to a modeled `on_hit` row with
  `certified_constants`; W's detail gains its sourced shield amount
  (80-200 + 70% AP). No damage was added to W — it stays a `no_damage`
  receipt (cc-immunity + shield + projectile destruction, and its
  `DamagePercent` is a reflection *modifier*, not a damage row).
- Fight (18 diffs): 8 new `on_hit_ability_passive` rows, 8 `total_damage`,
  2 `shadowflame_Shadowflame`. Only **sustained** scenarios move — the
  projectiles ride an empowered basic attack, so the burst scenarios
  (`auto_attack_uptime=0`) correctly stay at zero.
- Arithmetic: level 11, 0 AP -> `3 x 20.94` = **62.82** raw; at 40 MR that
  is `x 100/140` = **44.87**, the exact new no-items row. Level 18, 0 AP ->
  `3 x 30` = **90** raw -> **64.29**. Magic build (442 AP): level 11
  `3 x (20.94 + 0.04 x 442)` = **115.86** raw, mitigated by Shadowflame's
  flat magic pen (40 MR -> 25) `x 0.8` = **92.69**; level 18
  `3 x (30 + 17.68)` = **143.04** -> **114.43**. The two
  `shadowflame_Shadowflame` movements are downstream of the added magic
  damage instances, and vanish when the projectiles are set to 0.

## Mordekaiser (0)

W (Indestructible) and R (Realm of Death) were labelled `out_of_scope`
while the packet already emitted `no_damage` rows — a stale label, not a
gap. Reclassified to `no_damage` with tri-source receipts (wiki entry has
no damage clause; binary `MordekaiserW` has no damage field, only
`DamageConversion .45` / `DamageTakenConversion .075` / `MaxHealthCap .30` /
`HealingPercent` ranks 1-5 = 35/37.5/40/42.5/45% matching wiki, and
`MordekaiserR` carries only `SpiritRealmDuration 7` /
`StatStealPercentScalar 0.1` / `ZoneRadius 1200` / `GhostAPRatio 0.6`).
Two ASSUMPTIONS rows added, including an R stat-steal receipt for the
defender-stat input gap. **Zero behaviour change, hence zero golden
movement** — which is itself the evidence the reclassification was purely
a label fix.

## Latent defect found, reported, NOT fixed — `illaoi.py`

`_tentacle` has the exact defect Naafiri's P just hit: it sets both
`DamagePart(count=count)` and `proc_count: count`. Measured at level 18,
zero resistances, comparing the fight row against `total_raw`:

| `p_tentacles` | parse `total_raw` | fight row | overstatement |
| ---: | ---: | ---: | ---: |
| 1 | 448.50 | 448.50 | x1.0 |
| 3 | 1345.50 | 4036.50 | **x3.0** |
| 5 | 2242.50 | 11212.50 | **x5.0** |

It is invisible to the golden gate because golden runs default options and
the default `p_tentacles` is 1, where N x N == N. Out of this session's
scope (Illaoi is not a slot-5 champion); left untouched and recorded here
so it is not rediscovered as a regression.

---

Recapture executed after this attribution; compare re-verified identical.
