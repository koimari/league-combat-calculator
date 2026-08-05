# Handover Processing — Local Commit Evidence (5 Aug 2026)

Branch: `codex/handover-processing` (clean worktree, based on `origin/main`)
Base SHA: `820acbc3c8fe898463d0b2d802ebed28ce07e9c7` (production commit)
Evidence tier: **local commit** (per #77 taxonomy). No preview/production tier yet.

## Gates (all green on the base SHA)

| Gate | Result |
|---|---|
| `pytest -q` | **3199 passed** |
| `pylint src/ --fail-under=9` | **9.49/10** (>= 9) |
| `black --check src/ tests/` | 520 files unchanged |
| `node --check static/js/app.js` | OK |
| `git diff --check` | clean |
| `scripts/golden_snapshot.py compare scripts/golden_baseline.json` | snapshot identical |

## Acceptance receipts (Python 3.14 / pytest 9.1.1 / uv venv)

| Script | Result |
|---|---|
| `acceptance_matrix.py` | 10/10 PASS (calculate=200 optimize=200, withheld=True paths) |
| `champion_optimizer_matrix.py` | **173/173 CERTIFIED**, summary `exercised=173/173 passed=True` |
| `item_umbrella_audit.py` | passed: 209 ordinary / 202 manual+runtime / 130 optimizer; 0 review_pending, 0 blocked (attacker+target), 0 path mismatches, 0 unresolved conflicts |
| `full_entry_audit.py` | passed: 410/410 entries ready, 173/173 champion modules ready, 0 review_pending, 0 failures (items expected 237) |

## Issue-specific findings

### #40 (item umbrella)
Code already merged via PRs #102 (`a4ee5f9`), #103 (`bec9df1`), #114 (`efcfdce`),
commit `4cf08e8`. Standalone CP20 `0147d5a` is superseded — do not merge.
Universes reconciled (see issue body): 209 source / 188 selectable / 202 manual
runtime / 130 optimizer. Comment: #40#issuecomment-5197616389.

### #15 (champion modules)
On `820acbc3`: `reviewed_champion_names()` = 173, `registered_engine_champion_names()` = 173,
**generated = 0**. Full-entry audit 410/410; champion matrix 173/173 certified.
Remaining: `/api/champions` production pass (behind KoiAccessAccount session gate).

### #38 (nine champion withholdings)
All nine former withholdings (Akshan, Bel'Veth, Kalista, Ornn, Qiyana, Shyvana,
Tahm Kench, Wukong, Ziggs) are **CERTIFIED** in the local matrix on `820acbc3`.
Remaining: fresh production matrix pass before relying on closure.

### #82 (role-quest boot upgrades + support progression)
Code landed on main: `role_quests.py` (BOOT_UPGRADES, SUPPORT_QUEST_ITEM_STAGES),
`loadout_rules.py` (required_boots_tier, inventory_capacity, support gating),
boot upgrade stats (PR #103), support quest transition normalization merged as
`8d6abe4` (PR #106, branch `codex/cp82-support-quest-parity` head `7589400`).
All related tests pass in the 3199. Remaining: per-item typed-stat certification
and preview + production QA over 7 boot pairs + 5 upgraded support items.

### #14 / #77 / #78
#14 (Bastionbreaker/Muramana/Fimbulwinter withholding): by-design per-scenario
event-order certification; re-audit needs a production pass. #77: this document
follows the evidence format (tier + SHA + totals). #78: `/api/config`,
`/api/champions`, `/api/items`, `/api/boots` capability fields present in code;
frontend round-trip + production parity still require browser evidence.

## Blocked dependency

Production-tier evidence (browser QA on https://scryglass-item-calculator.vercel.app)
requires the KoiAccessAccount session; unauthenticated requests return the
private splash page for all `/api/*` routes. Needs the logged-in session or
credentials to complete #14/#15/#38/#77/#78/#82 production passes.
