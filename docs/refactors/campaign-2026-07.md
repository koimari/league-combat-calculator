# Refactor campaign — July 2026

Orchestrated multi-agent campaign. Claude is orchestrator/reviewer; subagents implement.
Branch: `feature/build-optimizer`. Baseline commit: `a5627bd` (WIP), data update: `3a3f4f1` (patch 16.13.1).

## Verification contract (applies to every phase)

1. Wiki data was re-pulled at campaign start (patch 16.13.1). Do NOT re-pull again mid-campaign.
2. Run the full suite with the project venv: `.venv/Scripts/python.exe -m pytest -q`
3. **Baseline pass/fail set** (updated after Phase 0b): **656 passed, 0 failed.**
   Refactor phases must keep the suite fully green with identical values —
   calculations replicate to the 2nd decimal.
4. Golden snapshot: `scripts/golden_snapshot.py`. After any refactor phase: `capture` to a
   temp file and `compare` against `scripts/golden_baseline.json` — must be identical to
   2 decimals. Coverage: all-champion stats/abilities, one-rotation AND sustained
   (auto_attack_uptime=1.0) fights for registered champions, and a 324-item sweep with
   autos enabled (on-hit paths exercised). **If compare shows ANY diff, stop and report
   to the orchestrator — never re-capture the baseline inside a refactor phase.**

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

- When a test value or parsed item looks wrong, check the wiki patch history FIRST:
  https://wiki.leagueoflegends.com/en-us/<Champion_or_Item_Name> — its "Patch history"
  section says authoritatively whether something was buffed/nerfed/reworked/removed.
  (Example: Opportunity — "V26.09: Removed from the game" — settled in one fetch what
  JSON archaeology couldn't.)

- Python: `.venv/Scripts/python.exe` (Windows). Tests import via `src.` package prefix from repo root.
- Never bypass `data_fetcher` for reads; never add network calls to it (CLAUDE.md rule 2).
- Hand-validated expected values in tests are sacred: a refactor must not change them.
  If one changes value under your diff, your refactor has a bug.
- Commit per phase with a descriptive message; do not push.

## Phase 0b (completed)

Resolved all 9 baseline failures. Suite: **656 passed, 0 failed** (was 652 passed / 9 failed).
Count reconciliation: 661 baseline tests − 7 Opportunity tests deleted + 2 new Voltaic tests = 656.

### Parser fixes (real product bugs)

**Statikk Shiv — Electrospark rework** (`passive_parser._parse_statikk_shiv`)
Wiki reworked the passive to ONE empowered chain-lightning attack: 60 magic damage,
bouncing to up to `{{pp|4 to 8 by 1|...}}` targets. The old `next (\d+) basic attacks`
regex silently failed, so the stale default `empowered_auto_count=3` won — the calculator
overstated single-target Statikk damage ~3×. Parser now emits `empowered_auto_count=1`
plus `chain_targets_min=4` / `chain_targets_max=8`; `_DEFAULT_ITEM_EFFECTS` updated to
match. damage.py's single-target model is one 60-damage proc per energize (chain has
nothing to bounce to vs one target).

**Voltaic Cyclosword — Firmament rework** (`passive_parser._parse_voltaic_firmament`)
Wiki reworked Firmament to current-health damage: `{{rd|9%|7%}}` of the target's CURRENT
health as physical (melee 9% / ranged 7%), "capped at 200 against non-champions". The old
flat `(\d+) '''bonus''' physical damage` regex failed, so the stale flat `base=100` default
won. Parser now emits `current_hp_ratio_melee=0.09`, `current_hp_ratio_ranged=0.07`,
`damage_cap=200.0` (JSON text confirmed ranged = **7%**, not the 0.06 in one triage note —
0.06 is BoRK's ranged ratio). damage.py computes `min(ratio × target health at first auto,
cap)` mitigated by armor, following the BoRK current-HP convention (proc lands on the first
auto at full target health) and the Titanic Hydra melee/ranged-key pattern.
*Modeling note for review:* the wiki scopes the 200 cap to non-champions; we apply it
unconditionally (conservative vs high-HP champion targets).

### Stale test constants (parser correct; balance drift at 16.13.1)

| Test | Old | New | Derivation from JSON |
|---|---|---|---|
| test_damage.py::TestParseAhriAbilities::test_q_rank3_with_60ap | 120.0 | 115.0 | Q "Damage Per Pass" r3 = 85 + 0.5×60 (both magic & true passes) |
| test_damage.py::TestParseAhriAbilities::test_q_rank5_with_215ap | 247.5 | 242.5 | r5 = 135 + 0.5×215 |
| test_damage.py::TestActualizerFightDamage::test_ahri_q_with_actualizer_active | ~323 | 314.55 | per pass 135+0.5×90AP=180; magic vs 100 MR=90 + true 180 = 270; ×1.165 amp (1.15 + 0.005×300/100) |
| test_ashe.py::TestQRangersFocus::test_q_flurry_ratio_rank5 | 1.40 | 1.30 | "Total Damage Per Flurry" 110/115/120/125/130 (+5/rank) |
| test_ashe.py::TestQRangersFocus::test_q_active_auto_damage | 420.0 | 390.0 | 200 AD × 1.30 × (1 + 0.50 crit) |
| test_stats.py::TestNewItemStats::test_flowing_water_rapids_ap | 80 | 75 | Rapids grants 40 AP (was 45) + Ahri base 35 |

Also updated (same Statikk rework, found on first full run):
test_damage.py::TestNewItemDamageEffects — `test_statikk_shiv_first_3_autos` →
`test_statikk_shiv_one_empowered_auto` (procs 3 → 1); `test_statikk_shiv_fewer_autos_than_3`
→ `test_statikk_shiv_no_autos_no_proc`.

### Opportunity — removed as dead code

Item removed from the game in **V26.09** (user-confirmed via wiki patch history), hence
absent from items.json. Deleted: `_DEFAULT_ITEM_EFFECTS["Opportunity"]` and
`get_opportunity_bonus_lethality()` (item_effects.py), `_parse_opportunity_preparation` +
registry entry (passive_parser.py), the entire `prep_lethality`/`effective_armor_prep`/
`prep_autos` plumbing in damage.py, and tests/test_damage.py::TestOpportunityPreparation
(7 tests). No references existed in optimizer.py, stats.py, or static/js/app.js.
Side effect: damage.py's copy of the lethality→flat-pen formula (old damage.py:686) is
gone — stats.py:286 is now the sole owner, simplifying the Phase 1 dedupe task.

### Golden baseline

Re-captured `scripts/golden_baseline.json`; `compare` clean. Diff vs old baseline:
**only `metadata/git_head` changed** — zero value entries. Explanation (verified, not a
red flag): every snapshot fight runs with `auto_attack_uptime=0.0`, so on-hit-once procs
(Statikk/Voltaic) never fire in any snapshot scenario, and Opportunity was never in
items.json. Known blind spot: the golden harness does not exercise auto-attack/on-hit
item paths; consider an uptime>0 section if Phase 4 touches them.
