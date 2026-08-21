# Engine-retirement campaign

Head at start: `7bb9701e` (PR #202 merge). Trigger: the PR #202 audit found the branch
built a second engine (`program/`, `interpreters/`, `trigger_stream.py`) beside the first
instead of retiring it — `src` 120k → 168k lines, `calculate_payload` 4.9 → 10.5 ms warm,
two hand-synced packet paths, and a test corpus a third of which pins tree shape.

**Goal.** One engine, one home per fact, no literal fallbacks, a pinned latency number,
and a `src` tree where every path is live. Deletions and moves; no new behavior.

**Invariant for every unit.** Zero diffs in `golden_snapshot.py compare` (pair and
coupled, including exact) unless the unit is a named correctness fix with a receipt.
`pytest -n auto`, `black --check`, `pylint src/` green in the worker's worktree before
it reports. A unit that must move a number stops and reports `ISSUES`, it does not
re-capture.

**Shape.** Integration branch `engine-retirement` off `main`. Each writing worker owns a
file set in its own worktree/branch (`er/<unit>`), merges into the integration branch
through the orchestrator, who reconciles the diff against the report before the next
dependent wave. Derived receipts (`behavior-frontier.json`, `cast-dependency-audit.json`,
plan locators, `runes.json` effects) are regenerated on the merged tree, never hand-merged.
Log: `decisions.tsv` in the session scratchpad; folded into this doc's results at close.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The compiled path (`program/`, `add_engine_result`) is the survivor; `_pair_packet` + `add_packet` are retired. | `program/compile.py:852` already documents `add_engine_result` as equivalent-minus-enrichment; the receipt's enrichment becomes a view of compiled actions, not a second compiler. |
| D2 | Interpreters become one `(family, lane, fields_fn)` table. | 33 classes whose Pair/Walk bodies differ by a lane constant; the lane set is restated in 4 places. |
| D3 | Rule 5 applies to every cached-data read: a `.get(key, literal)` on wiki/cache data either becomes a typed accessor that raises naming item+key, or is proven unreachable and deleted. | `item_effects.py:4567` is the exact shape that hid the 3× Statikk Shiv overstatement. |
| D4 | `trigger_stream.CAPABILITIES` is the only item→stream declaration; hand-kept item name sets become projections of it or are deleted. | `architecture.md:30` already claims this; the tree has two survivors. |
| D5 | `MODULE_CC` is the one CC declaration; parts-level `cc_kind` stamps in modules are moved into it and the contract refuses the parts-level form. | 164/177 declare; 6 stamp parts directly; 3 declare nothing. |
| D6 | A test survives if it would catch a behavior or numeric regression. A test that pins source line numbers, counts, AST shape, or receipt tree shape without a behavior behind it is deleted with its receipt, unless it is a declared growth gate. | ~790 tests go red on pure refactors; that is cost, not safety. |
| D7 | Docstrings and comments carry current state only. Campaign IDs (Amendment/Ruling/D-NN), and any docstring longer than its body, are rewritten or cut; a lint pins both at zero. | `~/.claude/CLAUDE.md` "Minimal prose"; 539 citations, 101 over-long docstrings. |
| D8 | Latency gets a home: `benchmarks.md` + a pinned script, captured **before** any deletion lands and re-captured at close. | No `benchmarks.md` exists; the 2.1× regression is untracked. |
| D9 | The "18-family union" finding is dropped: `RULE_FAMILY_COUNT = 18` is families, the 34 `RulePayload` members map onto them via `PAYLOAD_FAMILY`. | Verified at `item_behavior.py:108,2542`. |

## Units

| Unit | Wave | Owns | Done when |
|---|---|---|---|
| U01 bench home | 1 | `benchmarks.md`, `scripts/bench_request.py` | Script reproduces warm `calculate_payload` ms and a 20-call loop on pinned scenarios; numbers at `7bb9701e` committed. |
| S1–S5 scouts | 1 | read-only | Inventories in scratchpad: packet-path call graph and enrichment diff (S1); interpreter/lane table (S2); `damage.py` literal-default classification (S3); bookkeeping-test census (S4); dead-code census per directory (S5). |
| U02 one packet path | 2 | `participant_timeline.py`, `program/` | `_pair_packet`/`add_packet` gone; receipt enrichment derived from compiled actions; equivalence tests now test one path against goldens. |
| U03 interpreter table | 2 | `interpreters/`, `item_behavior.py` lane/family tables | One table, lane set in one place; `reachability_report` output identical. |
| U04 damage.py rule 5 | 2 | `damage.py` | Every cached-data `.get(key, literal)` typed-or-deleted; count pinned by test. |
| U05 trigger bus + item_effects rule 5 | 2 | `trigger_stream.py`, `item_effects.py` | Name sets gone or derived from `CAPABILITIES`; raw `.get("kind")` only in `trigger_stream.py`; `_cached_sustain_stat` fails closed. |
| U06 MODULE_CC | 2 | `champions/`, `module_contract.py` | 177/177 declare; contract refuses parts-level stamps; Fimbulwinter coverage cells unchanged. |
| U07 test corpus | 3 | `tests/`, `docs/receipts/` | D6 applied; a pure-refactor probe (rename a private helper) turns nothing red. |
| U08 prose | 3 | all `src/` (prose only) | D7 applied; lint test pins both counts at zero. |
| U09 dead paths | 3 | per-directory slices from S5 | Every S5 row deleted or kept with a named live reader. |
| U10 latency | 4 | hot path per profile | `bench_request.py` re-captured; `benchmarks.md` explains every delta. |
| Close | 4 | — | Gate ladder fresh at merge head; blind `audit`; results table here; backlog/traps updated. |

## Gate ladder (run once, fresh, at close)

1. `pytest -n auto`
2. `black --check src/ tests/ scripts/`
3. `pylint src/`
4. `golden_snapshot.py compare` pair, coupled, exact — identical
5. `coverage_census.py check docs/coverage-census.json`
6. `plan_audit.py`
7. `scripts/bench_request.py` vs `benchmarks.md`
8. Blind `elegant-design:audit` over `main..engine-retirement`

## Success criteria

- `wc -l src` down by ≥5k with gate 4 identical.
- `grep -c "_pair_packet\|add_packet\b" src` = 0.
- `interpreters/` has no `*PairInterpreter`/`*WalkInterpreter` class pairs.
- Lint tests pin: cached-data literal fallbacks, campaign-ID citations in `src`, and docstrings longer than their body all at zero; receipt-reading test files ≤ the declared gates.
- `benchmarks.md` exists, with the start and close numbers from the same script.
