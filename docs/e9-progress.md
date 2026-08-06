# E9 Progress Report — 2026-08-06 02:46 UTC

Branch: `codex/deep-audit-2026-08` @ `db3335a17c`

## Completion state

### Atomization (decomposition layer)
- **Champion atoms: 5,372** across 173 champions — families: damage 2,991 · CC-mobility 1,028 · stack-transform 841 · heal-shield 289 · interaction 155 · vision 68
- **Item atoms: 1,775** across 324 items — stats 586 · damage 348 · heal-shield 266 · stack-transform 248 · vision 190 · CC 137
- Evidence model: **zero weak atoms** (every atom tag/name/rule/inherited/wiki-map backed) · 19/19 sanity checks
- Atom **interaction network** (relations) wired into both atomizers: heal↔anti-heal, shield↔shield-reduction, tenacity↔brittle, damage↔mitigation/sustain

### Modeling (E-series)
| Workstream | State |
|---|---|
| E1 self-heal rules | ✅ **46 heal branches** (9 → 46) covering ~37 champions + 16 documented skips |
| E2 DoT tick counts | ⏳ swarm in flight (40 champions) |
| E3 stacks | 📋 partition ready (36) |
| E4 summons | 📋 partition ready (16) |
| E5 mis-modeled rows | 📋 partition ready (16, E2/E3-exclusive) |
| E6 classifier hardening | ✅ ghost atoms, digit-split, target policy, curated wiki recall |
| E7 item atomization | ✅ item atomizer + refinement |
| E8 interactions | 📋 worklist + grey-health design |
| E9 verification | 📋 corpus scaffold + receipt generator (173 champion + 324 item receipts) |

### Champion audit verdicts (baseline, pre-E-series)
- 68 ok · 43 review · 62 gap — the gap/review worklists feed E2-E5

### Gates
- pytest: **3260 passed** (post-E1) · pylint 9.50 · black clean · golden identical
- E2 in flight will re-capture golden where damage totals rise to correct values

## Receipts
- `docs/receipts/summary.json` + per-champion/per-item receipts (regenerate: `scripts/build_receipts.py`)
- `data/worklists/` — E2-E5/E8 quantified worklists + partitions
- `data/practice-corpus/scenarios.json` — Practice-Tool verification scenarios
