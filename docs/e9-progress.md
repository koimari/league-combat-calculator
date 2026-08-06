# E9 Progress Report — FINAL (2026-08-06)

Branch: `codex/deep-audit-2026-08` @ `07bae30`

## Completion state

### Atomization (decomposition layer)
- **Champion atoms: 5,372** across 173 champions — families: damage 2,991 · CC-mobility 1,028 · stack-transform 841 · heal-shield 289 · interaction 155 · vision 68
- **Item atoms: 1,775** across 324 items — stats 586 · damage 348 · heal-shield 266 · stack-transform 248 · vision 190 · CC 137
- Evidence model: **zero weak atoms** · 19/19 sanity checks · atom **interaction network** (relations) wired into both atomizers

### Modeling (E-series) — ALL COMPLETE
| Workstream | State |
|---|---|
| E1 self-heal rules | ✅ **46+ heal branches** (~37 champions) + grey-health closers (Pyke, Rengar, Tahm Kench, Mordekaiser, Udyr, Yuumi…) |
| E2 DoT tick counts | ✅ 40 champions (Lucian R 22 shots, MF R 18 waves, Morgana W 10 ticks, Teemo E DoT, Rumble R 20 ticks…) |
| E3 stacks | ✅ 36 champions (Varus Blight, Twitch poison, Senna Mist, Thresh souls, Kalista Rend, Yasuo/Yone, Rengar Ferocity…) |
| E4 summons | ✅ 16 champions (Yorick walkers+Maiden, Zyra plants, Ivern Daisy, Annie Tibbers, Heimer turrets, traps…) |
| E5 mis-modeled rows | ✅ 16+ fixes (Zed R stored %, TF W cards, Veigar R execute, Sion Q charge, Sett W true damage, Yone E, Xerath R…) |
| E6 classifier hardening | ✅ ghost atoms, digit-split, target policy, curated wiki recall |
| E7 item atomization | ✅ item atomizer + relations |
| E8 interactions | ✅ grey-health primitive, Grievous Wounds (items+champions), Serpent's Fang, 14 champion shields, revives (Anivia/Zac/Zilean), ally-support heals/shields, champion revive sources |
| E9 verification | ✅ **corpus (22 scenarios) · receipts (173 champs + 324 items) · BIS zero timing withholdings** |

### Champion audit verdicts (post-E-series, refreshed by E9 re-audit + closure wave)
- **143 ok · 30 review (all documented boundaries) · 0 gap** — every genuinely-missing mechanic closed by the E9.5 fix wave (28 champions: Lucian, MF, Morgana, Nunu, Talon, Warwick, Teemo, Rumble, Ahri, Illaoi, Kled, LeeSin, Naafiri, Pantheon, Renata, Sion, Smolder, Urgot, Shyvana, Sejuani, Sivir, Xerath, Viego, Sett, Poppy, Yone, Vel'Koz, Rammus)

### BIS verification (zero withholdings)
- **All 173 champions have certified BIS candidates** (sweep over 5 roles)
- Eclipse / Muramana / Bastionbreaker — the audited timing exclusions — **now certify** via authored event precision (`_item_proc_precision`: certified cast boundary = the hit; forced-attack stacking counts empowered swings)
- Support-starter upgrades (Bloodsong, Celestial Opposition, Dream Maker, Solstice Sleigh, Zaz'Zak's Realmspike) certify with `role_quest_complete: true` (sourced quest-legality gate)
- Only remaining "withheld": the 5 support upgrades without the quest state — a sourced legality constraint, not a modeling gap

### Practice-Tool corpus
- `data/practice-corpus/scenarios.json`: **22 scenarios** (4 legacy + 18 E-series) — one per workstream (E1 heals, E2 DoTs, E3 stacks, E4 summons, E5 mis-modeled, E8 grey/GW/shield/revive, item receipts), each with exact expected values + Practice-Tool reproduction steps + pinned engine SHA
- `tests/test_e9_corpus.py`: 21 tests asserting every scenario + the SHA-pin contract (engine changes without re-pinning fail loudly)

### Receipts
- `docs/receipts/`: 173 champion + 324 item receipts (`scripts/build_receipts.py`, sorted audit glob so the E9 batches win)

### Gates (final)
- pytest **3,655+ passed** (3,654 + BIS tests) · pylint **9.49/10** · black clean · node --check clean · git diff --check clean · golden snapshot identical
