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
| 4 | #11 structural-clones | 198 | 92 | 51 groups dissolved: 16 kit mechanics in `champions/shared_mechanics.py`, interpreter front doors in `item_behavior` and `value_ref`, `gate_receipt.emit_receipt`; the finished `migrate_single_hit_slots.py` codemod deleted; two left |

## Residue by phase

Phase 1: `SlotCtx` in a leaf made the `(ability, ctx, rank)` clump typed; its key replaced
`slotlib.extract_named`.

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

Phase 4 leaves: `inputs.int_option`/`float_option` are two typed delegations to `_option`, and
the typed signature is the reason two names exist. `optimizer._build_receipt_key` pairs with a
test helper that shares one comprehension and no fact.
