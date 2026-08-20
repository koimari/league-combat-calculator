# Coverage frontier

What the calculator does not model yet, measured at `0ef3228c` from the repo's own receipts
(`docs/coverage-census.json`, the champion module contracts, `item_effects.ITEM_EFFECTS`,
`data/runes.json`). Machine truth stays in those files; this page is the human reading of
them. Re-measure with the probes at the bottom before acting on a number here.

## Champions — 173/173 modules, 150 of 865 slots out of scope

| Slot | modeled | no_damage | out_of_scope |
|---|---|---|---|
| P | 97 | 12 | 64 |
| Q | 167 | 1 | 5 |
| W | 132 | 5 | 36 |
| E | 148 | 2 | 23 |
| R | 148 | 3 | 22 |

`no_damage` (23 slots) is closed: the slot deals nothing (Tryndamere P/Q/W/R, Zed P/W, …).
The 150 `out_of_scope` slots split by whether the cached wiki leveling carries a damage row:

**Damage slots worth a module update (wiki rows exist):** Samira Q, W, E · Yasuo R ·
Kai'Sa P · Kindred Q · Aurelion Sol W · Wukong W · Rumble P · Kog'Maw P · Mel W.

**Damage-row matches that are reduction/heal rows, not gaps:** Alistar R, Braum E, Rammus E,
Warwick E, Sona W, Tahm Kench E, Zac P, Rek'Sai P, Trundle P, Dr. Mundo P, Olaf R,
Seraphine P.

**~127 utility slots the engine has no axis for** — shields, heals, CC, mobility, auras,
summons, transforms: Milio, Taric, Yuumi, Zilean, Sona, Soraka and Shen's non-damage kits,
Lulu W/R, Morgana E, Sylas P/R, Renata W/R, Singed P/W/R, Thresh W, Kalista P/R, Rakan P/E,
Bard W/E/R, and the long tail of passives (Blitzcrank, Camille, Cassiopeia, Cho'Gath, …).
Closing these means new mechanics, not more packets.

**Known-degraded wiki parses** (CLAUDE.md Known Quirks): Bard P chimes, Heimerdinger W/E
multi-part rockets, Aurelion Sol Q stacks, Quinn P crit, Vladimir E charge, Yasuo/Yone Q3
crit conversion, Zeri P execute.

## Items — 125 of 154 effect-bearing SR items configured

209 ordinary Summoner's Rift items; 154 carry passive/active text; 125 have an
`ITEM_EFFECTS` entry. The 34 without:

| Class | Items | Cost of the gap |
|---|---|---|
| Coupled-fight damage | Imperial Mandate, Echoes of Helia, Rylai's Crystal Scepter | ally amp and heal-damage packets unpriced; Rylai's has no number |
| Survival input | Morellonomicon, Oblivion Orb, Chempunk Chainsword, Executioner's Calling | the engine models enemy healing but cannot apply Grievous Wounds |
| Support, handled in `item_behavior` (survival side), not `ITEM_EFFECTS` | Redemption, Locket of the Iron Solari, Mikael's Blessing, Moonstone Renewer, Shurelya's Battlesong, Ardent Censer, Knight's Vow, Dream Maker, Solstice Sleigh, Diadem of Songs | none for damage |
| Stat / utility only | Phantom Dancer, Cosmic Drive, Youmuu's Ghostblade, Quicksilver Sash, Crimson Lucidity, Cryptbloom, Dark Seal, Mejai's Soulstealer, Lost Chapter, Doran's Helm, boots (Swiftness, Lucidity, Gluttonous Greaves), Refillable Potion, jungle pets (Gustwalker, Mosstomper, Scorchclaw) | none |

## Enemy-side survival certification — 9 items, 100 coarse cells

Nine enemy items are survival-certified (Fimbulwinter, Force of Nature, Hexdrinker,
Immortal Shieldbow, Jak'Sho, Maw of Malmortius, …). The census's whole remaining frontier
is one mechanic: `fimbulwinter_everlasting`, 100 cells over 25 attackers (Aatrox, Ahri,
Akali, Akshan, Ambessa, Anivia, Annie, Bel'Veth, Brand, Darius, Diana, Kennen, Kled,
LeBlanc, Master Yi, Sett, Shaco, Sivir, Syndra, Vex, Xayah, Xin Zhao, Yone, Zoe, Zyra).
Everlasting's timed certification needs a reviewed CC kind on every damaging ability event
and those kits have hits with no instant the cache states. Each is acknowledged in
`docs/coverage-residue.json` with the sentence and what it omits; closing them would mean
authoring cadence the source does not give.

## Runes — 17 keystones, no minor runes

Everything in `data/runes.json` is a keystone (17 compiled, 0 unmodeled). Minor runes
(Triumph, Coup de Grace, Last Stand, Cut Down, Gathering Storm, Cheap Shot, Eyeball
Collection, Legend: Alacrity, Absolute Focus, Scorch, Transcendence, Celerity, …) are not
cached, so they fail closed. For an ordinary build this is the largest number still missing
per request (roughly 5–15% of damage) and the cheapest to add: most are flat or percent
modifiers the `rune_effects.py` shape already carries.

## Order of attack

1. Minor runes — biggest everyday number, smallest new mechanism.
2. Grievous Wounds items — the survival engine models healing but cannot reduce it.
3. Samira Q/W/E, Yasuo R, Kai'Sa P, Kindred Q — damage slots with wiki rows (`add-champion`).
4. Imperial Mandate, Echoes of Helia — coupled-fight ally effects, now that rosters exist.
5. The utility slots and the Fimbulwinter residue need new axes or new source data; not piecemeal.

## Probes

```python
# slot coverage
from src.calculator.champions import _CHAMPION_MODULES, get_champion_module_contract as g
{(s, st) for n in _CHAMPION_MODULES for s, st in g(n).coverage.items()}  # Counter it

# item effect gap
from src.calculator import item_source, item_effects
from src.calculator.data_fetcher import fetch_item_data
sr = {i["name"]: i for i in fetch_item_data().values() if item_source.is_ordinary_sr_item(i)}
[n for n, i in sr.items() if item_source.effect_entries(i) and n not in item_effects.ITEM_EFFECTS]
```

Census and residue: `python scripts/coverage_census.py check docs/coverage-census.json`;
keystones: `docs/coverage-census.json["keystones"]`.
