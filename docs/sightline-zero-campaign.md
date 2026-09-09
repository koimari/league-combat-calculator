# Sightline-zero campaign

Goal: `.sightline-baseline` from 217 findings to 0, one rule per phase, each phase a pure refactor
merged into `chore/sightline-zero`. Every phase runs the gates in `CLAUDE.md` plus
`sightline gate . --full`, both golden compares print identical, and `sightline baseline .` shows
the count fell.

## Findings per phase

| Phase | Rule | Before | After | Gates |
|---|---|---|---|---|
| 1 | #35 import-topology | 217 | 216 | pytest 15511 passed. pylint 9.74. black, prose lint, ruff, census, full gate clean. Goldens identical. |
| 2 | #54 kind-switch | 216 | 214 | pytest 15528 passed. Same gates clean. Goldens identical. |

## Phase 1: #35

Sightline 0.3 reports one 198-module component. Five deferred imports were its back edges.

| Edge | Cut |
|---|---|
| `champions/inputs` to the registry | `use_options_rows` port, wired from `champions/__init__.py` |
| `stats` to the registry | the eight game formulas moved to `stat_formulas.py` |
| `rune_effects` to `rune_paths` | `rune_paths.publish_rune_compilers()` pushes the tables |
| `champions/engine` to `slotlib` | `SlotCtx`, `SlotParser`, phase constants in `champions/slot_context.py` |
| `slotlib` to `ability_atoms` | `extract_description_*` readers in `ability_prose.py` |

The count fell by one, not two: `SlotCtx` in a leaf made the `(ability, ctx, rank)` #14 clump
typed, and its key replaced `slotlib.extract_named`. Phase 3 dissolves it.

## Phase 2: #54

`DamageClass` owns its resistance axis: `named`, `is_mitigable`, `resistance_name`,
`resistance_term(armor=, magic_resistance=)`. `ability_spec.py` still imports no sibling.

| Function | After |
|---|---|
| `damage._mitigate` | the one home of mitigation arithmetic; gained `ability_mr` |
| `damage._mitigate_hits` | `_mitigate(...) * hits` |
| `compile.knights_vow_target_factor` | `named`, then `is_mitigable` |
| `pricing.price_declared_packet` | `resistance_term`; `MITIGATED_DAMAGE_TYPES` deleted, no reader |
| `transitions.reprice_dynamic_resistance` | `resistance_term`, `resistance_name`; payload unchanged |

Left for the phase that touches those files: ten `damage_type in {...}` membership tests (#54
reads `if` comparisons only) and `participant_timeline._insert_receipt_clone`'s untyped twin of
the Knight's Vow redirect switch.
