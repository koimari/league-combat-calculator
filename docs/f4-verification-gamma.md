# F4 Verification — Gamma Batch (rotation engine cross-check)

**Reviewer:** F4 gamma pass · **Worktree:** `/Users/river/Projects/league-combat-calculator-audit` @ `c8bb082` (branch `codex/deep-audit-2026-08`) · **Date:** deep-audit-2026-08 cycle
**Method:** For each of the 57 assigned champions the resolver was called programmatically at baseline (level 11, no items, target 2000 HP / 100% current HP) via the project environment `.venv/bin/python` (3.14). Recorded: display name, derived `cast_order`, `derived` flag, rationale, `sources`, `setup`/`consume` receipts, and the edge detector's raw edges (setup/consume/kind/cite). Every derived order was checked for (a) valid permutation of the parsed/certified slots, (b) setup-before-consume satisfaction of every detected edge. Findings are grounded only in local source data: `data/champions.json` (patch-16.15 wiki cache with structured leveling attribute rows), `data/atoms/<key>.atoms.json` (atom provenance: wiki + binary), `data/champion-audit/*.json`, module source in `src/calculator/champions/`, `src/calculator/rotation_resolver.py` (F3), `tests/test_f3_rotation_all.py` / `tests/test_f2_rotation.py`. No remote operations were performed; no product code was edited.
**Sanity checks:** `tests/test_f3_rotation_all.py` (16 passed) and `tests/test_f2_rotation.py` (51 passed) — the suites pass, but passing tests were **not** treated as evidence of semantic correctness (see §2/§3).
**Violation scan:** order-vs-edge violations across all 57: only the two documented Varus seed exceptions (`R→Q` stack_consume + `R→Q` detonate), which the F2 seed deliberately overrides (documented in `tests/test_f3_rotation_all.py::_OVERRIDE_SEED_EXCEPTIONS`). Permutation check: no order drops or invents slots.
**Verdict legend:** CERTIFIED = semantics agree with sourced data · CERTIFIED WITH DOCUMENTED LIMITATION = engine is honest but cannot model the relationship · NEEDS ATOM/OVERRIDE = current result could be semantically wrong · ENGINE BUG = order/rationale/edge detector contradicts sourced data.

## 1. Assigned champions — full table (57)

| Key | Display name | Derived order (L11, no items) | Detected edge kinds | Semantic verdict | Evidence (local source) |
|---|---|---|---|---|---|
| Sejuani | Sejuani | Q → W → E → R | — | CERTIFIED | flat; P Frozen mark (stun->consume) rides the auto stream; Q knockup open, R last; no cast-slot setup/consume |
| Senna | Senna | Q → W → E → R | — | CERTIFIED | flat; P Weakened Soul mark consumed by autos/abilities (mist economy); no cast-slot edge |
| Seraphine | Seraphine | E → R → Q → W | execute | CERTIFIED | Q missing-health execute (0:75%) cast after E/R; E root/slow + R charm cc atomized but module cc untyped; order DPS-consistent |
| Sett | Sett | Q → W → E → R | — | CERTIFIED | flat; W grit true damage is self-resource (documented exclusion class); E stun untyped cc, order neutral |
| Shaco | Shaco | Q → W → R → E | execute | CERTIFIED | E execute (+50% below 30% HP) closes; Q/W/R precede by execute edges |
| Shen | Shen | E → Q | — | CERTIFIED | certified E,Q: E Shadow Dash taunt opens, Q Twilight Assault damage; W/R no-damage rows correctly excluded |
| Shyvana | Shyvana | Q → W → E → R | — | CERTIFIED | flat; no cast-slot setup/consume; dragon-form recast is heal state |
| Singed | Singed | Q → W → E → R | — | CERTIFIED | flat; Q poison trail first is correct opener; W/E/R no cross-slot edges |
| Sion | Sion | E → Q → W → R | shred | CERTIFIED | E shred edge (25% armor reduction 4s, target_debuff) opens; Q/W/R follow |
| Sivir | Sivir | Q → W → E → R | — | CERTIFIED | flat; Q two-way pass, W/R buffs, E spell shield; no edges |
| Skarner | Skarner | Q → W → E → R | — | CERTIFIED | flat; P Quaking stacks auto-consumed at 3; E impale->Q pull is prose-only, order not clearly wrong |
| Smolder | Smolder | Q → W → E → R | — | CERTIFIED | flat; Q main damage first; tier-3 burn is stack-gated state |
| Sona | Sona | Q → W → E → R | — | CERTIFIED | flat; Q/W/E/R no cross-slot setup; R stun untyped cc, order neutral |
| Soraka | Soraka | Q → W → E | — | CERTIFIED | flat; Q,W,E (R Wish no-damage correctly excluded); W heal row |
| Swain | Swain | Q → W → E → R | — | NEEDS ATOM/OVERRIDE | E Nevermove root (recast) unmodeled as cc_kind; W 1.5s-delayed Vision of Empire cast before E — root-setup inverted |
| Sylas | Sylas | Q → W → E → R | — | CERTIFIED | flat; E2 Abduct stun untyped cc, order neutral; W heal |
| Syndra | Syndra | Q → Q2 → W → E → R | recast | CERTIFIED | Q,Q2,W,E,R; Q2 second charge recast edge; R sphere-count execute position last |
| TahmKench | Tahm Kench | Q → W → R | — | CERTIFIED | flat Q,W,R; Q applies An Acquired Taste stacks, R Devour last (consume position correct); E shield excluded |
| Taliyah | Taliyah | E → W → Q | — | CERTIFIED | certified E,W,Q: E mines laid before W knock-through detonation (EMineDamage marker/stun atoms); Q last |
| Talon | Talon | Q → W → E → R | — | CERTIFIED | flat; P Blade's End 3-stack bleed auto-consumed; no cast-slot edge |
| Taric | Taric | Q → W → E → R | — | CERTIFIED | flat; E Dazzle stun untyped cc, order neutral; Q/W heals, R invuln state |
| Teemo | Teemo | Q → W → E → R | — | CERTIFIED | flat; Q blind, E on-hit poison, R shrooms; no cast-slot setup |
| Thresh | Thresh | Q → W → E → R | — | CERTIFIED | flat; Q hook first is the correct opener; E/R follow |
| Tristana | Tristana | Q → W → E → R | — | NEEDS ATOM/OVERRIDE | E Explosive Charge self-edge (charge attach + 4s fuse, stacks via autos/abilities, W reset) undetected; E should open, not sit after W |
| Trundle | Trundle | Q → W → E → R | — | CERTIFIED | flat; Q chomp, R drain DoT; W/E utility rows |
| Tryndamere | Tryndamere | Q → W → E → R | — | CERTIFIED | flat; Q heal row, E spin, W/R utility; no edges |
| TwistedFate | Twisted Fate | Q → W → E → R | — | CERTIFIED | flat; W gold-card stun rides the auto stream (buff row); Q-first not clearly wrong in deterministic model |
| Twitch | Twitch | W → R → Q → E | buff, stack_consume | CERTIFIED | W poison -> R AD amp (stat_buff) -> Q -> E detonate; stack_consume+buff edges all satisfied |
| Udyr | Udyr | Q → W → E → R | — | CERTIFIED | flat; stance-swap buffs; awakened bonuses are option-gated state |
| Urgot | Urgot | Q → W → E → R | — | CERTIFIED | flat; R Fear Beyond Death missing-health slow/execute documented kill boundary, R last |
| Varus | Varus | Q → E → R → W | detonate, stack_consume | CERTIFIED | seed Q,E,R,W with documented R->Q exception; W on_hit Blight + 'abilities detonate all Blight stacks' supports the seed |
| Vayne | Vayne | R → Q → W → E | buff | CERTIFIED | R bonus-AD buff (stat_buff) opens; Q/W/E follow; W Silver Bolts on-hit 3-stack true damage auto-driven |
| Veigar | Veigar | Q → W → E → R | — | NEEDS ATOM/OVERRIDE | R Primordial Burst missing-health execute (0:100%) undetected (attribute 'Minimum/Maximum Magic Damage' + prose); rationale falsely claims no execute; order coincidentally R-last |
| Velkoz | Vel'Koz | Q → W → E → R | — | CERTIFIED | flat; Q/W/E damage, R channel last; E knockup untyped cc, order neutral |
| Vex | Vex | Q → W → E → R | — | CERTIFIED | flat; Gloom mark (P/E) detonated by autos (p_gloom_detonations rider); R mark+recast last |
| Vi | Vi | Q → E → R | — | CERTIFIED | certified Q,E,R: Q engage, E cone, R suppress; W Denting Blows 3-stack shred is auto-stream (ViWMarker/Proc atoms) |
| Viego | Viego | Q → W → E → R | — | CERTIFIED WITH DOCUMENTED LIMITATION | Q mark (ViegoQMark atom) consumed by the AUTO stream, not a cast slot; Q,W,E,R has Q first anyway |
| Viktor | Viktor | Q → W → E → R | — | CERTIFIED | flat; Q shield/discharge, W field, E laser, R storm; no cross-slot edges |
| Vladimir | Vladimir | R → Q → E → W | amp | CERTIFIED | seed R,Q,E,W; Hemoplague 10% amp (r_hemoplague_debuff) opens the burst — correct |
| Volibear | Volibear | Q → W → E → R | — | CERTIFIED WITH DOCUMENTED LIMITATION | W Frenzied Maul self-Wounded (w_wounded option; W applies and consumes its own mark) is order-neutral; no cross-slot consumer exists |
| Warwick | Warwick | Q → W → E → R | — | CERTIFIED | flat; R suppress engage, Q heal, W/E utility; no cast-slot setup/consume |
| Xayah | Xayah | Q → W → E → R | — | CERTIFIED | flat; Q places feathers before E Bladecaller detonation (Q,W,E,R satisfies); clean_cuts stack system auto-driven |
| Xerath | Xerath | Q → W → E → R | — | CERTIFIED | flat; Q charge, W slow, E stun (untyped cc), R recasts last; order neutral |
| XinZhao | Xin Zhao | Q → W → E → R | — | CERTIFIED | module covers Q/W/E/R; W Challenged mark (E range, R knockback-exclusion) prose-only but W-before-E/R satisfies it; P Determination auto-consume |
| Yasuo | Yasuo | Q → W → E → R | — | CERTIFIED WITH DOCUMENTED LIMITATION | Q Gathering Storm self-stacks -> Q3 and E Ride the Wind self-stacks correctly excluded; module has no Q3 slot; R airborne requirement unmodeled but R last |
| Yone | Yone | Q → W → E → R | — | NEEDS ATOM/OVERRIDE | E Soul Unbound stored-damage mark ('Damage Stored' attr, true-damage +5s recast part) undetected and mis-ordered: E after Q/W, but the mark must be cast BEFORE the damage it stores |
| Yorick | Yorick | Q → W → E → R | — | CERTIFIED | flat; E Cursed armor-shred prose-only (no structured row), order not clearly wrong; W wall no-damage |
| Yunara | Yunara | Q → W → E → R | — | CERTIFIED | flat; W linger DoT priced; R Transcendent state option-gated |
| Yuumi | Yuumi | Q → W → E → R | — | CERTIFIED | flat; Q damage first, W attach, E shield, R heal/damage; no cast-slot setup |
| Zaahen | Zaahen | Q → W → E → R | — | CERTIFIED | flat; Q empowered strike + R heal rules; W/E/R damage modeled |
| Zac | Zac | Q → W → E → R | — | CERTIFIED | flat; Q double-strike, W, E, R bounces; no cast-slot setup |
| Zed | Zed | W → E → Q → R | — | ENGINE BUG | seed W,E,Q,R is inverted: Death Mark stores damage dealt DURING the mark (after R's cast); seed casts all damage before R, and its rationale claims R 'stores that burst' |
| Zeri | Zeri | Q → W → E → R | — | CERTIFIED | flat; Q main damage, E Burst Fire, R stack AS buff state |
| Ziggs | Ziggs | Q → W → E → R | — | CERTIFIED | flat; Q/W/E/R modeled; W turret execute documented out |
| Zilean | Zilean | Q → W → E → R | — | CERTIFIED | flat; Q only enemy-damage slot; W/E utility, R revive state |
| Zoe | Zoe | Q → W → E → R | — | CERTIFIED | flat; Q Paddle Star, E sleep, R blink; stolen-shard rows no-damage |
| Zyra | Zyra | Q → W → E → R | — | CERTIFIED | flat; E root untyped cc, order neutral; W plants priced via plant_count |

## 2. F4 gap-row verdicts (10 of the 19 F3 rows fall in this batch)

### 2.1 Tristana — F3 row 1 (E charge self-edge) → **NEEDS ATOM/OVERRIDE**
- Derived: `Q → W → E → R`, no edges, rationale = flat-kit fallback ("no … mark/stack consumer").
- Sourced data: `champions.json` E "Explosive Charge": *"tosses an explosive charge at the target enemy that attaches to them for 4 seconds … Tristana's basic attacks on-hit and abilities against the target increase Explosive Charge's damage by 25%, stacking up to 4 times … upon which the charge also detonates instantly"*; W: *"Scoring an enemy champion takedown or detonating Explosive Charge at maximum stacks … will reset Rocket Jump's cooldown."* Atom provenance: `stack-transform-summon-resource.stack · TristanaECharge` (wiki Stack/Stacking, binary `TristanaECharge`) + `TristanaEDebuff`; the module prices the detonation via `e_stacks` (default 4) — i.e. the charge is assumed pre-stacked, and the cast-order consequence (E must be attached before the stacking window, and before W to enable the reset) is not expressible.
- The F3 report itself lists the known combo "E first, then autos/abilities stack it to full-stack detonation" with the missing `charge applier` atom. Current order places E after W, forfeiting the W-reset sequencing and the 4 s fuse in a one-rotation burst.
- **Smallest fix:** author the F3-suggested "charge applier" atom on E (attach-before-stack) so the engine derives E first, or add a documented override seed `E → Q → W → R` (E opens).

### 2.2 Volibear — F3 row 4 (W self-consumed Wounded) → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q → W → E → R`, no cross-slot edges; rationale honestly reports flat kit.
- Sourced data: W "Frenzied Maul": *"mark the target Wounded for 8 seconds. Wounded Bonus: If the target is already Wounded, Volibear takes a bite out of them instead, dealing 50% (+25% per 100 bonus AD) increased damage and healing himself."* The `w_wounded` option is a `mark_consume` consume-role option, but the only applier is W itself → the detector's `add()` correctly skips the self-edge (`a != b`). No other consumer exists, so the self-edge is order-neutral; Q→W→E→R (Q stun opens, E delayed strike) is semantically sound.
- **Smallest fix:** none required for the order; optionally document the W→W recast in the module (F3 suggested a `self-consumed-mark` atom for the audit trail).

### 2.3 Viego — F3 row 5 (Q mark → auto) → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q → W → E → R`, no edges.
- Sourced data: Q "Blade of the Ruined King": *"his damaging abilities apply a mark to enemies hit for 4 seconds. Viego's next basic attack against a marked target is empowered to consume the mark on-hit to strike a second time."* Atom provenance: `stack-transform-summon-resource.mark · ViegoQMark` (binary `ViegoQMark`). The consumer is the basic-attack stream, which is not a cast slot the resolver can order; Q first is the correct opener anyway.
- **Smallest fix:** none — engine cannot model auto-stream consumption; the honest flat-kit rationale is accurate (no cast-slot consumer exists).

### 2.4 Yasuo — F3 row 9 (Q3 self-recast) → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q → W → E → R`, no edges (module has no Q2/Q3 slot).
- Sourced data: Q "Steel Tempest": *"Yasuo generates a stack of Gathering Storm … At 2 stacks, the next Steel Tempest cast consumes them all to become empowered"* (self-stack, correctly excluded); E "Ride the Wind" self-stacks; R "Last Breath" requires airborne targets and *"resetting Gathering Storm stacks"*. Atom provenance confirms the airborne/knockup machinery (`crowd-control-mobility.airborne · YasuoRKnockUpCombo*`) but there is no Gathering Storm recast slot in the module, so no `recast` edge can exist. Self-stacks produce no cross-slot edge by design — the F3 report's "correctly excluded" claim holds; R-last is fine.
- **Smallest fix:** none for order correctness; optionally add a `q_gathering_storm` recast pair atom / Q3 slot so the Q→Q3 cadence is represented (F3's own suggested resolution).

### 2.5 Shen — F3 row 11 (certified CAST_ORDER completeness) → **CERTIFIED**
- Derived `E → Q` == certified `['E','Q']`; a valid permutation of the module's meaningful slots (W Spirit's Refuge and R Stand United are no-damage rows; P Ki Barrier shield state).
- Sourced data: E "Shadow Dash" *"taunting them for 1.5 seconds"* (atom `crowd-control-mobility.immobilize · ShenE`); Q "Twilight Assault" damage + empowered autos. Taunt-first (E) then Q is the correct League opener (keeps the target in Q/auto range). No edge needed; certified order complete and correct.

### 2.6 Taliyah — F3 row 11 (certified CAST_ORDER completeness) → **CERTIFIED**
- Derived `E → W → Q` == certified `['E','W','Q']`.
- Sourced data: E "Unraveled Earth": *"Enemies that dash or are knocked over a stone will detonate it … becoming stunned"* (atoms `TaliyahEMineDamageMarker` mark + `TaliyahEMineStun` stun); W "Seismic Shove" knocks enemies 400 units (no damage row — displacement only); Q "Threaded Volley" is the main damage row (325 raw). E-before-W is the semantically correct mine→knock-through detonation; Q closes. R (Weaver's Wall) is a no-damage utility row, correctly excluded.

### 2.7 Vi — F3 row 11 (certified CAST_ORDER completeness) → **CERTIFIED**
- Derived `Q → E → R` == certified `['Q','E','R']`; W Denting Blows is an on-hit stack system (atoms `ViWMarker` mark, `ViWProc` proc; 20% armor reduction at 3 stacks) consumed via the auto stream — no cast slot, correctly absent from the certified order. Q engage → E cone → R suppress is semantically sound.

### 2.8 Seraphine — F3 row 13 (missing-health Q) → **CERTIFIED** (poke-cadence caveat)
- Derived: `E → R → Q → W`; execute edges `E→Q`, `R→Q`; rationale cites the missing-health row.
- Sourced data: Q "High Note": *"the damage is increased by 0% : 75% (based on target's missing health)"* (atom `damage.execute · SeraphineQ`, wiki Execution); module prices the 0.75×base missing-health part (option assumption: "Maximum Enhanced Damage row at full missing health"). E→R→Q places the two cc/damage rows before the execute — Q-last maximizes the 0–75% missing-health bonus, which is the engine's stated execute model and is semantically defensible for a burst. The F3 report's concern ("it delays her poke") is a real playstyle tradeoff (Q is the 6 s-cd poke tool) but not an order error: the DPS tie-break that places E before R is matrix-consistent. E's root/slow (atoms `SeraphineERoot`/`SeraphineEStun`) and R's charm are atomized but the module authors no `cc_kind`, so the cc edges do not fire — the derived order is nevertheless correct.
- **Smallest fix:** none for order; optionally author cc_kind on E/R so the cc_setup signal is real rather than accidental.

### 2.9 Xin Zhao — F3 row 18 (module-coverage-only) → **CERTIFIED**
- Derived: `Q → W → E → R`, flat-kit rationale; module covers all four damaging slots (Q/W/E/R) with sourced numbers (audit: "reviewed CP10.10 packet with Q/W/E/R damage modeled").
- Sourced data: W "Wind Becomes Lightning" applies the Challenged mark (prose: *"apply a Challenged mark … Audacious Charge and Crescent Guard have interactions against Challenged targets"*); R "Crescent Guard": *"knocking back all targets hit that are not Challenged"*. The mark is prose-only (no structured row/option the resolver consumes), but the derived order already satisfies the interaction (W before E/R). P Determination stacks are auto-consumed (documented state).
- **Smallest fix:** none required; optionally add a `challenged` mark atom for the W→R knockback-exclusion interaction.

### 2.10 Varus — F3 row 18 (module-coverage-only + R-stack seed exception) → **CERTIFIED**
- Seed `Q → E → R → W` (derived=False) with the documented `R→Q` exception (`_OVERRIDE_SEED_EXCEPTIONS`); the only order-vs-edge violations in the batch are exactly these two pinned R→Q edges.
- Sourced data: W "Blighted Quiver" passive: *"Varus' basic attacks are empowered to deal bonus magic damage and apply a stack of Blight on-hit … Varus' abilities detonate all Blight stacks on affected enemies hit"* — supports the seed's claim that E and R detonate too; R "Chain of Corruption": *"they are also inflicted with maximum stacks of Blight"* — supports the data-side R→Q edge; atom `VarusWDebuff` + `blight_stacks` option price the per-stack detonation. The seed's judgment (Q first: autos already carry stacks) is coherent and documented.

## 3. Non-gap findings (champions whose derived/seed order is semantically wrong or misclassified)

1. **Zed (seed) — ENGINE BUG.** Seed `W → E → Q → R` with rationale *"R (Death Mark) stores that burst and detonates 3s later"* is inverted. Sourced data (`champions.json` R): *"Marked for Death: Zed stores a portion of all pre-mitigation physical damage and magic damage he and his Shadows deal to the target, detonating at the end of the duration"* — only damage dealt **after** R's cast is stored; the seed casts W/E/Q before R, so the mark stores (almost) nothing. Atom provenance confirms the mechanic (`stack-transform-summon-resource.mark · ZedRDeathMark` + `damage.execute · ZedRDeathMark`). The module's own pricing (`_death_mark` reads Q+E raw from `ctx.results` as the stored pool) is only valid if R leads — the order contradicts the module's own pricing assumption. **Smallest fix:** reorder the COMBO_TABLE Zed seed to `R → W → E → Q` (or `R → E → Q → W`) and correct the rationale; the module's stored-pool read then matches the mechanic. `test_f2_rotation.py` pins the current order and must be updated with the fix.
2. **Yone — NEEDS ATOM/OVERRIDE.** Derived `Q → W → E → R`, flat rationale ("no … missing-health execute"). Sourced data: E "Soul Unbound": *"His damaging basic attacks and abilities against enemy champions apply a mark that stores a portion of the post-mitigation damage dealt to the target"*; structured attribute row **"Damage Stored"** (25–35%); parsed part `DamagePart(true, 107.0, time_offset=5.0)`. The detector's `_ATTR_STORED_DMG = re.compile('stored damage')` does not match "Damage Stored", so no stored-damage edge fires; and the `stored_consume` branch's semantics ("stored execute after all other damage") would be the **wrong direction** for a mark applied at cast. The module prices E as a % of the fight's Q/W/R damage, which is only correct if E is cast first. **Smallest fix:** make the stored-damage attribute match order-insensitive ("damage stored"), and route mark-at-cast stored-damage slots (Yone E; cf. Zed R) to a setup-before-burst edge (E first), or add an override `E → Q → W → R`.
3. **Veigar — NEEDS ATOM/OVERRIDE (classification; order coincidentally correct).** Derived `Q → W → E → R` with rationale *"no … missing-health execute"*, but R "Primordial Burst": *"deals magic damage, increased by 0% : 100% (based on target's missing health)"* (structured rows "Minimum/Maximum Magic Damage"; parsed R part `hp_scaled=yes`). The execute detector requires the attribute text to contain "missing" or "enhanc… damage" — "Minimum/Maximum Magic Damage" + prose misses both. The order happens to place R last (execute position), so totals are not wrong, but the flat-kit classification is factually false and would mis-order if the base order ever changed. **Smallest fix:** also fire the execute edge when a parsed damage part is `hp_scaled=yes` with a missing-health phrase in the description, or add an `r_primordial_burst_missing_health` execute option (the `hp_scaled` flag is already in the parse).
4. **Swain — NEEDS ATOM/OVERRIDE.** Derived `Q → W → E → R`, flat rationale. Sourced data: E "Nevermove": *"rooting them for 1.5 seconds"* (recast pull); W "Vision of Empire" is a 1.5 s-delayed long-range explosion. The module authors no `cc_kind` on E (generated batch module), so the cc_setup edge cannot fire and the derived order casts the unreliable delayed W **before** E's root — the root→W setup is inverted. This is exactly the F3 "known combo with no derivable data signal" class (cf. Nidalee/Illaoi rows). **Smallest fix:** author `cc_kind="root"` on Swain E's damage part (or a `root_setup` atom); the existing `cc_setup` fan-out then derives `E → Q → W → R`.
5. **Minor same-class notes (not clearly wrong, listed for completeness):** TwistedFate W gold-card stun rides the auto stream (buff row) so Q-first is defensible in the deterministic model; Yorick E "Cursed … armor reduction" is prose-only (no structured row) and the order is not clearly wrong; Tahm Kench Q-stacks→R consume is unmodeled (both are self/auto-stream class) but R-last already satisfies the consume position; Sejuani P Frozen mark (stun→consume, +10% max HP) is auto-stream and unmodeled; Talon/Senna/Vex marks are consumed by the auto stream (documented in champion-audit) and their orders are order-neutral.

## 4. Overall verdict

The F3 algorithmic derivation is sound where it fires: every detected edge in this batch (Sion shred, Twitch stack+buff, Vayne buff, Shaco execute, Syndra recast, Seraphine execute, Vladimir amp, Varus detonate) is semantically correct against `champions.json`/atoms, and no order violates a detected edge except the two documented Varus seed exceptions. All three certified CAST_ORDER champions (Shen, Taliyah, Vi) are complete and correct. The batch's four honest-limitation rows (Viego, Volibear, Yasuo) are correctly excluded self/auto-stream mechanics. However, four champions need fixes before beta: **Zed seed order is semantically inverted (ENGINE BUG), Yone's stored-damage slot is mis-ordered and undetected, Tristana's E-first combo is unexpressed, and Swain's E-root setup is unmodeled**; Veigar's R execute classification is false (order coincidentally fine). The F3 test suite passing does not cover any of these (self-edges, prose/attribute mismatches, and seed pins are out of its invariant scope).

F4_SUMMARY: assigned=57; certified=49; limitation=3; needs_fix=4; engine_bug=1; gap_rows_reviewed=10
