# Sightline-zero campaign

Goal: `.sightline-baseline` from 217 findings toward 0, one rule per phase, each phase a pure
refactor. Every phase runs the gates in `CLAUDE.md` plus `sightline gate . --full`, both golden
compares print identical (or a receipt under `docs/receipts/expected-golden-diff-*` declares every
moved leaf), and `sightline baseline .` regenerates the file. Each PR body holds its gate outputs.

## Findings per phase

| Phase | Rule | Before | After | What moved |
|---|---|---|---|---|
| 1 | #35 import-topology | 217 | 216 | five deferred back edges cut: `use_options_rows`, `stat_formulas.py`, `publish_rune_compilers()`, `champions/slot_context.py`, `ability_prose.py` |
| 2 | #54 kind-switch | 216 | 214 | `DamageClass` owns `named`, `is_mitigable`, `resistance_name`, `resistance_term` |
| 3 | #14 data-clump | 214 | 198 | sixteen clumps got the record that carries their idea; three left |
| 4 | #11 structural-clones | 198 | 92 | 51 groups dissolved into `champions/shared_mechanics.py` and the interpreter front doors; two left |
| 5 | #27 purchase-price, reframed as navigability | 92 | 63 | `damage.py` into the `fight/` package, the per-fight trace, one home per item mechanic, 96 leaves through `scripts/extract_modules.py`; 53 #27 keys stay |

## Residue

Phase 3: `(ability, ctx, rank)` is `module_helpers.ranked_slot`'s body convention and its readers
take an axis index that is a rank or a level; `(ability, attribute, rank)` are those readers;
`(damage_phase, preserve_reason, reason)` is the `SurvivalLedger.skip` Protocol.

Phase 4: `inputs.int_option`/`float_option` are two typed delegations to `_option`;
`optimizer._build_receipt_key` pairs with a test helper that shares one comprehension.

Phase 5: the plan `docs/plans/2026-09-09-fight-navigability.md` names every #27 leave: the
orchestrators whose fan-out is their own steps, `item_effects` under rule 5, the closed-union
catalogs, the champion modules whose hot symbols are reviewed constants, the gate scripts and the
test matrices. Four keys moved rather than cleared (`fight_params`, `champion_loadout`,
`ally_packet_shape`, `cast_edge_inference`) and five champion modules crossed the fan-out ceiling
when `slotlib` and `state_lifecycle` split (`ashe`, `rengar`, `bard`, `senna`, `ksante`). The
counter is a proxy: the reader's questions are answered by `scripts/fight_trace.py` and the
`fight/` layout, and a new on-hit item is one cached record, one parse line and one reference
entry (`tests/test_synthetic_on_hit_item.py`).
