# Full-Coverage Campaign — no combination withholds

## Goal

Every champion (173) × every public fight mode (4) × every legal loadout (209 ordinary-SR
items, all slots and quest states) × every keystone (17) computes through every public
endpoint — no withhold, refusal, or fail-closed path fires for any reachable selection.

## Frontier (measured 2026-08-18, runtime census through `calculate_payload`)

| Class | Population | Trigger |
|---|---|---|
| Fight-mode restriction | Vi, Kai'Sa, Karthus, Taliyah × all non-rotation modes, attacker & roster | `SUPPORTED_FIGHT_MODES` in module |
| Unmodeled keystones | 13 of 17 | `rune_effects._KEYSTONE_COMPILERS` has 4 |
| Champion kit coarse | Fizz W (DoT, no ticks), Shen Q (auto-coupling) | `damage._event_timeline_coverage` |
| Fimbulwinter control token | all 169 unrestricted champions | ability events lack reviewed `cc_kind` |
| On-hit event family | 26 champs (`auto_attacks` under AS steroids), 14+ (`on_hit_items_Q/W/E/R`), phantom, Rageblade, Dusk and Dawn, Horizon Focus, Kraken, Hullbreaker | rows author no events |
| Item proc precision | Eclipse/Muramana/Bastionbreaker on 17 champs | cast rows lack `event_order_certified` |
| Target-side Protoplasm | any enemy whose Lifeline triggers, timed | `target_Protoplasm Harness` never authors ticks |
| Lifeline expiry refusal | timed fight outlives shield window | `ThresholdExpiryWithheld` → 400 |
| BIS unrankable | `THEORETICAL` leaf in candidate | `UnrankableNumber` (TypeError) → 500 |

## Decisions

1. **Coverage = no refusals.** Silent-zero modeling gaps (self-healing absent for ~116
   champions, grey health for all but 5) do not withhold and are out of contract; they are
   flagged in the close report as the next campaign's frontier.
2. **Custom cast orders stay unsupported** for every champion (`capabilities.py` declares
   it for all participant kinds; the four certified-sequence reasons remain API-side).
   Lifting that is a feature, not coverage.
3. **The withhold machinery is kept, its trigger population emptied.** Every fail-closed
   check survives; closure means the census finds nothing for it to fire on.
4. **The four champions get real timed models**, each on the established engine pattern:
   Vi — shared auto+ability stack counter with expiry (Aurora `count_ability_hits` +
   Braum-style walk for the 4s windows); Kai'Sa — Plasma persistence, Supercharge AS
   window on the existing buffed-rate swing scheduler, R reset; Karthus — Defile as
   persistent toggle with mana-exhaustion cutoff, Lay Waste cadence, Death Defied
   post-death window; Taliyah — Worked Ground terrain state persisting across casts.
   Sources: cached wiki (`data/`), Community Dragon for anything the wiki degrades on.
5. **Event certification closes engine-side per mechanism, not per pair.** One fix per
   coarse-row producer in `damage.py` (swing schedule under AS modifiers, ability-attack
   on-hit rows, phantom rows, double-on-hit, damage-amp, spellblade edge) certifies all
   champions holding that item class at once.
6. **`cc_kind` is authored by champion modules** — the module owns its kit's crowd-control
   facts, same as its timing. The Fimbulwinter/Everlasting control token clears wherever
   every damaging ability event carries a reviewed kind (or the module declares its kit
   cc-free).
7. **Eclipse/Muramana close engine-side, not by module certification.** Runtime tracing
   (Wave 1C) showed the 16 champions' failures are one defect: cast times rounded to 3
   decimals (damage.py:4253) versus raw authored event times break both proc walkers'
   cursor matching (damage.py:7748, 8674); a rounding-aware comparison plus a
   positive-total gate in `_muramana_proc_events` (mirroring Eclipse's, damage.py:7714)
   closes 32/32 probes with zero module edits. Stamping certifications there would be
   certification theater and is banned.
8. **Protoplasm's target-side heal authors its sourced 5 s tick cadence**; Lifeline
   expiry becomes a modeled event (`ThresholdExpiryWithheld` retired), so certified items
   survive fights of any duration.
9. **All 13 remaining keystones get compilers** in `rune_effects.py` from `data/runes.json`
   under rule 5 (typed accessors, missing keys raise, no literal fallbacks).
10. **`UnrankableNumber` translates to a 400** at the app boundary (kept as TypeError
    internally per its bypass design); optimizer's `-inf` drop gains a `withheld_builds`
    row like its siblings.
11. **The census becomes the owning gate**: `scripts/coverage_census.py` sweeps the real
    pipeline (champion×mode, champion×item legal-slotted incl. boots tiers and support
    quest states, champion×keystone, certified-item×enemy-champion, crossover curves),
    writes `docs/coverage-census.json`, and fails on any withhold/coarse entry. Golden
    baseline re-captures per wave with explained diffs.

## Shape

- `src/calculator/champions/{vi,kaisa,karthus,taliyah}.py` — timed-mode models; mode and
  curve restriction constants deleted at each one's close.
- `src/calculator/champions/{fizz,shen}.py` (+ the 17 proc-precision modules, and cc_kind
  declarations kit-wide) — authored events / certifications.
- `src/calculator/damage.py` — per-mechanism event authoring; no classifier changes.
- `src/calculator/interpreters/threshold_defense.py`, `shield_ledger.py` — modeled
  Lifeline expiry; target-side tick authoring.
- `src/calculator/rune_effects.py` — 13 new `_compile_*` entries.
- `src/app.py` — UnrankableNumber → 400. `src/calculator/optimizer.py` — disclosure row.
- `scripts/coverage_census.py` → `docs/coverage-census.json` — the gate and its receipt.
- Tests: unpin the restriction tests named in the recon (test_event_order_certification,
  test_vi/kaisa/karthus/taliyah, test_app roster-window tests), add per-mechanic coverage.

## Success criteria

1. `scripts/coverage_census.py` full sweep reports **zero** entries in every withhold
   class; `docs/coverage-census.json` committed showing it, and CI's `coverage-census`
   job plus `patch_update.py run` hold the gate green against the live pipeline.
2. `/api/champions` publishes all four `supported_fight_modes` for all 173 champions;
   comparison curves return populated for all 173.
3. Each of the four champions: a timed-mode runtime probe shows the unlocked mechanic
   moving the numbers — Vi's W proc count grows with fight duration and ambient autos;
   Kai'Sa's Plasma ruptures recur across a 20 s window; Karthus's Defile stops at mana
   exhaustion; Taliyah's second Q on Worked Ground prices the changed damage — each pinned
   in that champion's test file with quoted engine output.
4. All nine certified-timeline items on any enemy champion in timed mode return results
   (census C2 axis, 9 × 173, zero withholds) including fights long enough to outlive the
   Lifeline window.
5. All 17 keystones resolve and `keystone_catalog()` publishes `implemented: true` for
   every row; each compiler's numbers trace to `data/runes.json` through typed accessors.
6. `pytest` (≥ 8858 tests), `pylint src/`, `black --check`, and the golden gate pass;
   every golden diff is explained in its capturing commit.
7. No public endpoint returns a 500 for any census-swept request (BIS probes included).

## Banned shortcuts

- No deleting or loosening a withhold check to satisfy criterion 1 — the check fires on a
  synthetic uncovered fixture in its test, proving it still works.
- No `event_precision` stamped where authored events don't sum-reconcile — the classifier
  in `damage._event_timeline_coverage` is not edited (tolerances, rules, or vocabulary).
- No additions to `EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES`; it shrinks or stays.
- No mode support lifted by constant deletion alone — criterion 3's probes must show the
  mechanic responding to the timeline, not a one-rotation result relabeled.
- The census gate calls the real `calculate_payload`/optimizer paths — no mocks, no
  cached responses, no reduced roster.
- Keystone numbers appear only in `rune_effects.py` reading `data/runes.json` — grep-clean
  everywhere else (rule 5's existing enforcement extends to the 13 new compilers).
