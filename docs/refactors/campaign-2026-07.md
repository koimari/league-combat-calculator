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
  defaults; damage-attribution split moved from app.py route into damage.py.
  (Champion-option metadata moved to Phase 3 — it lands naturally with the slot specs.)
- **Phase 3** — champion layer redesign: slot-archetype engine per
  docs/refactors/champion-layer-redesign.md (design approved after a 3-way bake-off).
  Includes serving champion option/assumption metadata from the specs, replacing
  app.js championOptionsDefs.
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

## Phase 1 (completed)

SSOT correctness. Suite: **686 passed, 0 failed** (656 baseline + 30 new tests).
Golden compare: **identical** to `scripts/golden_baseline.json`.

### Part A — stats.py behind item_effects accessors

New "Stat-modifying passives" section in `item_effects.py` (10 accessors), each owning
the lookup AND numeric semantics via `_required_effect_value(item, key)` — raises a
KeyError naming the item and key on a broken registry entry (no literal fallbacks
anywhere in the chain):

- `get_ap_multiplier` (Rabadon's + Blackfire, additive — replaces `check_item_passives`,
  now deleted), `get_mana_to_ap_bonus` (Archangel's + Seraph's, shared key shape),
  `get_dawncore_bonus_ap`, `get_flowing_water_bonus_ap`
- `get_passive_attack_speed_bonus` (Bandlepipes melee/ranged + Hexplate + Yun Tal,
  one table-shaped accessor)
- `get_muramana_bonus_ad`, `get_bloodmail_bonus_ad`, `get_steraks_bonus_ad`
  (kept separate — different source stats)
- `get_terminus_max_stack_bonuses` → (bonus armor/MR, pen %), `get_basic_ability_haste`
  (Shojin — replaces stats.py `_get_basic_ability_haste`)

stats.py now contains zero `ITEM_EFFECTS` references and zero item-paired magic numbers.
`.claude/skills/add-item-effect/SKILL.md` updated: Step 4 now teaches the accessor
pattern instead of the `.get(key, fallback)` anti-pattern it used to prescribe.

### Part B — duplicate literal fallbacks removed

**60 literal numeric fallbacks removed** total: 27 in damage.py, 17 absorbed from
stats.py into accessors, 16 inside item_effects.py's own helpers (Terminus, Hullbreaker,
Unending Despair, Collector, the four amp helpers — same bug class, swept while there).
Item-effect lookups now use hard indexing; registry-merge over `_DEFAULT_ITEM_EFFECTS`
guarantees the keys (verified: `passive_parser` never emits `type` keys, so type-driven
loops only ever match default-registered items).

**Disagreeing fallbacks found (Statikk-class, all DEAD code — never fired because the
defaults merge guarantees the keys; clean golden compare confirms):**
- damage.py spellblade `weave_delay` fallback `0.0` vs registry `1.5` — had it ever
  fired, effective spellblade CD would drop 3.0s→1.5s (overstated proc counts).
- damage.py Malignance `mr_reduction` fallback `0` vs `10.0`, `base` `0` vs `180.0`,
  `ap_ratio` `0` vs `0.15` — would have zeroed Hatefog.

**Deliberately retained `.get(key, 0)` (feature-absent markers, NOT stale duplicates,
now comment-guarded in code):** Bloodsong `expose_weakness_*` (polymorphic across all
spellblades), Navori `bonus_crit_damage` (polymorphic across crit_modifiers), and
`_level_scaled_base`'s structural defaults. String `damage_type` fallbacks untouched.

### Part C — refresh + lethality home

- `refresh_item_effects()` now truly mutates in place (`clear()` + `update()`), docstring
  notes why (from-import bindings in `calculator/__init__.py` stay live). Wired into
  `app.py::api_update_data` — refresh runs after the `update_data()` SSE stream completes,
  so "Update to latest patch" refreshes in-memory effects (`fetch_item_data` reads disk
  per call; no memoization to invalidate).
- `lethality_to_flat_pen(lethality, level)` added to `resistance.py` (penetration-math
  home) with the CLAUDE.md domain rule cited; stats.py's inline copy replaced with the
  call. Sole owner per Phase 0b (damage.py's copy died with Opportunity).

### Tests + verification

- New `tests/test_item_effects.py` (25 tests): every accessor (registry-patched so tests
  don't depend on patch numbers), KeyError-names-item-and-key, refresh in-place semantics
  (from-import binding identity + content, stale-entry eviction; `_build_item_effects`
  monkeypatched, registry snapshot/restored).
- `tests/test_damage.py`: `TestLethalityToFlatPen` (5 tests).
- black clean on all touched files; pylint 9.45/10 on touched src (was 9.33; remaining
  findings pre-existing — damage.py complexity is Phase 4, app.py E0401s are pylint
  running outside the venv).
