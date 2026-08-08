# Deep Audit & Fundamental-Decomposition Plan — 2026-08-05

Branch: `codex/deep-audit-2026-08` (clean worktree `/Users/river/Projects/league-combat-calculator-audit`)
Base: `820acbc3` (current production SHA) · Tier: local-commit/local-browser evidence

## 1. Current state (main @ 820acbc3)

- Gates: pytest **3201 passed** · pylint 9.49 · black clean · golden identical · acceptance 10/10 · champion matrix **173/173 certified** (0 generated) · full-entry **410/410 ready** (173 champions + 237 items) · item umbrella **209 items, 0 blocked, 0 review_pending**.
- Coverage model is **fail-closed and per-effect**: defense effects are modeled on the target/survival side; ally effects in the support ledger; Grievous Wounds in the timeline; slows/MS/utility as named out-of-scope reasons.

## 2. Gap inventory — every "partially working" surface

### 2.1 BIS/optimizer withholdings (user-visible partials)
- **Bastionbreaker** (`shaped_charge_Bastionbreaker`), **Eclipse** (`proc_Eclipse`), **Muramana** (`muramana_ability`) — excluded before BIS ranking: coarse timing, no sourced hit boundary. (Verified via `/api/bis` Ahri/Annie utility scenario + `timeline_coverage_probe.py`.)
- **Fimbulwinter** — partial candidate (uncertified CC-packet branch); visible as audit row, never ranked.
- Consequence: these items can never be "best in slot" until their event timing is exact. → closes #43/#44/#14.

### 2.2 Champion self-healing — only 9 modeled; 22+ heal-named mechanics missing
`HEALING_RULE_CHAMPIONS` = Aatrox, Ambessa, Darius, Warwick, Dr. Mundo, Irelia, Renekton, Soraka, Briar.

Binary evidence (scan of all 203 decomposed CharacterRecords for heal-named
spells/buffs) — modeled or missing:

- Modeled: Dr. Mundo (`DrMundoRHeal`), Soraka (`SorakaQRegen`) ✓ (others use non-heal spell names)
- **Missing from the self-heal model** (sourced heal mechanics present in the game data):
  Alistar (passive heal), Bard (W health pack), Cho'Gath (Feast), Ekko (R heal), Fiora (R heal),
  Garen (passive heal), Illaoi (tentacle heal), Kayle (W heal), Kindred (W passive heal),
  K'Sante (R conversion), Locke (consume attack), Pyke (P grey-health toggle), Rakan (Q heal),
  Rek'Sai (P regen), Seraphine (W2 heal), Sett (passive regen), Sylas (W damage+heal),
  Trundle (passive heal), Udyr (W heal), Vladimir (Q/W/R heals), Yuumi (P heal), Zoe (W heal summoner spell) — 22
- Additional champions whose heal mechanics use non-"heal" spell names (Swain R, Nasus passive,
  Maokai passive, Tahm Kench, Volibear W, Xin Zhao W, Mordekaiser, Gwen, Camille…) need a
  field-level audit of each CharacterRecord's BuffData/SpellData — seed for WS4.

### 2.3 Ally champion support — only items + a few champions
Verified: Lulu "Help, Pix!" shield (rank 5 → 230 shield to main, `support_events`) works.
Audit needed: every enchanter's champion-ability support (Sona W, Nami W/E, Yuumi, Seraphine, Taric, Rakan, Karma, Milio, Renata, Janna, Ivern…) — which are modeled in the support ledger vs missing.

### 2.4 Conditional (`modeled_event_certified`) items — 9
Sterak's Gage, Hexdrinker, Immortal Shieldbow, Maw, Protoplasm Harness, Seraph's Embrace, Force of Nature, Jak'Sho, Fimbulwinter.
Verified working when the trigger is hit (Sterak's: `threshold_shield_triggered=true`, 240 absorbed at <30% HP). In default timed fights they only fire when the threshold/event is actually crossed — correct, but every scenario result must make the trigger state explicit.

### 2.5 Active/input-gated items
Zhonya's Hourglass (stasis), Mikael's Blessing, Redemption — priced only from explicit `active_seconds` scenario inputs (fail-closed by design). The UI must surface these inputs clearly; otherwise item presence alone does nothing.

### 2.6 stats_only attacker items (99) — classification verified
- 52 truly stat-only (components/consumables) — nothing to model.
- 19 defense (modeled on target side: GA Rebirth, Banshee/Edge Annul, Zhonya, Lifelines, Randuin's, Warden's Mail, Spirit Visage…).
- 5 Grievous Wounds (applied in timeline) · 2 ally-support (Dream Maker, Echoes of Helia) · 3 jungle pets (monsters, out of scope) · 9 movement/slow utility · small misc set.
- Verify/decide: Cryptbloom (post-takedown heal), Gluttonous Greaves (omnivamp), Lost Chapter (mana), Doran's Helm (minion-only damage), Ionian (summoner haste), Gunmetal (Riot-only branch, explicitly out of scope).

### 2.7 Wiki-known quirks — modules exist; mechanics must be verified per slot
All 13 AGENTS.md quirk champions have named modules (Aurelion Sol Stardust, Bard Chimes, Heimer turrets, K'Sante resists, Quinn P crit, Vladimir E charge, Yasuo/Yone Q3 crit conversion, Zeri P execute range, Gnar Mega). Per-slot verification must confirm each quirk mechanic is actually modeled, not merely declared.

### 2.8 Champion classes / archetype semantics
Champion modules exist for all 173, but "class" behaviors (e.g., Vayne W true-damage stacks, Jinx rocket splash, Yasuo passive crit) are implemented per-module — the audit must confirm each is sourced, not estimated.



**Refined binary evidence (behavior-index over all 203 CharacterRecords):**
- 31 champions carry heal-named spell objects; ~22 are champion-specific
  (Alistar, Bard, Cho'Gath, Ekko, Fiora, Garen, Illaoi, Kayle, Kindred,
  K'Sante, Locke, Pyke, Rakan, Rek'Sai, Seraphine, Sett, Sylas, Trundle, Udyr,
  Vladimir, Yuumi, Zoe) — the rest are the shared `VladimirTransfusionHeal`
  lifesteal hook or rune references (Hecarim, Kalista, Kayn, Thresh, Twitch,
  Vex, Zeri, Zilean, Lillia) and must not be double-counted.
- 63 champions carry shield-named spell objects (every shield in the game is
  inventoried in `data/bin/behavior-index.json`).
- The champion bins contain the full spell objects inline (cooldowns, ranges,
  `mAlternateName` behavior refs); BuffData details resolve through those refs.
- `Scripts.wad.client` (53,778 files) holds map/AI Lua (level scripts, pets,
  minions, Baron) — game-logic layer for Practice-Tool reproducibility, not
  champion formulas.


**WS1 status (2026-08-05):** complete article inventory built and tracked —
`data/wiki/article-index.json` (4,231 namespace-0 non-redirect articles with
pageid/length/categories) + `scripts/decompose_wiki.py` (index rebuild + raw
wikitext fetch). Validated: all 173 calculator champions are present (2 are
cache-name aliases: Renata Glasc, Wukong). Per-family parsers for mechanics/
buffs/status pages are the next WS1 step; the wiki is template-heavy, so they
follow the lolstaticdata extraction pattern.

## 3. The decomposition architecture (path to "nothing partial")

**Principle:** every champion/item is a *composition of the game's fundamental behaviors*. Two authoritative sources feed one atomic catalog:

### 3.1 Full Wiki ingestion (13,832 articles)
Currently 410 pages are digested. The complete article set includes families beyond champions/items: summoner spells (36+), buffs/status effects, crowd control types, game mechanics, monsters (Baron/Dragons/Herald/Grubs/camps), minions, turrets, terrain, wards/vision, objectives, game modes, champion classes, runes (minor + keystone), consumables, and patch history. Pipeline: MediaWiki API → tracked cache (same `data/` pattern) → per-page receipt → category-tree coverage report.

### 3.2 Game binary ingestion (PROVEN WORKING on the installed client)
- Installed game = **16.15.8024387** — exactly the project's pinned audit basis.
- WAD packages: `.../Game/DATA/FINAL/Global.wad.client` (64,726 files), `DATA.wad.client` (4,869), 203 `Champions/<name>.wad.client` (each ~2.6k files).
- Hash table `hashes.game.txt` (2,284,982 entries) maps every WAD file: **64,713/64,726 matched**.
- Extraction: `league-tools` WAD parser (zstd/gzip) — verified on `data/characters/aatrox/aatrox.bin` (27.7 KB).
- Parse: `cdtb.binfile.BinFile` → named JSON (`CharacterRecord`, `SpellDataResource`, `BuffData`, `ItemData`) — verified: Aatrox base stats, spell slots, passive/buffs, stat stones.
- Artifacts to ingest: all `data/characters/*/*.bin` (CharacterRecords + spell data), `data/items/*.bin`, `data/spells/*.bin`, `data/buffs/*.bin`, rune/perk data, map data (Maps/Shipping).

### 3.3 Fundamental behavior catalog
Registry of atomic behaviors with dual provenance (wiki page + binary field):
damage packet types (projectile/hitscan/DoT/execute/true), shields (flat/percent/threshold), heals (self/ally/lifesteal/omnivamp/vamp), resource changes, CC types (stun/root/slow/silence/knockup/…), stacks (cap/decay/reset), transformations, resets, pet summons, vision/stealth, movement modifiers, buff/debuff instances (duration/refresh/stacking), interaction rules (target policy, simultaneous triggers, death boundaries).

### 3.4 Recompose
Each champion/item = declared composition of atoms (data-driven), with named champion modules verified against the full wiki entry and the binary. Anything not composed of atoms stays visibly out-of-scope with a named reason — nothing silently partial.

## 4. Delivery workstreams (order)

1. **WS1 — Full-wiki ingestion**: all 13,832 articles into the tracked cache; category-tree receipt; diff-audited like today's `data/`.
2. **WS2 — Binary ingestion**: extract + parse all CharacterRecords/SpellData/ItemData/BuffData from the local WADs; cross-validate wiki numbers against binaries (the wiki is the human-readable layer, binaries are the exact layer).
3. **WS3 — Atomic catalog**: the fundamental-behavior registry (typed, sourced, tested).
4. **WS4 — Champion recompose**: self-healing (all champions), ally-support (all enchanters), quirk mechanics per slot, class semantics.
5. **WS5 — Item recompose**: close Bastionbreaker/Eclipse/Muramana timing + Fimbulwinter certification; resolve the stats_only misc set.
6. **WS6 — Certification**: zero withholdings in BIS; conditional effects always fire when conditions met; every result carries receipts.
7. **WS7 — Practice-Tool reproducibility**: deterministic scenario → expected output fixtures; in-game verification protocol (same items/levels/abilities, combat-log comparison).

## 5. Reproducibility in the Practice Tool

- Every scenario is a concrete input tuple (champion, level, items, boots, quest, ranks, casts, options, enemies, allies, fight window) → deterministic output (TDD, EHP, shields, heals, kill time, ledger).
- The Practice Tool can reproduce: same loadout in-game, fixed target dummy/units, combat log → measured totals.
- Deliverable: an official scenario corpus (100+ fixtures) with expected values + a verification checklist, so anyone can reproduce any claim in-game.

## 6. Evidence from this audit

- `timeline_coverage_probe.py`: only `muramana_ability` coarse in the probe set.
- `/api/bis` Ahri/Annie utility: 3 withheld (Bastionbreaker, Eclipse, Muramana), 1 partial (Fimbulwinter).
- Sterak's Gage: threshold shield verified firing (`threshold_shield_triggered=true`).
- Lulu ally: `support_events` contains "Help, Pix! · Shield Strength" 230 → main.
- Binary pipeline: hash table 2.28M entries; WAD matched 64,713/64,726; Aatrox CharacterRecord parsed (base stats, spells, buffs).
