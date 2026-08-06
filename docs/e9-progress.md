# E9 Progress Report — 2026-08-06 (corpus expansion)

Branch: `codex/e9-corpus` (based on `codex/deep-audit-2026-08`)

## Completion state

### Atomization (decomposition layer)
- **Champion atoms: 5,372** across 173 champions — families: damage 2,991 · CC-mobility 1,028 · stack-transform 841 · heal-shield 289 · interaction 155 · vision 68
- **Item atoms: 1,775** across 324 items — stats 586 · damage 348 · heal-shield 266 · stack-transform 248 · vision 190 · CC 137
- Evidence model: **zero weak atoms** (every atom tag/name/rule/inherited/wiki-map backed) · 19/19 sanity checks
- Atom **interaction network** (relations) wired into both atomizers: heal↔anti-heal, shield↔shield-reduction, tenacity↔brittle, damage↔mitigation/sustain

### Modeling (E-series) — merged reality
| Workstream | State |
|---|---|
| E1 self-heal rules | ✅ **46 heal branches** (9 → 46) covering ~37 champions + 16 documented skips (batches b1–b6 merged) |
| E2 DoT tick counts | ✅ **40 DoT/channel champions** re-ticked in 3 swarm batches (14/14/12) + golden re-captured |
| E3 stacks | ✅ **36 stack champions** implemented in 3 batches (detonation/amplify/empower) + golden re-captured |
| E4 summons | ✅ **16 summon champions** in 3 batches (directed burst / melee pets / traps) + golden re-captured |
| E5 mis-modeled rows | ✅ **16 mis-modeled rows** fixed in 3 batches (wrong-basis 6 · wrong-read 9 · missing 1) + golden re-captured |
| E6 classifier hardening | ✅ ghost atoms, digit-split, target policy, curated wiki recall (17 wiki-map additions) |
| E7 item atomization | ✅ item atomizer + refinement (corpus-frequency pruning, vocab-leak cleanup) |
| E8 interactions | ✅ grey-health primitive (Pyke/Rengar/TahmK/Mordekaiser/Kled) · champion shield events (14) · Grievous Wounds + Serpent's Fang venom · revive events + ally-support heals/shields (11) · follow-up hooks (Anivia/Zac/Zilean revive sources, Taric Q, Bard W, Yuumi E, Rakan P) |
| E9 verification | 🔶 corpus scaffold + **Practice-Tool scenarios expanded to 22** (18 new: one+ per E1–E5/E8 workstream + 5 item receipts) · per-champion/per-item receipt generator · **receipt regeneration PENDING** (see marker below) |

### Champion audit verdicts (baseline, pre-E-series)
- 68 ok · 43 review · 62 gap — the gap/review worklists fed E2–E5 (all three now merged)

### E9 Practice-Tool corpus (`data/practice-corpus/scenarios.json`)
- `schema_version` 1; the four legacy scenarios are kept verbatim (their SHAs stay
  pinned at the commits they were captured on and are intentionally **not** re-pinned
  — their expectations predate the E-series rework).
- 18 new `local` scenarios, each pinned at the commit that wrote them and each
  verified by `tests/test_e9_corpus.py` (drives `/api/calculate`, asserts the exact
  receipt, and fails when a scenario SHA is not the current HEAD):
  - E1 self-heal: Aatrox Umbral Dash (Q heal 276.4 / W heal 50.4, total 326.8)
  - E2 DoT ticks: Malzahar E (16 ticks × 13.75 = 220)
  - E3 stacks: Varus Blight 3-stack detonation (353.7 raw) · Nasus 100-stack Q (355 raw)
  - E4 summons: Zyra plants (4 × 75) · Yorick Mist Walkers (20 × 129.4)
  - E5 mis-modeled: Zed R stored damage (341) · Veigar R minimum (325) · Sion Q max (676.4)
  - E8 interactions: Rengar W grey-health · Annie E shield (200) · Anivia Rebirth
    (revives at 100% max HP) · Morellonomicon Grievous Wounds (40% heal cut)
    · Serpent's Fang shield cut (35% ranged)
  - Item receipts: Serpent's Fang venom (50% melee) · Morellonomicon GW ·
    Sterak's Gage Lifeline (240) · Bloodthirster lifesteal (8 × 20.1) ·
    Fimbulwinter Everlasting (180.235)

### Gates
- pytest: **3592 passed** (3260 post-E1 → 3592 after E2–E5/E8 + corpus tests) ·
  pylint ≥ 9 · black clean · golden identical (re-captured per E-series merge)
- `pytest tests/test_e9_corpus.py` — 21 tests (18 pinned scenario receipts + 3 corpus contracts)

## Receipts
- `docs/receipts/summary.json` + per-champion/per-item receipts (regenerate: `scripts/build_receipts.py`)
- `data/worklists/` — E2–E5/E8 quantified worklists + partitions
- `data/practice-corpus/scenarios.json` — Practice-Tool verification scenarios

> ⚠️ **PENDING RE-RUN MARKER — docs/receipts/ regeneration is NOT done yet.**
> `scripts/build_receipts.py` must be run AFTER the three re-audit branches
> (`codex/e9-audit-1`, `codex/e9-audit-2`, `codex/e9-audit-3`) merge into the
> shared base. Until then `docs/receipts/summary.json` and the top-level
> `receipts` block inside `scenarios.json` are **stale** (pinned at `820acbc3`)
> and must not be treated as current. Do NOT regenerate them early — the
> audit verdicts feeding them would be stale.
