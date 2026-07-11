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

## Phase 2 (completed)

Cross-boundary SSOT. Suite: **700 passed, 0 failed** (686 + 14 new tests).
Golden compare: **identical** to `scripts/golden_baseline.json`. Live smoke test
(Flask on :5000): /api/config, minimal + full /api/calculate, /api/optimize — all pass.

### Part A — exclusivity groups served from Python

`optimizer.py::_EXCLUSIVITY_GROUPS` is now the single source of truth, exposed via
`exclusivity_groups()` (JSON-safe sorted lists) and served by a new **GET /api/config**
endpoint (app.js had no existing bootstrap fetch — its three init fetches are
champions/items/boots — so one new endpoint carries both Parts A and B in a single
round-trip). app.js: `ITEM_EXCLUSIVITY_GROUPS` literal deleted; `itemToGroups` is now
populated from the fetch; `getExclusivityBlock()` enforcement logic unchanged.

**Intended behavior fix:** the hand-copied app.js table had drifted — it was missing
the **Spellblade** group (Trinity Force, Lich Bane, Essence Reaver, Iceborn Gauntlet,
Bloodsong, Dusk and Dawn). The manual item builder now greys out a second spellblade
just like the optimizer already refused to pick one.

### Part B — unified default target stats

**Which defaults actually fired (confirmed by trace):** index.html's inputs carry hard
`value=` attributes — base HP **1000**, bonus **0**, armor **100**, MR **100** — and
app.js always sent all four fields, so app.py's old 2000/50/40 defaults were dead for
UI users (reachable only by direct API callers omitting fields). app.js's own literals
(1000/100/100) fired only when a user cleared an input. Effective default target:
**1000 HP / 0 bonus / 100 armor / 100 MR** — unchanged for a default-input user.

- New `DEFAULT_TARGET` dict at `damage.py` module level (health 1000, bonus_health 0,
  armor 100, mr 100); app.py's api_calculate AND api_optimize use it for absent fields;
  served to the frontend in /api/config.
- **Behavior change (API-only):** direct API callers omitting target fields now get
  1000/100/100 instead of the old 2000/50/40 — the absent-field and empty-input
  defaults now agree.
- app.js: literal fallbacks removed at both payload sites; new `buildTargetPayload()`
  uses the served `defaultTarget`. The wider ~40-line duplication between the calculate
  and optimize payload builders (target stats, fight params, ability ranks, cast order,
  champion options) collapsed into a shared `buildFightPayload(champion)`.

### Part C — damage attribution moved into the calculator

app.py's untested auto-vs-ability classification block moved verbatim into
`damage.py::split_auto_vs_ability(breakdown) -> (auto, ability)`, next to the code that
emits the breakdown keys; docstring documents the attribution rules (on_hit_/spellblade_
prefixes and fiendhunter → auto; "included in" notes skipped; damage_amplification/
execute redistributed by pre-amp ratio, dropped on zero total; sundered_sky excluded).
app.py calls it. TDD: 11 tests written first from current behavior
(`tests/test_damage.py::TestSplitAutoVsAbility`), red before implementation.
*Quirk preserved, noted for Phase 4:* damage.py no longer emits a literal
`damage_amplification` key (amps are `damage_amp_<source>`), so those rows classify as
ability damage even when they amplified autos — replicated exactly, not fixed.

### Tests + verification

- 14 new tests: `TestSplitAutoVsAbility` (11) and
  `tests/test_optimizer.py::TestExclusivityGroupsAccessor` (3, incl. Spellblade-present).
- `node --check static/js/app.js` clean; grep confirms `ITEM_EXCLUSIVITY_GROUPS` and the
  1000/100/100 literals are gone (championOptionsDefs untouched — Phase 3 scope).
- black clean; pylint 9.28/10 on touched src (findings pre-existing: venv E0401s,
  damage.py complexity = Phase 4). Swept while there: two dead imports in optimizer.py
  (`copy`, `item_effects`) removed.

## Phase 3a (completed)

Slot-archetype engine landed; GENERIC path routed through it. Suite: **723 passed,
0 failed** (700 + 23 new tests in `tests/test_engine.py`). Golden compare:
**identical** to `scripts/golden_baseline.json` (all 173 champions; ~161
unregistered ones now exercise the engine). The 12 registered modules untouched.

### What landed

- `src/calculator/champions/engine.py` — **135 lines** (design projected ~130).
  Phase constants BUFF/DEBUFF/DAMAGE/ONHIT/AMP + `PHASE_ORDER`; `SlotCtx`
  (shared mutable `stats`/`target`, readable `results`, `ability()` /
  `rank_for()` helpers); `build_parser(slot_map, champion_name)` returning the
  standard `parse_abilities` signature. Evaluation order (phase, then slot-map
  insertion order) is fixed once at build time; unknown `.phase` values raise
  ValueError at build time; parsers without `.phase` default to DAMAGE. Engine
  emits every non-None entry — zero-damage entries included (the stat_buff trap).
  Slot key "P" maps to results key `"passive"` (engine-level convention).
- `src/calculator/champions/slotlib.py` — **340 lines** (~350 projected at full
  archetype count; holds the 2 step-1 archetypes). ONE extraction core:
  `_sum_modifiers` (absorbs the walk duplicated at common.py:83-107 /
  generic_parser.py:113-132), `extract_named`, `extract_auto` (classifier +
  tiered primary/fallback detection), `extract_cooldown`, `build_stats_context`.
  Entry builders `damage_entry` (incl. the damage-type→result-key mapping with
  mixed split) and `on_hit_entry`. Archetypes: `simple_damage(attr=None,
  dmg_type="auto", casts, source, cooldown_from, ranks)` — auto mode = the old
  generic behavior including in-slot `targeting: "Passive"` on-hit detection —
  and `on_hit_auto()` (P-slot keyword/damageType detection, per-level scaling).
  All four amendment params implemented and unit-tested; later archetypes
  (stat_buff, on_hit_pct_health, toggle_dot, ...) slot in with zero engine changes.
- `champions/__init__.py` — unregistered fallback is now
  `build_parser(GENERIC_SLOTS, ...)`; `GENERIC_SLOTS = {Q/W/E/R: simple_damage(),
  P: on_hit_auto()}`. Registered-module dispatch unchanged. generic_parser.py and
  common.py untouched (deleted at Phase 3 end).

### Equivalence gates

- Golden compare identical (primary gate).
- Direct equivalence tests (survive future baseline churn): ALL champions,
  new engine vs `generic_parser.parse_abilities`, at levels 4/13/18 with
  stats+target, with stats omitted, and under `ability_ranks` overrides;
  plus a dispatcher-level fallback check. Full new-file runtime: 0.09s.
- Engine unit tests: BUFF slot mutating stats before a DAMAGE slot despite
  insertion order; within-phase `ctx.results` dependency (Illaoi pattern);
  zero-damage emission (engine and explicit-attr archetype); `source` /
  `cooldown_from` / `casts` int-and-attribute / `ranks="level"` /
  `dmg_type` override / mixed split / P→"passive" keying.

### Deviations from the design doc (for orchestrator review)

1. **engine↔slotlib import cycle**: slotlib imports the phase constants from
   engine, and the task pins `build_stats_context`'s single home to slotlib —
   so engine uses one deferred (function-level) import of `build_stats_context`,
   commented and pylint-tagged. Alternative was a third constants module;
   rejected as ceremony.
2. **Fallback skill-order name**: `build_parser(GENERIC_SLOTS,
   champion_data.get("name", ""))` — the data's own name, not the dispatcher
   arg — replicating the old generic parser byte-for-byte (matters for Singed,
   the only unregistered champion with a custom skill order).
3. **Defined semantics beyond the old code** (documented in docstrings, tested):
   explicit-`attr` mode always emits (even zero damage) and skips in-slot
   passive auto-detection — the generic drop rule applies only in auto mode;
   a missing/zero `casts` attribute falls back to ×1 (never silently zeroes a
   slot); engine copies `target_stats` into a mutable dict so future DEBUFF
   parsers never mutate the caller's dict (None vs {} is behavior-identical
   in `resolve_scaling`).

### Verification

black clean (engine.py, slotlib.py, __init__.py, test_engine.py). pylint
9.59/10 on touched src — remaining findings are the established pattern (the
fixed 7-arg `parse_abilities` signature; legacy generic_parser/anivia score
9.51 with the same classes) plus two design-mandated shapes: `SlotCtx`'s 9
attributes and `simple_damage`'s 6 params (the design table's signature).

## Phase 3b (completed)

Six champions ported to the slot-archetype engine, simplest-first, one commit
each: Anivia, Annie, Akali, Amumu, Ahri, Ashe. Suite after each commit and at
the end: **745 passed, 0 failed** (723 after 3a + 22 new slotlib unit tests);
every hand-validated expected value unchanged. Golden compare after every
champion: **identical** to `scripts/golden_baseline.json` (the snapshot
captures full ability dicts, so key shapes — not just values — are locked).

### Per-champion (non-blank LOC, before -> after)

| Champion | LOC | Archetypes used | Custom slot fns |
|---|---|---|---|
| Anivia | 121 -> 33 | simple_damage(attr=) x2, **toggle_dot** (new) | — |
| Annie | 178 -> 105 | simple_damage x2, **utility** (new) | `_summon_tibbers` (BUFF: magic-pen stat buff + burst + hardcoded Tibbers aura constants), `_pyromania_placeholder` |
| Akali | 192 -> 68 | simple_damage x2, **proc_damage** (new) | `_perfect_execution` (r2_min/r2_max/missing_hp_scaling shape) |
| Amumu | 180 -> 91 | simple_damage x3 (Q with new `cooldown="recharge"`) | `_despair` (W toggle DoT with per-tick display keys), `_cursed_touch_display`, `_cursed_touch_amp` (AMP-phase `"curse"` pseudo-slot) |
| Ahri | 121 -> 44 | simple_damage x2 (Q: mixed + casts=2), **multi_cast** (new) | `_fox_fire` (initial/subsequent per-flame keys) |
| Ashe | 154 -> 80 | simple_damage x2 | `_rangers_focus` (BUFF: AS stat buff + flurry auto_attack_override, `q_active` gate), `_frost_shot` (override falls back to P when Q absent — reads ctx.results, listed after Q) |

### slotlib additions (340 -> 565 lines, 22 unit tests in test_engine.py)

- `toggle_dot(phases, duration_option, interval, min_duration, cooldown,
  dmg_type, source)` — phase-structured toggle/channel DoT summed into ONE
  standard damage entry; ticks consumed by `(attr, tick_cap)` phases in
  order; cooldown pinned by the caller (0.0 = free toggle, 999.0 =
  cast-once). User: Anivia R.
- `proc_damage(attr, dmg_type, count_option, default_count)` — per-LEVEL
  per-proc damage x option-driven proc count, emitting the
  `proc_count`-shaped entry damage.py schedules outside the rotation.
  User: Akali P (Ambessa/Akshan P join in the next step).
- `multi_cast(casts, attr, dmg_type, source)` — N recasts per activation:
  `damage_per_cast`/`total_casts` (int preserved), deliberately NO cooldown
  key (damage.py spaces recasts itself). User: Ahri R.
- `utility(dmg_type)` — zero-damage display placeholder with real cooldown,
  rank-gated. User: Annie E.
- `simple_damage(cooldown="recharge")` — new cooldown mode: charge abilities
  report rechargeRate at rank (falls back to the plain cooldown). User:
  Amumu Q.
- `extract_value(ability, attribute, rank, modifier_index)` — extraction-core
  addition mirroring `common.extract_leveling_value` (raw leveling numbers:
  pen %, AS %, flurry ratios). Users: Annie R, Ashe Q.

### Behavior notes / deviations for orchestrator review

1. **toggle_dot serves Anivia, not Amumu.** The design table listed Amumu W,
   Alistar E, and Anivia R as toggle_dot users, but their legacy entries
   emit three DIFFERENT key shapes (Amumu W carries `damage_per_tick`/
   `total_ticks`; Anivia R is a standard entry; Alistar E is a
   total-attribute read plus an on-hit addend). Under the "no flag may
   change emitted keys" guardrail + the golden lock on key shapes, toggle_dot
   got the standard-entry shape (Anivia R, the design's `phases` amendment);
   Amumu W stayed a ~30-line custom fn. Flag for the step-3 porter: Alistar E
   will NOT fit toggle_dot either.
2. **Placeholders under the literal "P" key.** Annie P and Amumu P emit
   zero-damage display rows keyed `"P"` (legacy UI shape), but the engine
   maps a returned P-slot entry to `"passive"` — the only slot key that
   doesn't map to itself, so no returned entry can land under `"P"`. Ported
   as custom fns that write `ctx.results["P"]` directly and return None
   (commented in both modules). If more champions need this, consider a
   parser-stamped `result_key` engine extension instead.
3. **stat_buff archetype NOT added yet.** Its two users in this batch
   (Annie R, Ashe Q) both couple the buff with entry parts an archetype may
   not emit conditionally (Tibbers aura + burst; auto_attack_override), so
   both are custom BUFF-phase fns. The archetype should debut in the next
   step with the plain-shaped users (Aatrox/Vayne/Ambessa/Kog'Maw).
4. **Amumu "curse" pseudo-slot.** The Cursed Touch amplifier is an AMP-phase
   parser under the non-ability map key `"curse"`; it mutates the Q/W/E/R
   entries in `ctx.results` and returns None (so the key never appears in
   results). First use of the AMP phase.
5. **Akali `_parse_passive_damage` kept as a seam.** test_akali.py validates
   the passive per-level numbers through it; it is now a 2-line wrapper over
   `extract_named` at rank=level (verified equivalent: the 40-value
   per-level base and single-value scaling modifiers index identically in
   `_sum_modifiers`). Repointing those tests remains step-3 work.
6. **Dropped legacy quirk (unreachable):** Anivia/Ahri's old modules aborted
   the WHOLE parse (`return results`) when a slot's ability list was empty
   mid-loop; the engine skips just that slot. Unreachable with real data —
   every champion has all slot entries — and golden-verified identical.
7. Amumu's old module docstring claimed a `q_casts` option that the code
   never read; the claim was not carried over.

### Verification

black clean on all touched files. pylint **9.80/10** on the seven touched
src modules — remaining findings are the established patterns only:
`simple_damage`/`toggle_dot` 7-param factory signatures (design-mandated,
same class Phase 3a documented) and R0801 duplicate-code on the 5-line
ability/rank gate preamble shared by custom slot fns across champion files.

## Phase 3c (completed)

The remaining six champions ported hardest-last, one commit each:
Kog'Maw `8771046`, Vayne `59af552`, Aatrox `55d5039`, Alistar `45bb62c`,
Ambessa `e6765ec`, Akshan `e5d920a`. Suite after each commit and at the
end: **773 passed, 0 failed** (745 after 3b + 28 new engine/slotlib unit
tests); every hand-validated expected value unchanged. Golden compare
after every champion: **identical** to `scripts/golden_baseline.json`
(the one intermediate diff it caught — a missed `rank` key on Vayne W's
shell — was fixed before that commit). All 12 registered modules now run
on the engine; no champion resisted, none left on the legacy path.

### Per-champion (non-blank LOC, before -> after)

| Champion | LOC | Archetypes used | Custom slot fns |
|---|---|---|---|
| Kog'Maw | 185 -> 109 | simple_damage x2 | `_caustic_spittle` (first live DEBUFF-phase parser: damage + AS stat_buff + shred target_debuff), `_bio_arcane_barrage` (castable shell over `pct_health_per_hit`), `_living_artillery` (wrapper adding missing-HP flags) |
| Vayne | 183 -> 87 | **stat_buff** (new, with `couples`), **by_option** (new), simple_damage x3 | `_tumble` (cooldown scaled by R's published CDR), `_silver_bolts` (cooldown-less shell, floor + stacks/3) |
| Aatrox | 201 -> 66 | stat_buff (percent_of), by_option, **multi_hit_sum** (new) x2, **on_hit_pct_health** (new, scale="level"), simple_damage | — (seam `_extract_r_bonus_ad_percent` kept for tests) |
| Alistar | 115 -> 78 | simple_damage x2 (auto mode — Q/W ARE generic) | `_trample` (tick total + level-scaled add-once empowered auto; confirmed no toggle_dot fit, per the 3b flag) |
| Ambessa | 256 -> 147 | stat_buff (damage_attr), by_option x2, simple_damage x6 | `_sundering_slam` (recast_of wrapper), `_drakehounds_step` (seam `_parse_passive_damage`: per-level base + description-regex AD ratio) |
| Akshan | 266 -> 224 | simple_damage | `_heroic_swing`, `_comeuppance`, `_double_shot`, `_dirty_fighting_procs` — fat custom fns over the three kept regex seams; NOT bigger than the old module |

### slotlib additions (565 -> ~825 lines, 28 unit tests in test_engine.py)

- `stat_buff(attr, stat, mode=flat|percent_of, percent_of, apply_to,
  damage_attr, dmg_type, couples)` — BUFF-phase steroid entry
  (zero-damage unless `damage_attr`); `apply_to` mutates ctx.stats for
  later slots; `couples=(stats_key, attr)` publishes a second leveling
  value into ctx.stats for a dependent slot. Users: Vayne R (flat +
  couples), Aatrox R (percent_of AD), Ambessa R (damage_attr, no
  apply_to — armor pen is fight-engine-applied). Kog'Maw Q was checked
  per the task flag and stayed custom (damage + buff + debuff in one
  entry).
- `by_option(option, {value: parser}, default)` — option-dispatched
  cases; factory-time check that cases share ONE phase; bool-keyed
  cases normalize the option with `bool()`. Users: Aatrox Q, Ambessa
  Q1/Q2, Vayne E.
- `multi_hit_sum(attrs, dmg_type, source, cooldown_from)` — named
  attributes summed into one standard entry. User: Aatrox Q triads
  (both by_option branches). Ahri W / Akshan Q / Ambessa E from the
  design table turned out to be single-attribute reads (simple_damage);
  Alistar E stayed custom per the 3b flag.
- `on_hit_pct_health(attr, dmg_type, scale=rank|level,
  ap_ratio_per_100, floor_attr, stacks_required, source)` — ONHIT-phase
  %maxHP on-hit in the minimal `{name, on_hit}` shell. Direct user:
  Aatrox P (scale="level").
- `pct_health_per_hit(...)` extraction-core helper — the SHARED math
  (base %, per-100-AP ratio, floor, stacks division) under
  on_hit_pct_health, Kog'Maw W, and Vayne W. The three legacy shells
  differ in which fight-engine keys they carry (castable rank/cooldown
  shell vs cooldown-less stacks shell vs minimal passive shell), and
  golden locks key shapes — so per the "no flag may change emitted
  keys" guardrail the archetype owns ONE shell and the other two users
  are thin custom fns over the shared math (same resolution as 3b's
  toggle_dot note 1).
- Internal: `_find_named_leveling` / `_modifier_value` factored out of
  `extract_value` and reused by the new helper.

### The result_key decision (Ambessa Q2)

**No engine extension was needed.** The engine's slot->results mapping
is the identity for every key except `"P"` -> `"passive"`, so a slot
map may simply declare a synthetic `"Q2"` key
(`simple_damage(source=("Q", 1), cooldown_from=("Q", 0))` + a wrapper
stamping `recast_of: "Q"`); rank resolution follows the source slot
("Q"). Phase 3b's suggested parser-stamped `result_key` attribute was
not required; the contract is now locked by
`test_synthetic_slot_key_maps_to_itself`. The same identity mapping
serves Akshan's `"passive_double_shot"` key.

### Behavior notes / deviations for orchestrator review

1. **Kog'Maw Q is the first live DEBUFF-phase parser** but does NOT
   mutate `ctx.target`: damage.py owns shred application at fight
   time, and no parse-time scaling reads target resistances. The phase
   stamp documents the slot's role and its ordering guarantee.
2. **Dropped legacy `> 0` emission gates (unreachable):** Kog'Maw E,
   Aatrox W, Ambessa W/E, Akshan Q gated emission on damage > 0;
   explicit-attr `simple_damage` always emits (3a deviation 3's defined
   semantics). Real data always has positive damage for these
   attributes — golden-verified identical.
3. **Custom fns emitting nothing when an attribute is absent:**
   Kog'Maw W and Vayne W now drop the slot if their %maxHP attribute is
   missing (legacy emitted a zero-damage entry). Unreachable with real
   data; golden-verified identical.
4. **Test seams kept** (test files import module privates; repointing
   is step-4-adjacent work per the design's migration list): Aatrox
   `_extract_r_bonus_ad_percent` (now 3 lines over `extract_value`),
   Alistar `_extract_e_on_hit_damage`, Ambessa `_parse_passive_damage`,
   Akshan `_extract_e_per_shot` / `_parse_passive_proc_damage` /
   `_extract_double_shot_ratio`.
5. **Quarantined constants** (wiki prose, no JSON home, documented at
   module top): Vayne `_SILVER_BOLTS_STACKS = 3`; Akshan
   `_R_CRIT_EFFECTIVENESS = 0.3`, `_R_MISSING_HP_MAX_BONUS = 2.0`.
6. **proc_damage did not gain Ambessa/Akshan P** (3b predicted they
   would join): both passives need description-regex extraction, so
   they are custom fns that emit proc_damage's exact `proc_count`
   shape. proc_damage keeps its one attribute-driven user (Akali P).

### Verification

black clean on all touched files (`black --check` exit 0). pylint
**9.70/10** on the seven touched src modules — remaining findings are
the established classes only: R0913/R0917 on the design-mandated
factory signatures (`simple_damage` 7, `stat_buff` 8,
`on_hit_pct_health` 7, `toggle_dot` 7, `pct_health_per_hit` 8) and
R0801 duplicate-code on the 5-line ability/rank gate preamble shared
by custom slot fns. Full suite `773 passed` and golden compare
`OK: snapshot identical` re-run at wrap-up.
