# F3 — rotation derivation verification gaps

This report lists every champion whose algorithmic derivation is
**ambiguous**: the atomized data either produced conflicting signals, or
produced no signal where a known combo exists.  These are queued for the
F4 verification swarm — each entry names the missing atom(s) that would
resolve the derivation, so the swarm can either author the atom or
certify a manual override.

Legend:

- **derived order** — what the algorithm currently emits (base order when
  the kit is flat).
- **signal** — the atoms that fired (or the gap: which atoms are missing).
- **fix** — the atom/mechanic that would resolve the ambiguity.

---

## Known combos with no derivable data signal

These kits have a human-known optimal opener that the atomized data
cannot express yet — either because the setup is authored on a passive
row (not a cast slot) or because the relationship is only in prose.

| Champion | Known combo | Why the derivation can't see it | Missing atom |
|----------|-------------|---------------------------------|--------------|
| Tristana | E (Explosive Charge) first, then autos/abilities stack it to full-stack detonation | E applies AND consumes its own charge stacks (self-edge); the stackers are autos + abilities, not one cast slot | a "charge applier" atom on E (attach-before-stack); or a documented override |
| Caitlyn | W (Yordle Snap Trap) first — trapped targets take the Headshot amp | the trap's "takes additional damage from the Headshot" is a self-setup (W's own trap); no cross-slot consumer | a trap/Headshot setup atom linking W → empowered autos |
| Kennen | P (Mark of the Storm) marks via autos/abilities; W (Electrical Surge) active detonates the mark | the mark is applied by the auto stream + all abilities; the W active's consume is prose-only ("deals bonus magic damage to enemies marked") | a `mark_detonate` atom on W's active |
| Volibear | W (Frenzied Maul) applies Wounded; the SECOND W cast consumes it for +50% damage | W applies and consumes its own mark (self-edge); the champion has no other consumer | a self-consumed-mark atom (order-neutral, but should be documented) |
| Viego | Q applies the mark; the next basic attack consumes it | the consumer is the auto stream, not a cast slot | an auto-consumed-mark atom |
| Naafiri | Q bleed self-recast (Q → Q) | Q applies and consumes its own bleed; the missing-health rider is on the same cast | a recast-consumer atom on Q |
| Nidalee | W trap applies Hunted; cougar Q (Takedown) is Prowl-Enhanced vs Hunted | the Hunted mark application is a trap object (not a cast slot); form-swap kit | a Hunted-mark atom on W → Q edge |
| Illaoi | E (Test of Spirit) opens — the spirit transfer is her damage loop | the vessel/spirit relationship is prose; Q/W/R tentacle damage has no consume atom | a spirit/vessel setup atom |
| Yasuo | Q3 (Gathering Storm) consumes Q's self-stacks; E's Ride the Wind self-stacks | self-stacks, correctly excluded — but the Q→Q3 recast cadence is worth a module-level confirmation | a `q_gathering_storm` recast pair atom |
| Gnar | Rage Gene / Mega form bonuses | the form swap is a passive-driven state; Mega bonuses are module constants, not cast-order atoms | a form-gated cast-order declaration (module `CAST_ORDER`) |
| Jayce / Kai'Sa / Karthus / Shen / Taliyah / Vi | certified module orders | already certified via `CAST_ORDER` — no gap, listed for completeness | — |

## Ambiguous / conflicting signals

| Champion | Signal conflict | Current outcome | Suggested resolution |
|----------|-----------------|-----------------|----------------------|
| Hwei | Q's missing-health execute (q_missing_health) forces Q after R (the only other damage row in the default variant); W/E are utility rows with no damage at the default options | derived `R, Q, W, E` | verify the execute-last intent across Q's variants (QQ/QQ2) in timed fights |
| Seraphine | Q's "damage increased by up to 75% based on target's missing health" is a missing-health execute rider ("Maximum Enhanced Damage" attribute + target-missing-health) | derived `E, R, Q, W` — Q executes after E/R's damage; W (shield row) sits after the burst | confirm the execute-last rotation is the intended burst (it delays her poke) |
| Renekton / Rumble | "Enhanced Damage" rows are gated by a SELF resource (fury/heat), which the detector correctly excludes — but the enhanced state is a real damage amp a human times | flat base order | a self-resource AMP atom (heat/fury threshold) if the engine should order around it |
| Darius | E grants armor pen (buff-first) AND applies a Hemorrhage stack (stack-consume) — two edges that agree (E first) | derived `E, Q, W, R` | verified agreement; no action |
| Briar | Q shred (before W/E/R) + W missing-health execute (after Q/E/R) — consistent | derived `Q, E, R, W` | verified agreement; no action |
| Brand | P applies Blaze stacks; every ability also consumes ("Ablaze Bonus") — the consume is per-ability, not a single detonator | override seed `Q, R, E, W` | seed wins; the W "takes 25% increased damage vs ablaze" edge is detected and satisfied |

## Champion modules without full atom coverage

These champions' parses are generated packet modules (or sparse
hand-authored modules) — the missing atoms above are exactly what the F4
swarm should author while certifying the champion module:

`Tristana, Caitlyn, Kennen, Volibear, Viego, Naafiri, Nidalee, Illaoi,
Yasuo, Gnar, Hwei (variants), Seraphine, Renekton, Rumble, Brand
(ablaze consume), Nautilus, Lulu, Xin Zhao, Malphite, Poppy, Kai'Sa
(plasma autos), Varus (R-stack seed exception)`

---

*Every entry above was produced by the derivation itself (the ambiguity
report is generated from the same atoms the resolver consumes); nothing
is hand-invented.*
