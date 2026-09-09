# Sightline-zero campaign

Goal: `.sightline-baseline` from 217 keys to 0, one rule per phase, each phase a pure refactor
merged into `chore/sightline-zero`. Every phase runs the gates in `CLAUDE.md` plus
`sightline gate . --full`, both golden compares must print identical, and `sightline baseline .`
must show the key count fell.

## Baseline keys per phase

| Phase | Rule | Before | After | Gates |
|---|---|---|---|---|
| 1 | #35 import-topology | 217 | 216 | pytest 15511 passed, 43 skipped. pylint 9.74. black, prose lint, ruff tree gate, coverage census, sightline full gate: clean. Goldens identical. |

## Phase 1: #35

Sightline 0.3 reports the whole 198-module component as one finding, not only the
`champions/inputs` deferral the old baseline reason named. Five deferred imports were the back
edges; each is now a top-level import or an inverted call.

| Edge | Cut |
|---|---|
| `champions/inputs` to the registry | `use_options_rows` port; `champions/__init__.py` wires `declared_options_rows` |
| `stats` to the registry | the eight game formulas moved to `stat_formulas.py`; `stats` imports the registry at top level |
| `rune_effects` to `rune_paths` | `rune_paths.publish_rune_compilers()` pushes the tables; `src/calculator/__init__.py` calls it |
| `champions/engine` to `slotlib` | `SlotCtx`, the phase constants and `SlotParser` moved to `champions/slot_context.py` |
| `slotlib` to `ability_atoms` | the `extract_description_*` readers moved to `ability_prose.py` |

`rotation_resolver` and `interpreters/charged_strike` also hoisted deferred imports that hid no
cycle. The key count fell by one, not two: moving `SlotCtx` into a small leaf made the
`(ability, ctx, rank)` #14 clump across 13 champion slot functions typed, so its key replaced the
`slotlib.extract_named` key. Phase 3 dissolves it with the other #14 clumps.
