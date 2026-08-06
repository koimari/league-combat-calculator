# F4 Verification — Alpha Batch (58 champions)

- **Reviewer**: F4 (independent cross-check of F3 algorithmic orders against sourced League semantics)
- **Date/worktree**: `/Users/river/Projects/league-combat-calculator-audit` @ `c8bb082` (branch `codex/deep-audit-2026-08`), no remote ops, no product-code edits
- **Method**: called `resolve_cast_order` at baseline (level 11, no items, `target_max_health=2000`, `target_missing_health=0`) via the project venv; re-ran the resolver's own `detect_setup_consume_edges`; inspected `data/champions.json` structured wiki rows, `data/atoms/*.atoms.json`, `data/champion-audit/*.json`, and module `CAST_ORDER`/`OPTIONS`/`ASSUMPTIONS`. Verdicts rest on sourced rows/atoms, not on the F3 test suite (which passes: `tests/test_f3_rotation_all.py` 16/16, treated only as a consistency check).
- **Definition**: `derived` = rule produced by `derive_champion_rule` (algorithmic); `seed` = one of the ten `COMBO_TABLE` overrides (Aatrox, Annie, Aphelios, Brand, Cassiopeia, Jhin, Lux, Varus, Vladimir, Zed — only the first five fall in this batch).

## 1. Champion table (all 58 assigned)

Key | Display | Derived order | Edge kinds detected | Semantic verdict | Evidence (sourced)
---|---|---|---|---|---
Aatrox | Aatrox | R → Q → W (seed) | buff R→Q/W | CERTIFIED | R row: "gains bonus attack damage" (20/30/40); Q 3 sweetspot casts, W "Total Damage"; E dash has no damage row (absent)
Ahri | Ahri | E → Q → W → R | cc_setup E→Q/W/R | CERTIFIED | E row: charm 80-240 + 85% AP, Disable Duration 1.2-1.8s; no damage-amp claimed; order sound
Akali | Akali | Q → W → E → R | none | CERTIFIED (minor: R2 execute edge missed) | R row: recast "increased by 0% : 200% (based on target's missing health)" — Min/Max attribute names hide it from the detector; order still puts R last
Akshan | Akshan | Q → E → R | execute Q/E→R | CERTIFIED | R row: "increased ... by 0% : 200% (based on target's missing health)"; execute last correct
Alistar | Alistar | Q → W → E | none | CERTIFIED | Q knockup / W Headbutt / E Trample; no setup/consume rows
Ambessa | Ambessa | R → Q → Q2 → W → E | recast Q→Q2; buff R→Q/Q2/W/E | CERTIFIED | R row: "Passive: Ambessa gains armor penetration" (10/20/30); R active is a suppress+damage, **not** an execute; Q2 recast_of atom
Amumu | Amumu | Q → W → E → R | none | CERTIFIED | Q stun / W Tantrum / E / R AoE stun+damage; no consume rows
Anivia | Anivia | Q → E → R | none (miss: Q→E chilled) | CERTIFIED (minor: detector miss) | E row: "doubled if they were Chilled"; E "Enhanced Damage" (110-310); Q/R apply Chilled — order Q→E→R satisfies the real edge anyway
Annie | Annie | E → R → Q → W (seed) | buff R→Q/W | CERTIFIED | R row: "Passive: Annie gains magic penetration" (10/15/20); seed rationale matches rows
Aphelios | Aphelios | Q → W → R (seed) | none | CERTIFIED | Q weapon-form variant, W Phase swap, R "Magic Damage" blast
Ashe | Ashe | Q → W → R | none | CERTIFIED | Q Ranger's Focus (auto override), W Volley, R stun arrow; no consume rows
AurelionSol | Aurelion Sol | Q → E → R | none | CERTIFIED | Q breath ticks, E Singularity, R Falling Star; no consume rows
Aurora | Aurora | Q → E → R | none | CERTIFIED | Q row: "increased by 0% : 50% (based on target's missing health)" (Min/Max attrs — not flagged as execute; Q-first is her poke norm)
Azir | Azir | Q → W → E → R | none | CERTIFIED (minor: Q-first assumes a pre-existing soldier) | W row: soldier damage rides `auto_attack_override`; Q "one damage instance per cast regardless of soldier count" (module doc) — soldier placement is not a cast-order constraint in the model
Bard | Bard | Q | none | CERTIFIED | W heal / E tunnel have no damage rows; Q is the only damaging cast
Belveth | Bel'Veth | Q → W → R → E | execute Q/W/R→E | CERTIFIED | E row: "Each slash deals physical damage, increased by 0% : 100% (based on target's missing health)"; execute last correct
Blitzcrank | Blitzcrank | Q → W → E → R | none | CERTIFIED | Q hook / E knockup / R AoE; no consume rows
Brand | Brand | Q → R → E → W (seed) | none (P-driven consume) | CERTIFIED WITH DOCUMENTED LIMITATION | see gap section (Blaze multi-consume)
Braum | Braum | Q → W → R | none | CERTIFIED | Q applies Concussion stacks (P stun); W/E no damage; order fine
Briar | Briar | Q → E → R → W | execute Q/E/R→W; shred Q→W/E/R | CERTIFIED | see gap section (Q shred + W execute)
Caitlyn | Caitlyn | Q → W → E → R | none | CERTIFIED WITH DOCUMENTED LIMITATION | see gap section (W trap/Headshot)
Camille | Camille | Q → Q2 → W → E → R | recast Q→Q2 | CERTIFIED | Q row: "Recast ... bonus damage is doubled" (Q2 recast_of atom); Q→Q2 order correct
Cassiopeia | Cassiopeia | Q → E → W → R (seed) | dot_consume Q→E, W→E (W→E violated — documented seed exception) | CERTIFIED (seed exception documented) | Q "poison" rows; seed deliberately casts E before W to start the 0.75s cadence; W also applies poison — exception is documented in tests
Chogath | Cho'Gath | Q → W → E → R | none | CERTIFIED | R true damage flat vs champions ("Champion True Damage"); no execute-vs-champion row
Corki | Corki | E → Q → W → R | shred E→Q/W/R | CERTIFIED | E row: "Resistances Reduction Per Stack" (3-5) × 4 stacks; shred first correct
Darius | Darius | E → Q → W → R | stack_consume Q/W/E→R; buff E→Q/W/R | ENGINE BUG (edge detector; order correct) | see gap section (E shred + Hemorrhage)
Diana | Diana | Q → W → E → R | none | CERTIFIED | Q/W/E/R plain damage rows; no consume rows
DrMundo | Dr. Mundo | E → Q → W → R | buff E→Q/W | CERTIFIED | E row: "gains bonus attack damage" (2-3.2) + active missing-health bonus; buff first correct
Draven | Draven | Q → W → E → R | none (miss: R execute) | CERTIFIED (minor) | R row: enemies "below a health threshold ... are executed" (Adoration) — not flagged; R last anyway
Ekko | Ekko | Q → W → E → R | none | CERTIFIED | Q/W/E/R plain; no consume rows
Elise | Elise | Q → W → E → R | none | CERTIFIED | form-aware Q/W; E cocoon no damage; R transform no damage
Evelynn | Evelynn | W → Q → E → R | mark_consume W→Q; shred W→Q/E/R; execute Q/E→R | CERTIFIED | W row: "magic resistance reduction" (35-45%) at full charm; Q row: "marking them for 4 seconds ... deal bonus magic damage"; R execute last correct
Ezreal | Ezreal | W → Q → E → R | mark_applier W→Q/E/R | CERTIFIED | W row: mark detonated by abilities; W-first correct
Fiddlesticks | Fiddlesticks | Q → W → E → R | none | CERTIFIED | Q fear / W drain / E / R Crowstorm; no consume rows
Fiora | Fiora | Q → W → E → R | none | CERTIFIED (minor: R priced 0 at baseline) | R (Grand Challenge) vitals are option-gated (`p_vitals`); at baseline R raw = 0 — order placement immaterial; in-game R-first opener unmodeled
Fizz | Fizz | Q → W → E → R | none | CERTIFIED | Q/W/E/R plain; no consume rows
Galio | Galio | Q → W → E → R | none | CERTIFIED | Q tornado / W taunt / E / R; no damage-amp rows
Gangplank | Gangplank | Q → W → E → R | none | CERTIFIED | Q Parrrley / E Powder Keg / R barrage; barrel Q-detonate synergy is not an order constraint in the packet
Garen | Garen | E → Q → W → R | shred E→Q/R | CERTIFIED (minor: R execute edge missed) | E row: "25% armor reduction" after 6 hits; R row: "True Damage" 125/200/275 + 25/30/35 "% of target's missing health" — modifier-unit hidden from detector; R last anyway
Gnar | Gnar | Q → W → E (Mini); Q → W → E → R (Mega) | none | CERTIFIED WITH DOCUMENTED LIMITATION | see gap section (Rage Gene/form)
Gragas | Gragas | Q → W → E → R | none | CERTIFIED | Q/W/E/R plain; no consume rows
Graves | Graves | Q → W → E → R | none | CERTIFIED | Q/E/R plain; no consume rows
Gwen | Gwen | Q → W → E → R | none | CERTIFIED | Q true-damage center / R Needlework recast; no consume rows
Hecarim | Hecarim | Q → W → E → R | none | CERTIFIED | Q 1.75s spam, W heal, E, R fear; no consume rows
Heimerdinger | Heimerdinger | Q → W → E → R | none | CERTIFIED | Q turret charges; R upgrade row has no direct damage (raw 0); order fine
Hwei | Hwei | R → Q → W → E | execute R→Q | CERTIFIED WITH DOCUMENTED LIMITATION | see gap section (missing-health Q)
Illaoi | Illaoi | Q → W → E → R | none | CERTIFIED WITH DOCUMENTED LIMITATION | see gap section (E spirit/vessel)
Irelia | Irelia | Q → W → E → R | none | CERTIFIED (minor: E→Q mark-reset unmodeled) | E row marks+stuns, Q resets on marked targets — a cooldown-cadence mechanic, not a damage-amp edge; Q damage is mark-independent
Ivern | Ivern | Q → W → E → R | none | CERTIFIED | Q root / W brush / E shield / R Daisy; no consume rows
Janna | Janna | Q → W → E → R | none | CERTIFIED | Q/W damage, E shield/R heal have no damage rows; order fine
JarvanIV | Jarvan IV | Q → E → R | shred Q→E/R | CERTIFIED | Q row: "armor reduction" (10-26%) for 3s; shred first correct (E→Q knockup CC is not a damage constraint)
Jax | Jax | Q → W → E → R | none | CERTIFIED | Q/W/E/R plain; R active swing; no consume rows
Jayce | Jayce | R → Q → W (Cannon); R → Q → W → E (Hammer) | shred R→Q/W | CERTIFIED | see gap section (certified CAST_ORDER completeness)
Jhin | Jhin | Q → W → E → R (seed) | none | CERTIFIED | seed anchored on P 4th-shot missing-health bonus; R barrage last
Jinx | Jinx | Q → W → E → R | none (miss: R execute) | CERTIFIED (minor) | R row: "bonus damage based on the target's missing health" (Max/Min attrs) — not flagged; R last anyway
KSante | K'Sante | Q → W → E → R | none | CERTIFIED | Q applies marks consumed by P (`p_marks`); P is not a cast slot; Q-first order fine; Q cooldown degraded (0.0) in packet but order unaffected
Kaisa | Kai'Sa | W → Q (certified) | none | CERTIFIED | see gap section (certified CAST_ORDER completeness)
Kalista | Kalista | Q → E | stack_consume Q→E | CERTIFIED | E row: "basic attacks on-hit and Pierce apply a stack of Rend ... consuming the stacks" — Q→E correct

## 2. F4 gap-row section (9 rows in this batch)

### 2.1 Brand — Blaze multi-consume → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Engine output: seed order `Q → R → E → W`; `setup=('Q','R','W')`, `consume=('E')`; **edge detector emits zero edges**.
- Sourced rows: P: "Brand's abilities apply a stack of Ablaze ... stacking up to 3 times"; "Upon applying 3 stacks of Ablaze ... **consumes their stacks to explode**" (`Max Health Damage` 40-entry array + 2%/100 AP); W: "Ablaze Bonus: The target takes 25% increased damage" (`Increased Damage` 93.75-318.75); E: "Ablaze Bonus: Conflagration's spread range is doubled" — E **spreads, never consumes**.
- Verdict: order is semantically valid (Q/R apply Ablaze; W's 25% Ablaze bonus lands on an ablaze target; E spreads to surroundings; P detonates at 3 stacks). The machine-readable `consume=('E')` is a **mislabel** — the real consumer is P (passive, not a cast slot), so the seed's setup/consume receipt cannot be reproduced by the detector (seed tests skip the receipt-vs-edges check). This is a documented override behaving as designed; the mislabel is cosmetic but should be fixed.
- Smallest fix: change the seed's `consume` to `()` (or `("P",)`) and keep the rationale sentence "E spreads Blaze (P detonates at 3 stacks)" verbatim; optionally teach the detector a `P-consumer` receipt field.

### 2.2 Briar — Q shred + W execute agreement → **CERTIFIED**
- Engine output: `Q → E → R → W`; edges: execute Q/E/R→W, shred Q→W/E/R.
- Sourced rows: Q "reduces their armor and magic resistance for 5 seconds" (`Resistances Reduction` 10-20%); W Snack Attack "Bonus Damage ... % (+ 2.5% per 100 bonus AD) of the target's missing health" (`Bonus Damage` 9% + units); W2 requires the frenzy (`blood_frenzy_active` option, R re-triggers).
- Verdict: Q-first (shred) and W-last (missing-health execute) are exactly the sourced semantics; E/R between are DPS-ranked. Rationale sentences are clunky but factually accurate. No fix needed.

### 2.3 Caitlyn — W trap/Headshot → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Engine output: `Q → W → E → R`, no edges, "flat kit" rationale.
- Sourced rows: W "Headshot Damage Increase" (35/80/125/170/215 + 30% bonus AD); P "Enemies that step over a Yordle Snap Trap ... can grant an additional Headshot ... without consuming stacks"; module prices the trap Headshot through P (`w_traps` option, capped by "Maximum Number of Traps"), W itself is a zero-damage utility row (root+reveal).
- Verdict: the trap→Headshot synergy is real and **modeled in damage**, but P is not a cast slot, so no rotation-order edge exists; the "flat kit" claim is accurate for cast slots. Order Q→W→E→R is a valid permutation and not semantically wrong. The F3 row's concern is resolved by the module design; no resolver fix needed.

### 2.4 Darius — E shred + Hemorrhage agreement → **ENGINE BUG** (edge detector; derived order itself correct)
- Engine output: `E → Q → W → R`; edges include a **spurious** `stack_consume E→R` with cite "R attribute 'damage per stack' consumes stacks; **E stat_buff(armor_penetration_percent) applies them**", and the receipt lists E in `setup` as a stack applier.
- Sourced rows: P "Darius' **damaging** basic attacks and abilities apply a stack of Hemorrhage"; E (Apprehend) active "pulls enemies ... slowed by 40%" — **no damage attribute, no stack application**; only E's passive "Armor Penetration" (20-40%). The module itself documents "E ... applies NO bleed stack" (`applies_dot_stack` deliberately absent). R "Bonus Damage Per Stack" (25/50/75) + "increased by 0% : 100% (based on target's Hemorrhage stacks)".
- Root cause: `detect_setup_consume_edges` — `_P_PASSIVE_ABILITIES_APPLY` (`r"abilit(y|ies).{0,80}apply a stack of X"`) matches P's phrase and then `applies_condition(slot,"stack")` returns True for **every** slot, including zero-damage E (the cd-0 guard doesn't catch a 26s-CD zero-damage row).
- Verdict: order `E→Q→W→R` is semantically correct (E's armor pen opens; Q/W apply stacks; R's per-stack damage closes), so the *agreement* holds — but the edge detector contradicts the sourced data and pollutes the rationale/receipt.
- Smallest fix: in `applies_condition`, before the `passive_applies` shortcut, require `_is_damage_row(info)` (raw>0 or parts) for cast slots — the same guard already used for the execute fan-out.

### 2.5 Gnar — Rage Gene/form → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Engine output: Mini `Q → W → E` (R correctly absent — Mega-only, module: "R (GNAR!) is Mega-only: Mini form emits nothing"); Mega `Q → W → E → R`.
- Sourced rows/atoms: Rage Gene is a passive stat transition (`GnarTransform`, `GnarFuryGeneration`, `gnar Passive (Rage Gene)` atoms — stack-transform-summon-resource family), not an order constraint; `mega`/`q_pickup`/`r_wall` options dispatch the forms; R "Increased Damage" (wall, 1.5x) read via `r_wall`.
- Verdict: per-form orders are valid permutations; the engine cannot model the mid-fight form transition cadence (100 Rage → transform), which is a state machine, and it says so via the option design. Honest limitation.
- Small nit: the flat-kit rationale text claims the "certified module order Q → Q2 → W → E → R is kept exactly" while the actual order is `Q → W → E` (absent slots dropped) — generic fallback text; recommend the rationale echo the actual slot list.

### 2.6 Hwei — missing-health Q → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Engine output: `R → Q → W → E`; edge `execute R→Q` ("Q is a missing-health/stored execute — after R's damage").
- Sourced rows: Q "Severing Bolt": "deals increased damage based on the target's missing health" (`Maximum Damage Increase` 200-350; `Maximum Damage` 120-560); R "Spiraling Despair" DoT aura + explosion (`Maximum Total Damage` 230-540) — R first maximizes aura ticks.
- Verdict: for the missing-health Q variant (q_variant=1), Q-after-R is correct; the edge is driven by the `q_missing_health` option, which the module gates to variant 1 while the resolver applies it to the **default** variant 0 (Devastating Fire — "target-max-health scaling", per module detail). The mislabel is harmless for the default variant's order (R→Q→W→E is still a sane damage order), but the edge is variant-coupled.
- Smallest fix: in `_resolve_option_slot`, scope `q_missing_health` to `q_variant == 1` (return None otherwise), or document the variant coupling in the rationale.

### 2.7 Illaoi — E spirit/vessel → **CERTIFIED WITH DOCUMENTED LIMITATION**
- Engine output: `Q → W → E → R`, no edges, "flat kit" rationale.
- Sourced rows: E "pulling their Spirit out ... redirects a portion of the pre-mitigation damage received" (`Damage Transmission` 25-45%); "marking the target as a Vessel ... Each Tentacle autonomously attacks the closest Vessel or Spirit ... once every 4.5/4/3.5 (based on level) seconds"; P "Tentacles are commanded to attack by Illaoi's abilities"; atoms: `IllaoiTentacleHeal`, `illaoi Passive (Tentacle)` (summon family).
- Verdict: spirit/vessel is target-state + summon machinery, not a cast-order constraint among Q/W/E/R; the module explicitly documents E as a no-damage row ("Spirit health/armor/magic-resist redirection and Vessel spawning are target-state branches") and prices tentacle slams via the `p_tentacles` option. The engine is honest ("no setup/consume signal" is true for cast slots). No fix needed.

### 2.8 Jayce — certified CAST_ORDER completeness → **CERTIFIED**
- Engine output: Cannon `R → Q → W`, Hammer `R → Q → W → E`; certified `CAST_ORDER = ["R","Q","Q2","W","E"]`; edges shred R→Q/W.
- Sourced rows: R (Cannon) "empowering his next basic attack to reduce the target's armor and magic resistance by 20% / 25% / 30% / 35% (based on level) for 5 seconds" — R-first is correct; module ASSUMPTIONS document the transform-first combo and that the cross-stance burst is not modeled.
- Verdict: the certified order is complete for the module's stance-at-a-time model; `Q2` is a **phantom slot** (module `SLOTS` has no Q2 — it is never parsed, so the derivation's "permutation of present slots" trivially preserves certified relative order); cannon E emits nothing (gate utility). Derived orders are valid subsequences of the certified order. No order error; note `Q2` should be dropped from `CAST_ORDER` or a real `Q2` slot added.

### 2.9 Kai'Sa — certified CAST_ORDER completeness → **CERTIFIED**
- Engine output: `W → Q` (certified kept), no edges, "flat kit" rationale.
- Sourced rows: W "applies 2 Plasma" (3 evolved, "requires 100 ability power ... refunds 75% of its cooldown"); module `CAST_ORDER = ("W","Q")` with `CUSTOM_CAST_ORDER_UNAVAILABLE_REASON` ("Plasma resolves before the volley") and W-impact-delayed Q hit offsets; E (Supercharge) and R (Killer Instinct) are non-damaging, so W/Q are the complete damaging cast set; Plasma detonation is P-driven (5 stacks, `plasma_starting_stacks` option).
- Verdict: certified order is complete and semantically correct (W applies Plasma before Q's volley). Nit: the resolver's "no setup/consume signal" rationale is technically true for cast slots but Plasma *is* a stack system; the module-level documentation covers it. No fix needed.

## 3. Non-gap issues (orders correct, detector/rationale completeness)

1. **Anivia — chilled-consume edge missed (detector bug).** E's "Enhanced Damage" (110-310, "doubled if they were Chilled") is a structured consume row, and E's own passive effect says "Enemies hit by Flash Frost ... become Chilled" — the named-applier scan `_P_NAMED_APPLIER_COND` matches this phrase but only runs for `stack_consume`/`detonation_consume`/`mark_consume` roles, never `enhanced_consume`. Order Q→E→R is already correct. Smallest fix: run the named-applier scan for `enhanced_consume` too.
2. **Missing-health executes hidden by attribute names (Garen R, Jinx R, Akali R2, Draven R threshold).** All four have sourced missing-health/execute rows whose *attribute names* lack the literal "missing" (Garen R "True Damage" modifier units "% of target's missing health"; Jinx R "Maximum/Minimum Physical Damage" + "bonus damage based on the target's missing health"; Akali R2 "Minimum/Maximum Magic Damage" + "increased by 0%:200%"; Draven R execute below Adoration threshold). The detector gates on attribute-name keywords, so these edges are missed — every affected order still places R last, so no order is wrong; the "flat kit" rationales are overstated.
3. **Fiora — R priced 0 at baseline.** Grand Challenge vitals are option-gated (`p_vitals`); the in-game R-first opener (vitals before Q/W/E hits) is unmodeled in the rotation order. Order placement is immaterial at raw 0; flagging as a model gap, not an order error.
4. **Irelia — E→Q mark reset unmodeled.** E marks+stuns and Q resets on marked targets (cooldown cadence), not a damage-amp edge; default Q-first order is not clearly wrong but the E-before-Q cadence is unmodeled.
5. **Azir — Q-first assumes a pre-existing soldier.** Module documents "one damage instance per cast regardless of soldier count" with soldier autos on the auto stream (`soldier_autos`); W placement order is immaterial in the model. In-game Q-before-W does nothing; the model's implicit pre-state makes the order consistent.
6. **Cassiopeia seed W→E exception** is the F2-documented seed deviation (W also applies poison; seed casts E first for cadence) — context, not a defect.
7. **Rationale cosmetics:** flat-kit rationales say the "certified module order ... is kept exactly" even when absent slots are dropped (e.g., Gnar Mini `Q,W,E` vs `Q,Q2,W,E,R`); the generic text should echo the actual slot list.
8. **K'Sante Q cooldown degraded** (0.0 in the packet; JSON stores "3.5 : 2 (based on bonus resistances)" in units) — Q drops out of DPS ranking and castability gates; order unaffected but the DPS signal for Q is lost.

## 4. Overall verdict

All 58 derived orders are **valid permutations of the parsed meaningful slots** (no invented/dropped slots; option-gated slots handled per form/stance). **Every gap-row order in this batch is semantically sound** against the sourced wiki rows and atoms. Two detector-level defects were confirmed (Darius spurious E stack edge; Anivia chilled-consume miss) and a cluster of attribute-name-gated execute misses (Garen/Jinx/Akali/Draven) — none of them changes a derived order, because the default/certified base orders already place those executes last. No `NEEDS ATOM/OVERRIDE` findings: where the engine cannot model a relationship (Caitlyn trap-Headshot, Brand P detonation, Illaoi spirit/vessel, Gnar form transition, Hwei variant gating, Kai'Sa Plasma), the module documentation and option system are explicit about it.

F4_SUMMARY: assigned=58; certified=52; limitation=5; needs_fix=0; engine_bug=1; gap_rows_reviewed=9; non_gap_issues=8
