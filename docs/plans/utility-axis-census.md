# Utility-axis census

Every champion slot the contracts report `out_of_scope`, classified by primary
mechanism and mapped to the engine home that already exists. Read-only measurement
for plan decision 8 (`docs/plans/2026-08-20-coverage-frontier-campaign.md`).
Machine twin: `docs/plans/utility-axis-census.json`.

150 slots are `out_of_scope`; 14 belong to unit E (below); **136 rows here**.

`out_of_scope` is the *default* for any slot absent from a module's `SLOTS` map
(`champions/module_contract.py:33`), not an authored claim that the engine lacks an
axis. Nine rows below are already modelled through another channel.

## 1. Mechanisms and their engine homes

| Mechanism | Slots | Engine home today |
|---|---|---|
| `aura_or_stat` | 35 | `champions/slotlib.py:878` `stat_buff` -> dispatch `damage.py:2739-2821`; **no movement-speed key** |
| `other` | 14 | varies - see the note column |
| `cc_only` | 11 | `ability_spec.py:382` `CC_KIND_VOCABULARY` - a marker only, consumed by `damage.py:1962` |
| `self_shield` | 11 | `champions/slotlib.py:581` `attach_self_shield` (needs a damage event to ride) -> `shield_ledger.py:207` |
| `damage_rider` | 10 | the damage engine itself - these belong with unit E, not the utility axis |
| `self_heal` | 10 | `champions/healing_contract.py:49` -> resolvers in each `champions/<name>.py` (`derive_self_healing`, 62 champions), anchors in `healing_helpers.py` |
| `ally_heal` | 7 | `support_effects.py:316` (same scanner; `Heal Per Tick` refused at `:416`) |
| `ally_shield` | 7 | `support_effects.py:316` `derive_ally_effects` (Q/W/E/R only, attributes at `:34`) |
| `mobility_only` | 7 | none |
| `resource_or_cooldown` | 6 | none for champions (`roster_composition.py:298` is item mana only) |
| `vision_or_utility` | 6 | none |
| `summon_or_pet` | 5 | none - per-champion constants + a count option (`champions/annie.py:136`) |
| `transform_or_form` | 3 | no abstraction; a per-champion option (`champions/gnar.py:84`, variants `packet_module.py:687`) |
| `death_or_revive` | 2 | `defensive_effects.py:398` `_champion_starting_revive` (module `starting_revive_defense`) |
| `enemy_projectile_or_reflect` | 2 | none |

`other` is: damage_reduction 5, terrain 2, attachment 1, copies_ultimate 1, disguise 1, experience 1, invulnerability 1, no_effect 1, shop 1. None of them has any engine surface.

## 2. Cheapest first

| # | Slice | Slots | Why it is where it is |
|---|---|---|---|
| 1 | **Already modelled through another channel - re-source the label, write no code** | 9 | Aatrox E, Anivia P, Blitzcrank P, Camille P, Milio R, Morgana P, Taric Q, Zac P, Zilean R. Runtime probe: revive_health_amount 2814.0 Anivia / 1619.0 Zac / 1100.0 Zilean; self_healing sources Umbral Dash, Soul Siphon, Starlight's Touch, Breath of Life; Blitzcrank P and Camille P author `self_shield_events`. |
| 2 | **The ally-support scanner already emits a packet - verify and pin (two are wrong)** | 9 | Milio W, Milio E, Riven E, Rumble W, Seraphine W, Sivir E, Sona W, Thresh W, Yuumi E. `derive_ally_effects` probe at level 18: Riven E shield 170.0 self, Thresh W shield 130.0, Sivir E heal 81.6, Seraphine W shield 140.0, Sona W shield 105.0, Milio W heal 150.0 / E shield 165.0, Yuumi E shield 165.0, Rumble W shield 145.0 (mis-scoped). |
| 3 | **Scanner-shaped: the cached row exists and exactly one hook is missing** | 10 | Bard W, Jarvan IV W, Rakan E, Soraka R, Rakan P, Shen P, Yuumi P, Morgana E, Shen R, Taric W. Four need the slot in `SLOTS` (no cast to hang the packet on), three are P slots outside the `Q/W/E/R` loop (`support_effects.py:333`), two use an attribute name absent from `:34`, and Taric W's `% of target's maximum health` resolves to 0.0 and is dropped at `:391`. |
| 4 | **`stat_buff` already dispatches the key the slot needs** | 22 | Tristana Q, Warwick W, Trundle W, Quinn W, Master Yi R, Nocturne W, Twitch Q, Viego E, Olaf P, Olaf R, Miss Fortune W, Lulu W, Lulu R, Singed R, Zaahen P, Renata Glasc W, Naafiri W, Varus P, Swain P, Nunu & Willump P, Rammus P, Rengar R. Every one is an attack-speed, attack-damage or health grant with a cached leveling row; `damage.py:2739-2821` already dispatches `bonus_attack_speed`, `total_attack_speed_percent`, `bonus_attack_damage`, `bonus_health`. Rengar R is a `target_debuff` `armor_reduction_flat` (`champions/engine.py:200`) rather than a self buff. |
| 5 | **Self-heal with a cached row that no healing rule authors** | 6 | Cho'Gath P, Rek'Sai P, Mordekaiser R, Trundle P, Dr. Mundo P, Alistar P. Probe: none of the six appears in `self_healing_events`. Cho'Gath, Rek'Sai and Mordekaiser are absent from `HEALING_RULE_CHAMPIONS` entirely; Trundle, Dr. Mundo and Alistar are in it but the rule body prices only their other slots. |
| 6 | **Damage riders - unit E's lane, not the utility axis** | 11 | Warwick P, Taric P, Sona P, Sylas P, Seraphine P, Shaco P, Miss Fortune P, Milio P, Mel P, Xin Zhao P, Ornn P. Each carries a cached damage row and prices nothing. Probe: Warwick's five autos deal 270.0 physical and 0.0 magic, so Eternal Hunger (6-60.76 +15% bonus AD +10% AP magic on-hit) is missing about as much damage again as the autos themselves. |
| 7 | **Self-shield residue - a home exists but nothing routes to it** | 3 | Vi P, Mordekaiser W, Tahm Kench E. Vi P is exactly the `attach_self_shield` shape (`champions/slotlib.py:581`) on abilities that already emit damage events. Mordekaiser W and Tahm Kench E are grey health, whose primitive lives in `participant_timeline.py` (`GREY_HEALTH_RULE_CHAMPIONS` in `healing.py`) (`GREY_HEALTH_RULE_CHAMPIONS` already lists both champions). |
| 8 | **CC: the marker exists, the magnitude does not** | 11 | Bard R, Kalista R, Nasus W, Rammus E, Renata Glasc R, Singed W, Trundle E, Twitch W, Udyr E, Viktor W, Zilean E. `cc_kind` is one vocabulary string per part with no duration and no percent (`ability_spec.py:457`), so these can be *declared* but never *priced*. A duration and magnitude field comes first. |
| 9 | **No axis at all** | 55 | `aura_or_stat` 15, `other` 13, `mobility_only` 7, `resource_or_cooldown` 6, `vision_or_utility` 5, `summon_or_pet` 4, `transform_or_form` 3, `ally_heal` 1, `enemy_projectile_or_reflect` 1. Movement speed is the largest single group and has no `stat_buff` key at all; mobility, vision/stealth, summons, transforms, damage reduction taken and terrain have no engine surface whatsoever. Each needs a new axis before any slot moves. |

## 3. Asides - things that look wrong today

| Where | What |
|---|---|
| `support_effects.py:316` (Rumble W) | Emits `shield 145.0` scoped `one_teammate`. The cached prose is "Rumble generates 20 Heat to **grant himself** a shield" - a fabricated ally shield, the exact class `_MODULE_AUTHORED_HEAL_SLOTS` (`:158`) was built to stop. |
| `support_effects.py:316` (Mordekaiser W) | Emits `heal 12.0` scoped `one_teammate` from the cached `Heal` row - which is the Potential Shield **decay rate** ("decays by 8-25 by level every second"), not a heal, and Morde's recast heals only himself. |
| `champions/aphelios.py` E | Weapon Queue System is a text prompt with no gameplay effect. Per decision 6 that is `no_damage`, not `out_of_scope`; it is not a missing axis. |
| `MODULE_COVERAGE` vs docstrings | Blitzcrank P and Camille P author `self_shield_events`, Anivia P / Zac P / Zilean R implement `starting_revive_defense`, and Morgana P / Aatrox E / Milio R / Taric Q are healing-rule-owned - all nine still report `out_of_scope`. |
| Docstring says `no_damage`, map says `out_of_scope` | rumble.py:24 "no_damage rows"; nasus.py:20, tristana.py:13, varus.py:22 and morgana.py:14 "zero-damage row(s)"; pantheon.py:18 "a documented no-damage row". Eight slots whose own module contradicts the map. |
| tristana.py:131 | The module's own assumption reads "zero-damage rows; the AS buff is not applied to the auto count" - Rapid Fire's 60-120% attack speed is stated as unpriced, in the file, for a marksman whose whole output is autos. |
| `data/champions.json` attribute names | Dr. Mundo P, Rek'Sai P, Zac P and Tahm Kench E carry heal/regen rows labelled `Max Health Damage`; Jayce P has two duplicate `Hextech Capacitor` entries. |
| `champions/slotlib.py:589` | `attach_self_shield` can only ride an ability that emits a damage event, so a shield-only slot (Vi P, Shen P, Rakan P) has no channel except the ally scanner - which skips P. |

## 4. Unit E's fourteen (excluded)

Samira Q/W/E, Yasuo W/R, Kindred Q/R, Kai'Sa P, Aurelion Sol P/W, Wukong W, Rumble P,
Kog'Maw P, Mel W. (The plan and the frontier page say "ten" and list eleven; the brief
names fourteen. All fourteen are `out_of_scope` today.)

## 5. The slot table (136 rows, sorted by mechanism then champion)

| Champion | Slot | Mechanism | Secondary | Wiki numbers | Engine home | Note |
|---|---|---|---|---|---|---|
| Bard | W | `ally_heal` | `aura_or_stat` | yes | `support_effects.py:316` | Min/Max Heal already overridden (:55) but W is not in SLOTS, so no cast carries it |
| Milio | R | `ally_heal` | - | yes | `healing_contract.py:49` | heal owned by the healing rule; the scanner defers (support_effects.py:158) |
| Milio | W | `ally_heal` | - | yes | `support_effects.py:316` | already emits: heal 150.0 one_teammate (probe) |
| Nilah | P | `ally_heal` | `ally_shield` | partial | none | amplifies nearby allied heals by 7.5% and shields by 15%; no amp channel |
| Sona | W | `ally_heal` | `ally_shield` | yes | `support_effects.py:316` | already emits shield 105.0; the heal is rule-owned and the scanner defers (:158) |
| Soraka | R | `ally_heal` | - | yes | `support_effects.py:316` | Heal 150-350 (+50% AP) row present; R is not in SLOTS |
| Taric | Q | `ally_heal` | `self_heal` | partial | `healing_contract.py:49` | only 'Maximum Charges' is a leveling row; the rule owns the heal and the scanner defers (:158) |
| Milio | E | `ally_shield` | `aura_or_stat` | yes | `support_effects.py:316` | already emits: shield 165.0 one_teammate (probe) |
| Morgana | E | `ally_shield` | `cc_only` | yes | `support_effects.py:316` | 'Magic Shield Strength' is absent from _SUPPORT_ATTRIBUTES (support_effects.py:34) |
| Rakan | E | `ally_shield` | `mobility_only` | yes | `support_effects.py:316` | Shield Strength 50-150 row present; E is not in SLOTS |
| Seraphine | W | `ally_shield` | `ally_heal` | yes | `support_effects.py:316` | already emits shield 140.0 self_and_all_teammates; the missing-health pulse heal is not expressible |
| Shen | R | `ally_shield` | - | yes | `support_effects.py:316` | 'Minimum/Maximum Shield Strength' are absent from _SUPPORT_ATTRIBUTES (:34); R not in SLOTS |
| Taric | W | `ally_shield` | `aura_or_stat` | yes | `support_effects.py:316` | in SLOTS and attribute present, but '% of target's maximum health' resolves to 0.0 and is dropped (:391) |
| Thresh | W | `ally_shield` | `mobility_only` | yes | `support_effects.py:316` | already emits: shield 130.0 one_teammate (probe) |
| Cassiopeia | P | `aura_or_stat` | - | yes | none | amplifies MS bonuses; stat_buff has no movement-speed key |
| Jayce | P | `aura_or_stat` | `transform_or_form` | partial | none | 30 MS on stance swap; the cache holds two duplicate P entries |
| Lulu | R | `aura_or_stat` | `cc_only` | yes | `slotlib.py:878` | bonus health 275-575 (+55% AP) - stat_buff already dispatches bonus_health |
| Lulu | W | `aura_or_stat` | `cc_only` | yes | `slotlib.py:878` | self/ally AS 20-30%; enemy cast is a 1.2-2s polymorph |
| Master Yi | R | `aura_or_stat` | - | yes | `slotlib.py:878` | AS 25-65%, MS 35-55% |
| Miss Fortune | W | `aura_or_stat` | - | yes | `slotlib.py:878` | AS 40-100% + MS |
| Nami | P | `aura_or_stat` | - | partial | none | flat + AP-scaled ally MS; no movement-speed channel |
| Nidalee | P | `aura_or_stat` | `vision_or_utility` | partial | none | MS in brush + Hunted mark that empowers the first Takedown/Pounce |
| Nocturne | W | `aura_or_stat` | `enemy_projectile_or_reflect` | yes | `slotlib.py:878` | AS 30-50%, doubled to 60-100% on a successful spell-shield block |
| Nunu & Willump | P | `aura_or_stat` | - | partial | `slotlib.py:878` | 20% AS / 10% MS to self and one ally, plus a cleave on Willump's autos |
| Olaf | P | `aura_or_stat` | `self_heal` | yes | `slotlib.py:878` | missing-health-scaled AS 50-107.84% and lifesteal 8-27.67% |
| Olaf | R | `aura_or_stat` | - | yes | `slotlib.py:878` | bonus AD 10-30 with a total-AD ratio, and 10-20 resistances - a plain stat_buff shape |
| Pyke | P | `aura_or_stat` | `self_shield` | partial | `healing.py` | AD from bonus health (1 per 14); Pyke is already in GREY_HEALTH_RULE_CHAMPIONS |
| Quinn | W | `aura_or_stat` | `vision_or_utility` | yes | `slotlib.py:878` | AS 28-80% and MS 20-40% off Harrier hits |
| Rammus | P | `aura_or_stat` | - | partial | `slotlib.py:878` | AD = 15% armour + 15% MR; percent_of mode reads one stat, not a sum |
| Renata Glasc | W | `aura_or_stat` | `death_or_revive` | yes | `slotlib.py:878` | ramping ally AS/MS, plus a revive-with-burn the revive axis cannot express |
| Rengar | R | `aura_or_stat` | `vision_or_utility` | yes | `engine.py:136` | armour reduction 15-25 is exactly a target_debuff armor_reduction_flat payload |
| Singed | P | `aura_or_stat` | - | partial | none | stacking MS, capped at 625%; no movement-speed channel |
| Singed | R | `aura_or_stat` | - | yes | `slotlib.py:878` | AP 25-85 plus resistances and MS; the AP amplifies his own Q |
| Sivir | P | `aura_or_stat` | - | yes | none | 55-75 MS on hit; no MS channel |
| Sivir | R | `aura_or_stat` | `resource_or_cooldown` | yes | none | team MS 20-30% and -0.5s basic-ability cooldown per auto |
| Sona | E | `aura_or_stat` | - | yes | none | self and tagged-ally MS |
| Soraka | P | `aura_or_stat` | - | partial | none | 90% MS toward wounded allies; no movement-speed channel |
| Swain | P | `aura_or_stat` | - | partial | `slotlib.py:878` | permanent +15 bonus health per Soul Fragment - a stacked bonus_health buff |
| Taliyah | P | `aura_or_stat` | - | partial | none | 10-40% MS near terrain |
| Teemo | W | `aura_or_stat` | - | yes | none | MS 12-28%, doubled on cast |
| Tristana | P | `aura_or_stat` | - | yes | none | attack range only |
| Tristana | Q | `aura_or_stat` | - | yes | `slotlib.py:878` | AS 60-120% for 7s - the largest single unpriced DPS stat in this table |
| Trundle | W | `aura_or_stat` | - | yes | `slotlib.py:878` | AS 30-90%, MS, and increased healing inside the zone |
| Varus | P | `aura_or_stat` | - | partial | `slotlib.py:878` | on-takedown AS, then AD and AP derived from total bonus AS |
| Vayne | P | `aura_or_stat` | - | partial | none | 30/90 MS while facing an enemy |
| Viego | E | `aura_or_stat` | `vision_or_utility` | yes | `slotlib.py:878` | AS 30-50% inside the mist |
| Vladimir | P | `aura_or_stat` | - | partial | none | AP<->bonus-health two-way conversion; stat_buff has no conversion mode |
| Warwick | W | `aura_or_stat` | - | yes | `slotlib.py:878` | AS 70-110% against wounded targets, doubled 140-220% lower still |
| Zaahen | P | `aura_or_stat` | `death_or_revive` | yes | `slotlib.py:878` | 1.5-2.95% AD per stack to 36-70.87% AD at 12 - a bonus_attack_damage percent_of shape |
| Bard | R | `cc_only` | - | partial | `ability_spec.py:382` | 2.5s stasis+stun; cc_kind is a marker with no duration |
| Kalista | R | `cc_only` | `other:ally_displacement` | yes | `ability_spec.py:382` | ally is pulled, then lands for a 1-2s knockup |
| Nasus | W | `cc_only` | - | yes | `ability_spec.py:382` | ramping slow + cripple; magnitude is not expressible |
| Rammus | E | `cc_only` | - | yes | `ability_spec.py:382` | 1.2-2s taunt; the cached damage row is monsters-only |
| Renata Glasc | R | `cc_only` | - | yes | `ability_spec.py:382` | berserk 1.25-2.25s |
| Singed | W | `cc_only` | - | yes | `ability_spec.py:382` | 50-70% slow + ground |
| Trundle | E | `cc_only` | `other:terrain` | yes | `ability_spec.py:382` | terrain pillar, knockback, 34-50% slow |
| Twitch | W | `cc_only` | - | yes | `ability_spec.py:382` | 30-50% slow; the poison stacks are already an option |
| Udyr | E | `cc_only` | `aura_or_stat` | yes | `ability_spec.py:382` | stance stun on attacks + MS 25-55% |
| Viktor | W | `cc_only` | - | yes | `ability_spec.py:382` | 33-45% slow then a 1.5s stun on the fifth stack |
| Zilean | E | `cc_only` | `aura_or_stat` | yes | `ability_spec.py:382` | 40-99% ally MS or enemy slow |
| Mel | P | `damage_rider` | - | yes | none | Overwhelm stored-damage execute + Searing Brilliance projectiles (8:30/level) |
| Milio | P | `damage_rider` | `aura_or_stat` | yes | none | Fired Up! adds 7/11/15% of AD plus a 10:50 burn to the enchanted next hit |
| Miss Fortune | P | `damage_rider` | - | yes | none | Love Tap 50-100% AD on a newly marked target |
| Seraphine | P | `damage_rider` | - | yes | none | each Note fires for 4-27.47 (+4% AP) on the empowered attack |
| Shaco | P | `damage_rider` | - | yes | none | Backstab 20-31.18 (+20% bonus AD), crit-modifiable, positional |
| Sona | P | `damage_rider` | `resource_or_cooldown` | yes | none | Power Chord 20-270 (+20% AP) on every third basic ability |
| Sylas | P | `damage_rider` | - | partial | none | Petricite Burst 130% AD (+30% AP) magic on the empowered attack |
| Taric | P | `damage_rider` | - | yes | none | Bravado 25-101 (+15% bonus armour) on two attacks per cast, plus 100% total AS |
| Warwick | P | `damage_rider` | `self_heal` | yes | none | Eternal Hunger 6-60.76 (+15% bonus AD +10% AP) magic on-hit - unpriced, see asides |
| Xin Zhao | P | `damage_rider` | `self_heal` | partial | `healing_contract.py:49` | third-stack 15-60% AD (+5-20% AP) and a max-health heal; Xin Zhao already has a heal rule |
| Anivia | P | `death_or_revive` | `aura_or_stat` | yes | `defensive_effects.py:398` | already modelled: anivia.py:120 starting_revive_defense |
| Zilean | R | `death_or_revive` | `ally_heal` | yes | `defensive_effects.py:398` | revive modelled (zilean.py:43); the scanner separately emits a 1100.0 one_teammate heal |
| Shen | W | `enemy_projectile_or_reflect` | - | no | none | zone that blocks basic attacks for Shen and allies |
| Sivir | E | `enemy_projectile_or_reflect` | `self_heal` | yes | `support_effects.py:316` | already emits heal 81.6 self_and_one_teammate; the spell shield itself has no axis |
| Aurora | W | `mobility_only` | `vision_or_utility` | yes | none | dash + invisibility + MS 20-40% |
| Bard | E | `mobility_only` | - | no | none | one-way terrain portal |
| Kalista | P | `mobility_only` | - | partial | none | dash during the attack windup |
| Lucian | E | `mobility_only` | `resource_or_cooldown` | no | none | dash; -1s/-2s cooldown per Lightslinger shot |
| Taliyah | R | `mobility_only` | `other:terrain` | no | none | wall + ride |
| Talon | E | `mobility_only` | - | no | none | terrain parkour |
| Zoe | R | `mobility_only` | - | no | none | blink out and back |
| Alistar | R | `other:damage_reduction` | - | yes | none | 55-75% reduction taken; incoming_damage_multiplier is item-only (defensive_effects.py:117) |
| Anivia | W | `other:terrain` | `cc_only` | partial | none | impassable wall + knock-away; no terrain axis |
| Aphelios | E | `other:no_effect` | - | no | n/a | Weapon Queue System is a text prompt with no gameplay effect - see asides |
| Braum | E | `other:damage_reduction` | - | yes | none | directional 35-55% reduction + first-hit block |
| Malzahar | P | `other:damage_reduction` | - | partial | none | 90% reduction + CC immunity until broken |
| Neeko | P | `other:disguise` | - | no | none | ally/unit disguise |
| Nilah | W | `other:damage_reduction` | `mobility_only` | partial | none | a flat magic-damage reduction + a full basic-attack dodge |
| Ornn | P | `other:shop` | `damage_rider` | partial | none | Masterwork upgrades + Brittle 9-17.94% target max health on an immobilise |
| Sylas | R | `other:copies_ultimate` | - | no | none | casts another champion's ultimate with converted ratios |
| Taric | R | `other:invulnerability` | - | no | none | 2.5s team invulnerability |
| Warwick | E | `other:damage_reduction` | `cc_only` | yes | none | 35-55% reduction, then a fear on recast |
| Yorick | W | `other:terrain` | - | partial | none | impassable ring with 2-4 wall health; zero damage |
| Yuumi | W | `other:attachment` | `aura_or_stat` | partial | none | attach state: untargetable, casts from the anchor |
| Zilean | P | `other:experience` | - | yes | none | experience generation |
| Pantheon | P | `resource_or_cooldown` | - | no | none | Mortal Will stack counter; the empowered rider is already priced on Q |
| Renekton | P | `resource_or_cooldown` | - | no | none | Fury generation |
| Ryze | P | `resource_or_cooldown` | `aura_or_stat` | partial | none | +10% max mana per 100 AP; Ryze's kit scales off max mana |
| Viktor | P | `resource_or_cooldown` | `transform_or_form` | no | `packet_module.py:687` | Hex Fragment augments change ability behaviour - a variant-option shape |
| Xerath | P | `resource_or_cooldown` | - | yes | none | mana restore on-hit |
| Zilean | W | `resource_or_cooldown` | - | yes | none | -10s on Q and E; no cooldown-refund channel a champion can author |
| Aatrox | E | `self_heal` | `mobility_only` | partial | `healing_contract.py:49` | heal-amp already declared (aatrox.py:175); only the dash is unmodelled |
| Alistar | P | `self_heal` | `ally_heal` | partial | `healing_contract.py:49` | 5%/7% max health lives in prose, no leveling row; Alistar is already declared |
| Cho'Gath | P | `self_heal` | `resource_or_cooldown` | yes | `healing_contract.py:49` | Heal 18-96 leveling row; Cho'Gath is not in HEALING_RULE_CHAMPIONS; on-kill trigger |
| Dr. Mundo | P | `self_heal` | - | yes | `healing_contract.py:49` | already declared; regen rows are mislabelled 'Max Health Damage' in the cache |
| Mordekaiser | R | `self_heal` | `aura_or_stat` | partial | `healing_contract.py:49` | heals 10% of target max health and shreds 10% of its resists; Morde has no heal rule |
| Morgana | P | `self_heal` | - | partial | `healing_contract.py:49` | already modelled by the rule; the slot stays a zero-damage row |
| Rek'Sai | P | `self_heal` | `resource_or_cooldown` | yes | `healing_contract.py:49` | burrow heal 9-21.29% max health (row mislabelled 'Max Health Damage'); no rule declared |
| Trundle | P | `self_heal` | - | yes | `healing_contract.py:49` | 1.8-5.94% of the dying unit's max health; Trundle is already declared |
| Yuumi | P | `self_heal` | `ally_heal` | yes | `support_effects.py:316` | 'Heal' 20-120.59 row present but P is outside the scanner's Q/W/E/R loop (:333) |
| Zac | P | `self_heal` | `death_or_revive` | yes | `defensive_effects.py:398` | revive already modelled (zac.py:47); the 4-8.47% Goo chunk heal is not |
| Blitzcrank | P | `self_shield` | - | partial | `slotlib.py:581` | already modelled: blitzcrank.py:199 rides Q as self_shield_events |
| Camille | P | `self_shield` | - | partial | `slotlib.py:581` | already modelled: camille.py:274 |
| Jarvan IV | W | `self_shield` | `cc_only` | yes | `support_effects.py:316` | Shield Strength 60-140 row present; W is not in SLOTS |
| Mordekaiser | W | `self_shield` | `self_heal` | partial | `participant_timeline.py:3879` | grey-health primitive holds it; the scanner also emits a spurious ally heal - see asides |
| Rakan | P | `self_shield` | - | yes | `support_effects.py:316` | 'Shield' 30-247.94 (+95% AP) row present; P is outside the scanner's Q/W/E/R loop (:333) |
| Riven | E | `self_shield` | `mobility_only` | yes | `support_effects.py:316` | already emits: shield 170.0 self (probe) |
| Rumble | W | `self_shield` | `aura_or_stat` | yes | `support_effects.py:316` | already emits shield 145.0 but scoped one_teammate - fabricated ally shield, see asides |
| Shen | P | `self_shield` | - | yes | `support_effects.py:316` | 'Shield' 47-128.59 (+13% bonus health) row present; P is outside the scanner loop |
| Tahm Kench | E | `self_shield` | `self_heal` | yes | `healing.py` | grey health to shield; Tahm Kench is already in GREY_HEALTH_RULE_CHAMPIONS |
| Vi | P | `self_shield` | - | partial | `slotlib.py:581` | 12% max health on the next ability hit - exactly the attach_self_shield shape, unused by vi.py |
| Yuumi | E | `self_shield` | `aura_or_stat` | yes | `support_effects.py:316` | already emits: shield 165.0 (anchor scope override, support_effects.py:78) |
| Azir | P | `summon_or_pet` | - | partial | none | Sun Disc turret; needs a destroyed enemy tower |
| Lissandra | P | `summon_or_pet` | - | yes | none | Frozen Thrall shatters for 120-520 (+50% AP); spawns only on a nearby champion death |
| Naafiri | P | `summon_or_pet` | - | no | none | Packmates; no pet timeline exists |
| Naafiri | W | `summon_or_pet` | `aura_or_stat` | partial | `slotlib.py:878` | 2 extra Packmates; the 20% AD bonus AD is a stat_buff the module could carry |
| Zyra | P | `summon_or_pet` | - | partial | none | seed spawns; plants have no pet timeline |
| Nidalee | R | `transform_or_form` | - | no | `packet_module.py:687` | cougar form is already selected by the w_variant packet option (nidalee.py:41) |
| Udyr | P | `transform_or_form` | `aura_or_stat` | partial | none | stance/awaken system plus 30% AS on two attacks after each cast |
| Viego | P | `transform_or_form` | `self_heal` | partial | none | possession assumes another champion's whole kit |
| Akshan | W | `vision_or_utility` | `death_or_revive` | partial | none | camouflage + ally resurrection; only the MS 80-120 row is cached |
| Ashe | E | `vision_or_utility` | - | no | none | hawk vision only |
| Pyke | W | `vision_or_utility` | `aura_or_stat` | partial | none | camouflage + lethality-scaled MS |
| Senna | E | `vision_or_utility` | - | partial | none | camouflage aura for the team |
| Teemo | P | `vision_or_utility` | `aura_or_stat` | partial | none | idle stealth + 20-80% AS on break |
| Twitch | Q | `vision_or_utility` | `aura_or_stat` | yes | `slotlib.py:878` | camouflage then AS 40-60% on break |
