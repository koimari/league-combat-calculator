# Fight engine navigability (sightline-zero phase 5, rewritten)

Goal: a reader can answer "where does this champion's damage with this item come from, at each
step" by opening one file per step, and adding an item touches one declaration per fact. Sightline
#27's line counter is a proxy for this, not the target: its residue stays baselined with
reasons. One branch, `sightline/27-navigability`, one PR at the end.

## Order

| # | work | proof |
|---|---|---|
| 1 | `damage.py` bands into the `fight/` package | goldens identical, bench flat, every band under one concept name |
| 2 | one item, one home: the on-hit and single-proc functions become loops over catalog declarations; a per-fight trace | Dusk and Dawn on Kog'Maw traced row by row; a new on-hit item is one catalog entry plus one test |
| 3 | stages 1 to 8 of the #27 plan (test fixtures, small leaves, defenses, `program` and `survival` layers, shared ledgers, interpreters, eligibility families, the champion package) | goldens identical |
| 4 | stages 10 and 11 (the `ability_spec` leaves `quantity` and `control_spec` with their reader codemod; compositions: `pipeline` receipts, `champion_loadout`, `item_support_effects` per item family, `support_effects`, optimizer, bis, rotation) | goldens identical |

Not taken: stage 12 (scripts and test files) and stage 9 (parser and registry carves), which
move lines and help no reader.

## Step 1: the `fight/` package

`src/calculator/damage.py` keeps `calculate_fight_damage`, `FightConfig`'s public import path,
`split_auto_vs_ability`, `split_by_damage_type` and `DEFAULT_CAST_ORDER`; its body becomes the
ordered list of step calls. Every other definition moves into `src/calculator/fight/`, a package
whose subpackages are the engine's steps in the order the orchestrator runs them. Each
`__init__.py` holds one docstring line naming its step and nothing else: no re-export.

| subpackage | what it means | modules (defs per `sl_scratch/phase-27/modules.md`, stage 13) |
|---|---|---|
| `fight/` | the vocabulary every step reads | `config`, `state`, `results`, `resists`, `mitigation`, `cast_slots`, `empower_declaration`, `cast_control_marker` |
| `fight/ledger/` | the reconstructed event ledger and what reads it | `event_rows`, `event_ledger`, `coverage`, `pool_walk`, `breakdown` |
| `fight/setup/` | resolving the request into a `FightState` | `combat_state`, `stat_buff_ultimates`, `target_debuffs` |
| `fight/rotation/` | which abilities cast when, admitted against resources, and what each cast prices | `cast_parts`, `cast_schedule`, `cast_plan`, `resource_admission`, `energy_walk`, `mana_declarations`, `mana_walk`, `stack_timeline`, `ability_rotation`, `precomputed_procs`, `dot_ticks`, `shaped_charge` |
| `fight/autos/` | the swing schedule and everything that rides a basic attack | `swing_schedule`, `simulation`, `on_hit_stream`, `empower_windows`, `on_hit_layering`, `spellblade`, `decaying_health_walk`, `single_proc_on_hits`, `copied_on_hit`, `on_hit_healing` |
| `fight/items/` | item packets that are not on-hits | `burns`, `proc_triggers`, `cast_procs`, `eclipse_stack_gate`, `actives`, `muramana`, `energized_packets` |
| `fight/runes/` | the rune page's procs, keystones and amplifiers | `streams`, `page_damage`, `keystone_casts`, `keystone_ledger_walk`, `keystone_attacks`, `keystone_stacks`, `amplifiers` |
| `fight/stacks/` | champion stack resources as receipt ledgers | `account`, `senna`, `ashe`, `ksante`, `heimerdinger`, `bard`, `aurelion_sol`, `rengar` |
| `fight/after/` | what runs over the finished ledger | `amp_chain`, `amplifiers`, `lethality_windows`, `stored_damage`, `reprice`, `empowered_swings`, `shield_outcome` |

Decisions. `Resists` and `_mitigate` stay together (one file for pricing one instance).
`FightState` and `FightConfig` are leaves under `fight/` because every step annotates them and
`damage.py` has no `from __future__ import annotations`. The five functions over 500 lines
(`mana_walk`, `ability_rotation`, `simulation`, `on_hit_layering`, `single_proc_on_hits`) move
whole; step 2 restructures the last two. `_restate_declaration` moves to `survival/pricing.py`.
Where two maps name one band two ways (`resource_admission` and `cast_plan`), the assignment file
picks one and the DAG check decides.

Mechanics. One tool, `scripts/extract_modules.py`, reads an assignment file (new module, docstring
line, defs in source order), cuts each top-level def by AST span with its leading comment block,
computes each new module's imports from its free names against the source's import block and
the other assignments, refuses any cycle, and rewrites the residue and every reader
(`from .damage import X`, `damage.X`, and `monkeypatch.setattr("src.calculator.damage.X")`
targets) to the new home. Statement order inside a body never changes. The tool stays, with
tests, because steps 3 and 4 drive it with their own assignment files.

## Step 2: one item, one home, and the trace

Design panel before code. Fixed points: `interpreters/on_hit_strike.py`, `spellblade.py`,
`periodic.py` and the catalog's `ValueSource` rules are the shape; every item branch inside
`on_hit_layering` and `single_proc_on_hits` that names an item becomes a catalog declaration
priced by its family interpreter, until each function is a loop over declared rules.
`item_coverage`'s hand-listed pricing homes become derived from the catalog. The trace is a
per-fight ledger a reader can print: one line per priced packet with time, source, raw, the
resistance it met, the amplifiers applied and the mitigated amount, produced from the receipts the
engine already publishes, exposed through `calculate_payload`. Acceptance: Kog'Maw with Dusk and
Dawn traced end to end, and a new on-hit item added through one catalog entry with its trace as
the test oracle.

## Steps 3 and 4

The `#27` plan's stage tables and `modules.md` name every module and def. Each source file is one
assignment file for `extract_modules.py`; files are disjoint, so they run in parallel.

## Gates, per step

Both `golden_snapshot.py compare` targets identical after every assignment file lands (steps 1, 3
and 4 move import order; compiled slot order and ledger insertion order are numeric). Fresh-process
import of every new module. `pytest -n auto`. `black`, `pylint src/ --fail-on=E0601,E0602`,
`prose_lint.py`, the ruff tree gate, `coverage_census.py check`, `sightline audit . --quiet`
prints nothing new under any rule, `sightline gate . --full`. `scripts/bench_request.py --compare
benchmarks.md` before step 1 and after each step: import cost may not get worse.

Paid in the same commit as the move: `test_literal_defaults.ROOTS`, `ER5_TAIL`, `ROW_READS`;
`test_architecture.FRONT_DOOR_FRONTIER` and both `DAMAGE_PATH` rules; `rename_evidence.EVIDENCE_HOMES`;
`data_registry`'s memo table; `item_coverage`'s pricing-home strings; `docs/behavior-frontier.json`
regenerated (its four totals are the invariant); architecture.md's module map gains the `fight/`
package; CLAUDE.md quirks that name a moved symbol. Every other `docs/` and `data/` file byte
identical. At the end, `sightline baseline .` and the campaign doc record the count.
