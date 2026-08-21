# Coverage frontier

What the calculator does not model yet, measured at the coverage-frontier campaign's merge
head from the repo's own receipts (`docs/coverage-census.json`, the champion module
contracts, `item_effects.ITEM_EFFECTS`, `data/runes.json`). Machine truth stays in those
files; this page is the human reading of them. Re-measure with the probes at the bottom
before acting on a number here.

## Champions — 173/173 modules, 65 of 865 slots out of scope

| Slot | modeled | no_damage | out_of_scope |
|---|---|---|---|
| P | 125 | 19 | 29 |
| Q | 172 | 1 | 0 |
| W | 150 | 8 | 15 |
| E | 156 | 5 | 12 |
| R | 159 | 5 | 9 |

`modeled` means a priced row or a state row the engine consumes (a stat grant, a shield, a
heal, a revive) — a slot with no row of its own says which engine channel pays it
(`COVERAGE_CHANNELS`: `self_healing_rule`, `self_shield_events`, `starting_revive_defense`,
`post_hit_proc`). `no_damage` means the slot is emitted and nothing is left to price.
`out_of_scope` means the engine has no axis, and the module docstring names it. The 65 by axis:

| Axis | Slots | Which |
|---|---|---|
| Stat or aura with no channel (movement speed, stat conversion) | 13 | Cassiopeia P, Jayce P, Nami P, Nidalee P, Pyke P, Sivir P, Sivir R, Sona E, Soraka P, Taliyah P, Teemo W, Vayne P, Vladimir P |
| Summon, pet, clone, transform, terrain | 8 | Azir P, Lissandra P, Zyra P, Wukong W, Nidalee R, Udyr P, Anivia W, Yorick W |
| Mobility | 7 | Aurora W, Bard E, Kalista P, Lucian E, Taliyah R, Talon E, Zoe R |
| CC magnitude (the marker has no duration or percent) | 7 | Bard R, Kalista R, Nasus W, Trundle E, Udyr E, Viktor W, Zilean E |
| Reflection, invulnerability, death, disguise, attachment, shop, experience | 9 | Shen W, Mel W, Taric R, Kog'Maw P, Neeko P, Yuumi W, Ornn P, Zilean P, Sylas R |
| Priceable with no engine shape yet | 6 | Samira P (range-gated rider on ability parts), Aurelion Sol P/W (already reached through `stardust_stacks` / `w_active`), Nilah P (ally heal/shield amp), Yuumi P (on-hit self shield), Tahm Kench E (grey-health active) |
| Vision, stealth | 5 | Akshan W, Ashe E, Pyke W, Senna E, Teemo P |
| Damage-reduction taken | 5 | Alistar R, Braum E, Malzahar P, Nilah W, Warwick E |
| Resource, cooldown | 5 | Renekton P, Ryze P, Viktor P, Xerath P, Zilean W |

Closing these means new axes, not more packets; each is a backlog row
(`docs/surface-area-backlog.md`, CF3–CF9).

**Known-degraded wiki parses** (CLAUDE.md Known Quirks): Bard P chimes, Heimerdinger W/E
multi-part rockets, Aurelion Sol Q stacks, Quinn P crit, Vladimir E charge, Yasuo/Yone Q3
crit conversion, Zeri P execute; and the cache-quality rows in backlog CF11.

## Items — every effect-bearing SR item is classified

209 ordinary Summoner's Rift items; 154 carry passive/active text; 125 have an
`ITEM_EFFECTS` entry and the other 34 are reviewed `item_coverage` claims
(`optimizer_candidate_coverage` reports every one as fully modelled):

| Class | Items | What is priced |
|---|---|---|
| Coupled-fight ally effects | Imperial Mandate, Echoes of Helia, Rylai's Crystal Scepter | Mandate's Command amp and Control haste; Helia's Soul Siphon heal (its record carries no damage row); Rylai's slow is state — none of the three has an unpriced damage packet |
| Grievous Wounds | Morellonomicon, Oblivion Orb, Chempunk Chainsword, Executioner's Calling | the coupled walk cuts every heal the wounded participant receives to 60% for 3 s, gated on the item's damage type (magic / physical) — self-heal rules, lifesteal, Warmog's ticks, thorns and Lifeline heals included |
| Support, handled in `item_behavior` (survival side) | Redemption, Locket of the Iron Solari, Mikael's Blessing, Moonstone Renewer, Shurelya's Battlesong, Ardent Censer, Knight's Vow, Dream Maker, Solstice Sleigh, Diadem of Songs | ally heals/shields at the level the wiki names (holder's or recipient's) |
| Stat / utility only | Phantom Dancer, Cosmic Drive, Youmuu's Ghostblade, Quicksilver Sash, Crimson Lucidity, Cryptbloom, Dark Seal, Mejai's Soulstealer, Lost Chapter, Doran's Helm, boots (Swiftness, Lucidity, Gluttonous Greaves), Refillable Potion, jungle pets (Gustwalker, Mosstomper, Scorchclaw) | their stats |

## Enemy-side survival certification — 9 items, 100 coarse cells

Nine enemy items are survival-certified (Fimbulwinter, Force of Nature, Hexdrinker,
Immortal Shieldbow, Jak'Sho, Maw of Malmortius, …). The census's whole remaining frontier
is one mechanic: `fimbulwinter_everlasting`, 100 cells over 25 attackers. Everlasting's
timed certification needs a reviewed CC kind on every damaging ability event and those
kits have hits with no instant the cache states. Each is acknowledged in
`docs/coverage-residue.json` with the sentence and what it omits; closing them would mean
authoring cadence the source does not give.

## Runes — 62 cached, 62 compiled, 31 priced; 9 shards priced

`data/runes.json` holds the whole roster from Data Dragon (17 keystones, 45 minor runes
with path and row) plus the Rune page's stat-shard table. Every rune compiles and is
selectable through a validated rune page (`keystone`, `minor_runes`, `stat_shards`,
`rune_options`); all nine shards price into stats. 31 runes price a number: every
proc/amp/stat keystone and the minors whose effect reaches a channel the engine reads
(haste, adaptive force, attack speed, health, life steal, lethality and magic pen, a heal
ledger, impaired- and shield-triggered procs, option-armed procs). The other 31 compile to a
receipted refusal naming the axis they wait on:

| Axis | Runes |
|---|---|
| Gold, vision, wards | Cash Back, Treasure Hunter, Sixth Sense, Deep Ward |
| Movement speed with no fight consequence | Relentless Hunter, Approach Velocity, Magical Footwear, Nimbus Cloak, Stormraider's Surge |
| Summoner-spell / item / trinket haste | Cosmic Insight, Grisly Mementos, Hextech Flashtraption, Unsealed Spellbook |
| Mana and resource | Manaflow Band, Presence of Mind |
| Consumables on a clock | Biscuit Delivery, Time Warp Tonic, Triple Tonic |
| Holder-side durability (no holder-health or incoming-damage stream in the pair engine) | Bone Plating, Conditioning, Second Wind, Unflinching, Guardian, Aftershock |
| Heal-and-shield power multiplier (published, read by no packet) | Revitalize |
| Non-champion target, kill without a timestamp | Demolish, Absorb Life |
| Growing or cyclic in-fight grants | Conqueror, Fleet Footwork, Grasp of the Undying (its heal), Dark Harvest (its missing-health gate), Glacial Augment (ally-only) |

## Order of attack

1. Holder-side durability axis — a holder-health track in the pair engine would price six
   runes, the Grey-health and shield slots that wait on it, and Last Stand from the fight
   instead of an option.
2. Movement speed as one stat channel shared by items, runes and abilities (CF9) — 8 champion
   slots and 5 runes.
3. CC duration/magnitude on the marker (CF8) — 6 champion slots, then Everlasting's residue
   can shrink where the cache states an instant.
4. Samira P's range-gated rider (CF3) and the cache-quality rows (CF11).
5. Summons, transforms, terrain and mobility need new axes; not piecemeal.

## Probes

```python
# slot coverage
from collections import Counter
from src.calculator.champions import _CHAMPION_MODULES, get_champion_module_contract as g
Counter((s, st) for n in _CHAMPION_MODULES for s, st in g(n).coverage.items())

# item effect gap (every name it prints is a reviewed item_coverage claim)
from src.calculator import item_source, item_effects
from src.calculator.data_fetcher import fetch_item_data
sr = {i["name"]: i for i in fetch_item_data().values() if item_source.is_ordinary_sr_item(i)}
[n for n, i in sr.items() if item_source.effect_entries(i) and n not in item_effects.ITEM_EFFECTS]

# runes
from src.calculator.rune_effects import rune_catalog, shard_catalog
c = rune_catalog(); len(c), sum(e["implemented"] for e in c)
```

Census and residue: `python scripts/coverage_census.py check docs/coverage-census.json`.
