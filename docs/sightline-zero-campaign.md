# Sightline-zero campaign

Goal: `.sightline-baseline` from 217 findings to 0, one rule per phase, each phase a pure refactor
merged into `chore/sightline-zero`. Every phase runs the gates in `CLAUDE.md` plus
`sightline gate . --full`, both golden compares print identical, and `sightline baseline .` shows
the count fell. Each phase's PR body holds its gate outputs.

## Findings per phase

| Phase | Rule | Before | After | What moved |
|---|---|---|---|---|
| 1 | #35 import-topology | 217 | 216 | five deferred back edges cut: `use_options_rows` port, `stat_formulas.py`, `publish_rune_compilers()`, `champions/slot_context.py`, `ability_prose.py` |
| 2 | #54 kind-switch | 216 | 214 | `DamageClass` owns `named`, `is_mitigable`, `resistance_name`, `resistance_term`; `_mitigate` is the one mitigation home |
| 3 | #14 data-clump | 214 | 198 | sixteen clumps got a record (table below); three left with reason |

## Residue by phase

Phase 1: moving `SlotCtx` into a leaf made the `(ability, ctx, rank)` clump typed, so its key
replaced `slotlib.extract_named` and the count fell by one, not two.

Phase 2: ten `damage_type in {...}` membership tests (#54 reads `if` comparisons only) and
`participant_timeline._insert_receipt_clone`'s untyped twin of the Knight's Vow redirect switch
stay for the phase that touches those files.

Phase 3 records:

| Record | Home | Dissolves |
|---|---|---|
| `ValueSource(registry, owner)` with `ref`, `label`, `receipt` | `value_ref.py` | both catalog clumps, 73 signatures |
| `EventStamp(time, sequence)` | `state_lifecycle.py` | `(kind, sequence, time)`, `(meta, sequence, time)` |
| `StackEvent`, `AutoSwings` | `damage.py` | `(amount, detail, source)`, the six on-hit simulator inputs |
| `TimelineScene` | `participant_timeline.py` | the three keystone scheduler clumps |
| `EmittedSlot`, `DeclarationSites` | `champions/engine.py`, `module_contract.py` | validator prefix, contract carriers |
| `AmpRiders`, `Window`, `PacketSources`, `CensusSweep`, `ClaimGuard` | one file each | the five single-file clumps |

Phase 3 leaves: `(ability, ctx, rank)` is the calling convention `module_helpers.ranked_slot`
types once on its `body`; its readers take an axis index that is a rank at 763 sites and a level
at 64, so a record would misname one. `(ability, attribute, rank)` are those readers.
`(damage_phase, preserve_reason, reason)` is `SurvivalLedger.skip`, a Protocol with three
implementations; the interface is the type.
