# Golden recapture — roadmap session 4 batch H, 2026-08-21

Champions: Talon, Thresh, Varus, Vayne, Vladimir (one `out_of_scope` slot
each per roadmap-100.md sec 2.2's 1-slot row).

Pre-recapture compare: **0 diffs** — `scripts/golden_snapshot.py compare
scripts/golden_baseline.json` reported `OK: snapshot identical to
scripts/golden_baseline.json`. All five closures in this batch are
stale-label fixes (the Ryze/Senna/Swain/Tahm Kench precedent, batch G;
originally the Malzahar/Nasus precedent, batch D) — every slot already
emitted a sourced zero-damage row before this pass, so `MODULE_COVERAGE`
was the only stale artifact. No recapture was required or performed.

## Per-champion disposition

- **Talon E (Assassin's Path):** stale-label fix, `out_of_scope` ->
  `no_damage`. The pinned reviewed packet (`static/reviewed-packets.json`)
  already declares E `kind="no_damage"` (parkour dash, no enemy-damage
  formula). E is not one of the slots the module reassigns (only P/Q/W/R
  are overridden below `build_packet_module`), so it already fell to the
  compiler's default `_no_formula_parser` branch. Zero golden movement.
- **Thresh W (Dark Passage):** stale-label fix, `out_of_scope` ->
  `no_damage`. The pinned reviewed packet declares W `kind="no_damage"`
  (lantern dash/ally shield, no enemy damage). W is not reassigned by this
  module (only P is overridden; W keeps the packet's default no-damage
  slot). The separate ally-support Dark Passage shield priced through the
  ally-scanner (documented in ASSUMPTIONS) is a distinct, already-modeled
  mechanism, unaffected by this label fix. Zero golden movement.
- **Varus P (Living Vengeance):** stale-label fix, `out_of_scope` ->
  `no_damage`. The pinned reviewed packet declares P `kind="no_damage"`
  (on-takedown attack-speed buff, self-directed only). P was already
  wired to a hand-authored parser (`_living_vengeance`) that returns
  `total_raw=0.0`, `parts=()` — a genuine sourced zero-damage entry, just
  authored outside `build_packet_module`. Zero golden movement.
- **Vayne P (Night Hunter):** stale-label fix, `out_of_scope` ->
  `no_damage`. The pinned reviewed packet declares P `kind="no_damage"`
  (bonus movement speed toward slowed/immobile enemies, self-directed
  only). P has never been wired into `SLOTS` (deliberate, documented
  since before this pass) — the Tahm Kench E precedent (batch G) for an
  absent-but-sourced-no_damage slot: the fight ledger never invents an
  enemy hit for it, and `parse_abilities`' output is unchanged (P remains
  absent). Zero golden movement.
- **Vladimir P (Crimson Pact):** stale-label fix, `out_of_scope` ->
  `no_damage`. The pinned reviewed packet declares P `kind="no_damage"`
  (bonus-health-to-AP self stat conversion, no enemy-damage row). P is
  not one of the two slots this module's `slot_parsers` reassigns (only
  W and E are overridden), so it falls to `build_packet_module`'s default
  no-damage branch. Zero golden movement.

## Downstream pinned-assertion fix (found in per-champion validation)

`tests/test_vladimir_e_charge_time.py` hard-pinned
`MODULE_COVERAGE["P"] == "out_of_scope"` in two places
(`TestSourceEvidence::test_module_declaration_pinned`'s full-dict
equality and `TestRegressionSurface::test_module_meta_pins_unchanged`'s
single-key assertion). Both updated to `"no_damage"` — the sourced
reclassification, not a fight-computation change. Grepped the other four
champions' test files for an equivalent pin; none found (all four passed
`pytest -k <champion>` clean on the first run after their edits).

## Validation

- Per-champion: `pytest -k talon` (10 passed), `-k thresh` (105 passed),
  `-k varus` (20 passed), `-k vayne` (74 passed), `-k vladimir` (2 failed
  on first run — the pinned-assertion fix above — 79 passed after fix).
- Batch: `pytest -k "talon or thresh or varus or vayne or vladimir"` —
  288 passed.
- `tests/test_f2_rotation.py` + `tests/test_f3_rotation_all.py` +
  `tests/test_ci_evidence_parity.py` — 92 passed (no new OPTIONS were
  added in this batch, so no `_ROTATION_CLASSIFICATIONS` entries were
  needed).
- Golden: `scripts/golden_snapshot.py compare scripts/golden_baseline.json`
  — identical, 0 diffs. No recapture performed.
- `black --check src/ tests/ scripts/`: `vayne.py`'s new
  `MODULE_COVERAGE` ternary line exceeded the line-length limit; ran
  `black` on that one file (the standard formatting pass, not a logic
  change) and re-verified `pytest -k vayne` stayed at 74 passed. Full
  `black --check` then reported all 595 files clean.
- `pylint src/calculator/champions/{talon,thresh,varus,vayne,vladimir}.py`:
  9.72/10, identical to the pre-edit baseline (verified via `git stash`
  before/after) — same pre-existing `invalid-name`
  (module-level `OPTIONS`/`SLOTS` reassignment pattern) and
  `duplicate-code` (R0801) findings, only line numbers shifted from the
  added docstrings. No new findings.
- Full suite: `pytest -q --tb=no -rf` — **8392 passed, 0 failed.**
