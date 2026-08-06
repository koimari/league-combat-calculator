# F4 — Independent semantic verification (beta batch, 58 champions)

Branch `codex/deep-audit-2026-08` @ `c8bb082` (HEAD verified, no remote ops, no source edits).
Resolver entry: `resolve_cast_order` at baseline level 11, no items (`data/champions.json` cache,
`data/atoms/*.atoms.json`, champion modules in `src/calculator/champions/`).
Method: programmatic run of the F3 derivation for every assigned champion; every order checked
for (a) valid permutation of the parsed cast slots, (b) edge-direction consistency
(applier before consumer), (c) agreement with typed atoms + explicit wiki rows (not prose
inference). All 58 orders are valid permutations; 0 order-vs-edge violations.

Edge kinds observed in this batch: `shred`, `stack_consume`, `mark_applier`, `mark_consume`,
`execute`, `cc_setup`, `recast` (none in batch), `dot_consume` (none).

## 1. Assigned-champion table

| key | display | derived order | edge kinds | verdict | evidence (local source) |
|-----|---------|---------------|------------|---------|-------------------------|
| Karma | Karma | Q, W, E, R | — | **NEEDS ATOM/OVERRIDE** | R (Mantra) is a cast slot (cd 38) cast LAST; wiki R row: "Karma empowers her next basic ability within 8 seconds for an additional effect" — Mantra must precede the empowered ability. No empower atom exists. |
| Karthus | Karthus | W, Q, E, R | shred | CERTIFIED | certified `CAST_ORDER ("W","Q","E","R")` (karthus.py) reproduced; W `target_debuff mr_reduction_percent=25` sourced from wiki W description "inflicted with 25% magic resistance reduction"; shred edges W→Q/E/R agree. |
| Kassadin | Kassadin | Q, W, E, R | — | CERTIFIED | flat kit, no typed consume/shred atom in rows; base order honest (Riftwalk spam row carries no cross-slot setup). |
| Katarina | Katarina | Q, W, E, R | — | CERTIFIED | W row has only "Bonus Movement speed" (no Magic Damage attribute) — module's zero-damage W is faithful to the pinned wiki. |
| Kayle | Kayle | Q, W, E, R | — | CERTIFIED | flat kit; E active missing-health rider is on the auto slot (self), no cross-slot consumer. |
| Kayn | Kayn | Q, W, E, R | — | CERTIFIED | flat base order; `form` options (base/darkin/shadow_assassin) re-priced Q/R but preserve order in all three variants (verified). |
| Kennen | Kennen | Q, W, E, R | — | CERTIFIED WITH DOCUMENTED LIMITATION (gap row 3) | P row: "Kennen's abilities apply a stack of Mark of the Storm to enemies hit"; W active detonation is prose-only ("deals magic damage to all nearby enemies afflicted by Mark of the Storm"); atom `stack-transform-summon-resource.mark KennenMarkOfStorm` exists on passive only — no `mark_detonate` atom on W. Order Q→W is compatible; edge unmodeled. |
| Khazix | Kha'Zix | Q, W, E, R | — | CERTIFIED | flat kit; `q_isolated` is a self-condition option (correctly excluded). |
| Kindred | Kindred | Q, W, E, R | — | CERTIFIED | W (Wolf's Frenzy) is a cd-0 zone row — correctly not a cast endpoint; E self-stack pounce ("the pounce consumes all stacks") is a self-edge, correctly excluded. |
| Kled | Kled | Q, W, E, R | — | CERTIFIED | flat kit; W is the auto-stream 4th-hit row (cd 0), correctly not a setup endpoint. |
| KogMaw | Kog'Maw | Q, W, E, R | shred | CERTIFIED | Q `target_debuff armor_reduction_percent=24, mr_reduction_percent=24` → shred edges Q→E/R; W on-hit row is auto-stream (module: "W assumed always active"). Q-first shred is correct. |
| Leblanc | LeBlanc | Q, W, E, R | mark_applier, mark_consume | CERTIFIED | Q `q_consume` sigil option + Q corpus "phrase:marks-target" → Q→W/E mark_applier; R consumes the mark (mark_consume Q→R). Q-first correct. |
| LeeSin | Lee Sin | Q, W, E, R | — | CERTIFIED | flat kit; Q two-stage recast rides the same slot (self). |
| Leona | Leona | Q, W, E, R | — | CERTIFIED | flat kit; Q/E/R control metadata not authored as cc_kind on parts, so no cc_setup edges — order stays honest base. |
| Lillia | Lillia | Q, W, E, R | — | CERTIFIED | flat kit; sleep/drowsy state is control state, no typed consume atom. |
| Lissandra | Lissandra | Q, W, E, R | — | CERTIFIED | flat kit. |
| Locke | Locke | Q, W, E, R | — | CERTIFIED | flat kit; `soul_nails` self-stack option correctly excluded (closed vocabulary). |
| Lucian | Lucian | Q, W, E, R | — | CERTIFIED | flat kit. |
| Lulu | Lulu | Q, W, E, R | — | CERTIFIED (gap row: coverage-only) | atoms present (22, full provenance); Q/E are the damage slots, W/R zero-damage rows; honest flat order. |
| Lux | Lux | E, Q, R, W | mark_consume | CERTIFIED | documented COMBO_TABLE override (derived=False); E slow → Q root → R consumes P Illumination (`p_illumination_procs`); semantics agree with the P "Illumination" mark rows. |
| Malphite | Malphite | Q, W, E, R | — | CERTIFIED (gap row: coverage-only) | atoms present (34, full provenance); flat kit; R-engage opener is a human pattern, but Q-poke-first is not semantically wrong for a 1-rotation practice sequence. |
| Malzahar | Malzahar | Q, W, E, R | — | CERTIFIED | flat kit; E DoT has no cross-slot consumer (W voidling row has no consume atom), so no reorder is derivable. |
| Maokai | Maokai | Q, W, E, R | — | CERTIFIED | flat kit. |
| MasterYi | Master Yi | Q, W, E, R | — | CERTIFIED | flat kit; E (Wuju Style) is a self-buff without a damage-amp stat_buff key — no buff edge; order acceptable. |
| Mel | Mel | Q, W, E, R | stack_consume | CERTIFIED | `r_overwhelm_stacks` option → R consumes Overwhelm stacks applied by Q/W/E (`phrase:applies-stack` + E dot); R last is the correct execute-after-stacks order. |
| Milio | Milio | Q, W, E, R | — | CERTIFIED | support kit; W/E/R zero-damage rows; Q is the only damage cast. |
| MissFortune | Miss Fortune | Q, W, E, R | — | CERTIFIED | flat kit; E slow row sits directly before R in base order — consistent with the real E→R cadence. |
| MonkeyKing | Wukong | Q, E, R | shred | CERTIFIED | Q `target_debuff armor_reduction_percent=30` → shred edges Q→E/R; W (Decoy) zero-damage row excluded; DPS tie-break consistent across the matrix. |
| Mordekaiser | Mordekaiser | Q, W, E, R | — | CERTIFIED | flat kit; E pull has no cc_kind atom, so no cc_setup edge; order acceptable. |
| Morgana | Morgana | Q, W, E, R | — | CERTIFIED | flat kit; Q root before W pool in base order — matches the real bind→pool pattern. |
| Naafiri | Naafiri | Q, W, E, R | — | CERTIFIED WITH DOCUMENTED LIMITATION (gap row 5) | Q rows: "Bleed Physical Damage per Tick" + "Minimum/Maximum Bonus Physical Damage" + "Darkin Daggers can be recast at no additional cost"; module option `q_recast`; atom `NaafiriQBleed`. Recast is self-slot — no cross-slot edge can exist; Q-first is correct. |
| Nami | Nami | Q, W, E, R | — | CERTIFIED | flat kit. |
| Nasus | Nasus | Q, W, E, R | — | **NEEDS ATOM/OVERRIDE** | E (Spirit Fire) wiki row carries unconditional "Armor Reduction 30/35/40/45/50% of target's armor" ("inflicting them with armor reduction, lingering for 1 second") — NOT gated by any self-resource. Module parse drops it (no `target_debuff` on E), so the derived order puts the shredder after Q. |
| Nautilus | Nautilus | Q, W, E, R | — | CERTIFIED (gap row: coverage-only) | atoms present (34, full provenance); flat kit; Q-anchor-first is the correct opener. |
| Neeko | Neeko | Q, W, E, R | — | CERTIFIED | flat kit; Q re-bloom is self-conditional (module assumes both re-blooms fire). |
| Nidalee | Nidalee | W, E, Q, R | execute | CERTIFIED WITH DOCUMENTED LIMITATION (gap row 6) | W trap first + Q last is coincidentally the correct form-swap burst (trap → cougar execute), but the driver is a variant misattribution: the execute cite comes from the cougar Takedown row ("Prowl-Enhanced Minimum/Maximum Damage", "based on the target's missing health") while the modeled packet is human Javelin Toss. Hunted→cougar-Q edge unmodeled ("using Pounce's Hunted bonus" is in the W Pounce row; trap atoms `Bushwhack` exist). |
| Nilah | Nilah | Q, W, E, R | — | CERTIFIED | flat kit. |
| Nocturne | Nocturne | Q, W, E, R | — | CERTIFIED | flat kit. |
| Nunu | Nunu & Willump | Q, W, E, R | — | CERTIFIED | flat kit; W snowball-engage is a human pattern, not a typed setup. |
| Olaf | Olaf | Q, W, E, R | — | CERTIFIED | flat kit. |
| Orianna | Orianna | Q, W, E, R | — | CERTIFIED | flat kit; Q ball-reposition-first is correct. |
| Ornn | Ornn | Q, W, E, R | — | CERTIFIED | flat kit; Q-pillar→E knockup is prose-only (no typed atom), order acceptable. |
| Pantheon | Pantheon | W, E, R, Q | cc_setup, execute | CERTIFIED | W `cc_kind` stun → W before Q/E/R; Q missing-health execute → after W/E/R. Derived W→E→R→Q matches the real stun→burst→execute pattern. |
| Poppy | Poppy | Q, W, E, R | — | CERTIFIED (gap row: coverage-only) | atoms present (31, full provenance); flat kit. |
| Pyke | Pyke | Q, W, E, R | — | CERTIFIED | flat kit; R execute lands last by base position (module prices non-execute damage; no execute edge needed). |
| Qiyana | Qiyana | Q, W, E, R | — | CERTIFIED | flat kit; W is authored as an on-hit row (element on-hit) rather than a cast — order unchanged. |
| Quinn | Quinn | Q, W, E, R | — | CERTIFIED | flat kit; Q blind first is correct. |
| Rakan | Rakan | Q, W, R | — | CERTIFIED | E (Battle Dance) zero-damage row excluded; Q→W→R flat order fine. |
| Rammus | Rammus | Q, W, E, R | — | CERTIFIED | flat kit; Q Powerball-first correct. |
| RekSai | Rek'Sai | Q, W, E, R | — | CERTIFIED | flat kit; E fury bite is a self-resource variant (fury 0/100 priced), no cross-slot edge. |
| Rell | Rell | Q, W, E, R | — | CERTIFIED | pinned wiki Q row has only "Magic Damage" (no shred attribute in local data) — module faithful; Q-first fine. |
| Renata | Renata Glasc | Q, W, E, R | — | CERTIFIED | flat kit. |
| Renekton | Renekton | Q, W, E, R | — | CERTIFIED WITH DOCUMENTED LIMITATION (gap row 17) | E "Armor Reduction 25–35%" is under "Reign of Anger Bonus: Dice, the recast ... inflicts armor reduction" — fury-gated, so the closed-vocabulary exclusion is CORRECT; Enhanced Damage rows are fury-gated too. Flat base order is honest. |
| Rengar | Rengar | Q, W, E, R | — | CERTIFIED | flat kit; ferocity is a self-resource option. |
| Riven | Riven | Q, W, E, R | — | CERTIFIED | flat kit; R (wind slash, cd-0 row) last is the correct execute position. |
| Rumble | Rumble | Q, W, E, R | — | **NEEDS ATOM/OVERRIDE** (gap row 17) | E (Electro Harpoon) wiki row carries NON-heat-gated "Magic Resistance Reduction 10/12/14/16/18%" ("inflicting them with magic resistance reduction for 4 seconds ... stacking up to 2 times"; the "Enhanced MR Reduction 15–27%" is the heat-gated part). Module parse drops the base shred entirely (no `target_debuff` on E), so the derived flat order puts the MR shredder third, after Q. |
| Ryze | Ryze | E, Q, W, R | mark_applier | CERTIFIED | E corpus "consumes the mark" + "phrase:marks-target" → E→Q/W/R mark_applier; DPS tie-break consistent across the matrix. E-flux-first is the correct Ryze pattern. |
| Samira | Samira | Q, W, E, R | — | CERTIFIED | flat kit; R-last coincides with the real S-rank gate (module does not model the style rank, but the position is right). |

Counts: 51 CERTIFIED · 4 CERTIFIED WITH DOCUMENTED LIMITATION · 3 NEEDS ATOM/OVERRIDE · 0 ENGINE BUG.

## 2. F4 gap-row verdicts (assigned batch)

### G1. Kennen — P mark → W detonate (F3 row 3) — **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q, W, E, R`, no edges. Local evidence: P row "Innate: Kennen's abilities apply a stack of Mark of the Storm to enemies hit."; W active description "deals magic damage to all nearby enemies afflicted by Mark of the Storm or within Slicing Maelstrom." (prose — no typed attribute); atoms contain `stack-transform-summon-resource.mark KennenMarkOfStorm` (passive) but **no W detonate atom**.
- The relationship is real but unmodeled; the derived order is *compatible* (Q applies marks, W detonates) and the engine's rationale is honest ("no setup/consume signal").
- Smallest fix: add a `mark_detonate` atom on W's active citing the W active description. The existing passive-applies mechanism (`abilities apply a stack of X` → every slot applies marks) would then produce Q/E/R → W edges automatically.

### G2. Naafiri — Q bleed self-recast (F3 row 5) — **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q, W, E, R`, no edges. Local evidence: Q rows "Bleed Physical Damage per Tick", "Minimum/Maximum Bonus Physical Damage"; blurb "Darkin Daggers can be recast at no additional cost."; module option `q_recast` ("Q recast hits the bleeding target (bonus damage + heal)", default true); atom `NaafiriQBleed` (DoT).
- The recast consumes Q's own bleed on the **same slot** — a self-edge the resolver's `add()` correctly cannot express as a cross-slot constraint; Q-first is semantically right.
- Smallest fix: register `q_recast` in the closed vocabulary as a documented self-consume (or add a `q_bleed_recast` recast atom) so the receipt's sources cite it; no order change.

### G3. Nidalee — W trap Hunted → cougar Q (F3 row 6) — **CERTIFIED WITH DOCUMENTED LIMITATION** (with a rationale caveat)
- Derived: `W, E, Q, R`; edges: Q execute after W/E. Local evidence: W Pounce row "using Pounce's Hunted bonus will reduce Pounce's cooldown" (Hunted is named only in the W slot); Q Takedown row carries "Prowl-Enhanced Minimum/Maximum Damage" and "based on the target's missing health"; trap atoms `Bushwhack`/`BushwhackDamage` exist; `Takedown`/`NidaleeCougarTakedownAttack` (transform) atoms exist.
- The order is *coincidentally* the correct form-swap burst (trap first, cougar execute last), but the driving cite is a **variant misattribution**: the "missing-health execute" edge is read from the cougar Takedown attribute rows while the modeled Q packet is human Javelin Toss (q_variant=0). The actual Hunted→Prowl-Enhanced relationship is unmodeled.
- Smallest fix: author a Hunted mark atom pair — Bushwhack applies "Hunted" (`phrase:marks-target`-style typed mark) and cougar Q consumes it ("Prowl-Enhanced" rows) — giving an explicit W→Q edge; also scope the execute cite to the cougar variant so the rationale names the modeled packet.

### G4. Karthus — certified CAST_ORDER completeness (F3 row 8) — **CERTIFIED**
- Derived `W, Q, E, R` reproduces the certified `CAST_ORDER ("W","Q","E","R")` (karthus.py). Local evidence: W wiki description "Enemies that touch the wall are inflicted with 25% magic resistance reduction"; module authors `target_debuff mr_reduction_percent=25` (wall_contact option) → shred edges W→Q/E/R. Order, edge, and certification all agree.

### G5. Renekton — self-resource amp (F3 row 17a) — **CERTIFIED WITH DOCUMENTED LIMITATION**
- Derived: `Q, W, E, R`, no edges. Local evidence: Q "Enhanced Damage"/"Enhanced Healing" rows and E "Reign of Anger Bonus: Dice, the recast ... inflicts armor reduction" (Armor Reduction 25–35%) are **fury-gated**; the closed-vocabulary `_P_SELF_RESOURCE` exclusion is therefore correct. Flat base order is honest.
- Optional follow-up (as F3 says): a self-resource AMP atom (fury threshold) if the engine should order around empowered casts.

### G6. Rumble — self-resource amp (F3 row 17b) — **NEEDS ATOM/OVERRIDE**
- Derived: `Q, W, E, R`, no edges. Local evidence: E (Electro Harpoon) base row — "inflicting them with magic resistance reduction for 4 seconds and slowing them ... stacking up to 2 times" with **non-heat-gated** "Magic Resistance Reduction 10/12/14/16/18%" (the "Danger Zone Bonus" *Enhanced* MR Reduction 15–27% is the heat-gated part). The module parse drops the base shred (`E` has no `target_debuff`), so the derived order places the MR shredder third.
- This is beyond the documented heat limitation: the *base* shred is a real cross-slot setup and should produce shred edges E→Q/R.
- Smallest fix: author `target_debuff {mr_reduction_percent: 10–18, stacks: 2}` on Rumble E in the packet module (wiki "Magic Resistance Reduction" + "Total MR Reduction" rows) → order becomes E, Q, W, R.

### G7–G10. Nautilus / Lulu / Malphite / Poppy — module-coverage-only (F3 row 19) — **CERTIFIED**
- All four have custom modules (`reviewed_module` status), atom files with full binary/wiki provenance (34/22/34/31 atoms), and honest flat-kit derivations (`Q, W, E, R`). No typed setup/consume signal exists in their local rows; no order is contradicted by the data. Malphite's classic R-engage opener is a human pattern, not a data signal — not an error.

## 3. Non-gap issues (new F4 findings)

1. **Karma — NEEDS ATOM/OVERRIDE (order semantically wrong).** R (Mantra) is a cast slot (cd 38, zero damage) placed **last** in `Q, W, E, R`. Local evidence: R row "Active: Karma empowers her next basic ability within 8 seconds for an additional effect."; module Q detail "Mantra Soulflare field/detonation is included only when the explicit Mantra toggle is on." Mantra must precede the ability it empowers; R-last means the modeled rotation empowers nothing. Smallest fix: a mantra/empower atom (R → next Q/W/E buff edge) or a documented override `R, Q, W, E`. Karma is absent from the F3 gap list — the derivation cannot see her because R carries no damage-amp stat_buff and the empower relation is prose.
2. **Nasus — NEEDS ATOM/OVERRIDE (order semantically wrong).** E (Spirit Fire) carries unconditional "Armor Reduction 30/35/40/45/50% of target's armor" ("...inflicting them with armor reduction, lingering for 1 second") in the wiki rows; `nasus.py::_spirit_fire` does not author `target_debuff`, so no shred edge exists and the derived order puts E third (`Q, W, E, R`). In League the shred opens the Q/auto burst (E → Q). Smallest fix: add `target_debuff {armor_reduction_percent: 30–50}` to `_spirit_fire` → shred edges E→Q/W/R → order E, Q, W, R.
3. **Nidalee rationale misattribution (order OK).** See G3 — the execute cite names a cougar-variant row while the modeled packet is human Q. Recommendation: scope the corpus/execute read to the active variant or cite both.
4. Minor observations (order acceptable, not defects): Leona (E-engage-before-Q is the human order; cc_kind not authored on Q/E/R — no cc_setup edges); Ornn (Q-pillar→E knockup is prose-only); Malzahar (E-DoT-first human opener; no consumer atom); Master Yi (E true-damage buff before Q is the human pattern; no stat_buff key); Kindred (W zone is a cd-0 row; real W→Q cadence unmodeled); Nunu (W snowball-engage unmodeled). Rell Q and Katarina W were checked against the pinned wiki and are **faithful** (no shred attribute / no damage attribute in local data) — no action.

## 4. Overall verdict

The F3 algorithmic derivation is sound on the mechanics it can see: 51/58 assigned champions certify against the typed atoms + explicit wiki rows, including all edge-bearing kits in this batch (Karthus, Kog'Maw, LeBlanc, Lux, Mel, Wukong, Pantheon, Ryze) — no order-vs-edge violations and no engine-bug contradictions were found in the assigned roster. The documented limitations (Kennen mark-detonate, Naafiri self-recast, Nidalee Hunted, Renekton fury) are honestly reported by the engine. However, three kits produce **semantically wrong derived orders** because module parses dropped typed wiki attributes (Rumble E base MR shred, Nasus E armor shred) or because a cast slot with a setup role is ordered after its consumer (Karma R Mantra) — two of these (Karma, Nasus) are absent from the F3 gap list and must be added. All three fixes are small, local, and source-backed.

F4_SUMMARY: assigned=58; certified=51; limitation=4; needs_fix=3; engine_bug=0; gap_rows_reviewed=10
