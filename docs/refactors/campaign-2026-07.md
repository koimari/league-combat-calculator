# Refactor campaign — July 2026

Orchestrated multi-agent campaign. Claude is orchestrator/reviewer; subagents implement.
Branch: `feature/build-optimizer`. Baseline commit: `a5627bd` (WIP), data update: `3a3f4f1` (patch 16.13.1).

## Verification contract (applies to every phase)

1. Wiki data was re-pulled at campaign start (patch 16.13.1). Do NOT re-pull again mid-campaign.
2. Run the full suite with the project venv: `.venv/Scripts/python.exe -m pytest -q`
3. **Baseline pass/fail set** (established 2026-07-10, after re-pull): 652 passed, 9 failed.
   Refactor phases must keep every baseline-passing test passing with identical values —
   calculations replicate to the 2nd decimal. The 9 baseline failures are being triaged
   separately (patch drift vs parser regression); do not "fix" them inside a refactor phase.
4. Golden snapshot: `scripts/golden_snapshot.py` (built in Phase 0). After any refactor phase:
   `capture` to a temp file and `compare` against `scripts/golden_baseline.json` — must be
   identical to 2 decimals.

## Baseline failures under triage

- tests/test_ashe.py::TestQRangersFocus::test_q_flurry_ratio_rank5
- tests/test_ashe.py::TestQRangersFocus::test_q_active_auto_damage
- tests/test_damage.py::TestParseAhriAbilities::test_q_rank3_with_60ap
- tests/test_damage.py::TestParseAhriAbilities::test_q_rank5_with_215ap
- tests/test_damage.py::TestActualizerFightDamage::test_ahri_q_with_actualizer_active
- tests/test_damage.py::TestOpportunityPreparation::test_parsed_values_match_expected
- tests/test_damage.py::TestVoltaicCyclosword::test_voltaic_parsed_values (KeyError 'base')
- tests/test_stats.py::TestNewItemStats::test_flowing_water_rapids_ap (75 vs 80)
- tests/test_stats.py::TestNewItemStats::test_statikk_shiv_parsed_values (KeyError 'empowered_auto_count')

## Phases (task list mirrors this)

- **Phase 0** — baseline commit, data re-pull, baseline test run, failure triage, golden snapshot. *(in progress)*
- **Phase 1** — SSOT correctness: stats.py literal fallbacks -> item_effects accessors;
  `lethality_to_flat_pen()` in resistance.py (dedupe stats.py:286 / damage.py:686);
  `refresh_item_effects()` mutate-in-place + wired into `api_update_data`.
- **Phase 2** — cross-boundary SSOT: exclusivity groups served from Python; unified target-stat
  defaults; damage-attribution split moved from app.py route into damage.py; champion option
  metadata served from champion modules instead of app.js `championOptionsDefs`.
- **Phase 3** — champion layer redesign: generic parser with per-champion override specs;
  dedupe common.py/generic_parser.py extraction logic. Design reviewed before implementation.
- **Phase 4** — decompose `calculate_fight_damage` (damage.py:504-2114) into named step functions.
- **Phase 5** — test suite reorg: split test_damage.py; test_ahri.py; conftest fixture adoption;
  Known_Good.txt reconciliation; Kog'Maw/KogMaw naming.
- **Final review** — orchestrator diff review, full verification, patch-drift report for user sign-off.

## Conventions for subagents

- Python: `.venv/Scripts/python.exe` (Windows). Tests import via `src.` package prefix from repo root.
- Never bypass `data_fetcher` for reads; never add network calls to it (CLAUDE.md rule 2).
- Hand-validated expected values in tests are sacred: a refactor must not change them.
  If one changes value under your diff, your refactor has a bug.
- Commit per phase with a descriptive message; do not push.
