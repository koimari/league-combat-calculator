# Slop campaign

Source: `docs/audit/2026-09-19/issues.md` and the eleven per-dimension reports beside it. Goal:
land every finding the audit proposes, in the audit's phase order, with no behaviour change except
the correctness asides of its section 8. Ids below (`D1`, `2.4`, `W2`, `C1`, `P1`, `X6`, `A2`)
are the audit's own.

## Rules every unit follows

- One worker, one worktree, one branch `slop-<wave>/<unit>`, one scope list. A worker edits nothing
  outside its scope. Traps it learns go in its report, not `TRAPS.md`. The integrator appends them.
- Gates per unit, fresh output quoted in the report: `black --check src/ tests/ scripts/`,
  `pylint src/ --jobs=4 --fail-under=9 --fail-on=E0601,E0602` for code changes, both golden
  compares (`scripts/golden_baseline.json`, `scripts/golden_coupled_baseline.json`),
  `python scripts/prose_lint.py`, `python scripts/literal_defaults.py`, `pytest <the test files
  the unit touched or that read what it changed>` without `-n`, plus the owning gate of anything
  touched (`coverage_status.py --check`, `swing_stream_audit.py`, `build_icon_sprite.py --check`,
  `certify_damage_casts.py --check`, `node build.mjs --check` under `ui/`).
- The full suite (`pytest -n auto`, `coverage_census.py check`, `make ci-full`) runs once per
  wave, by the integrator, on the merged tree. Four concurrent full runs took the machine out of
  memory; a worker or skeptic never runs the whole suite, never passes `-n`, and never runs more
  than one pytest at a time.
- A pure refactor or deletion prints `OK: snapshot identical` on both golden compares. A unit that
  moves a golden stops and reports the diff instead of re-capturing.
- Codemods land one at a time with a green golden between each, never batched.
- The worker re-greps every "nothing reads it" claim before the delete, over `src/`, `tests/`,
  `scripts/`, `ui/`, `static/`, `templates/`, `docs/`, `ci/`, `.github/` and `.claude/skills/`.
  Three of the audit's claims already failed re-verification.
- A skeptic reviews every branch before integration, prompted to refute it: a deleted reader, a
  gate not run, a scope breach, a silent behaviour change.
- The integrator merges units onto `campaign/slop-<wave>`, resolves conflicts by intent,
  regenerates derived receipts in the CLAUDE.md order, runs every CI gate one process at a time
  with `pytest -n 8`, and hands the branch to the session, which merges to `main` only on a green
  run it reproduces. The campaign pushes nothing.

## Waves

| Wave | Audit phases | Units (branch) | Runs |
|---|---|---|---|
| A | 1, 2 | `data`: 1.1 tracked data, 1.4 guards, X5 machine-path lint, X6 one atomizer. `docs`: 1.2 finished docs, 6.2 merges, HANDOVER citations. `frontend`: D34 to D41, A4, A7, X7 escapers. `claude-md`: 6.4 split into `TRAPS.md` and `architecture.md`, HANDOVER section 11 lift, stale citations, word-budget test, pointer rule. | parallel, one integrator |
| B | 3 | `contract-tests`: 2.1, 2.2, 2.7 codemods. `dead-tests`: 2.3, 2.4, 2.5, 2.6 with A1 Akshan fixed first, 2.8, 2.9, A8, A12, A13. `relocate`: 2.10, 2.11, 2.12, X3 `ER5_TAIL` derivation. | parallel, one integrator |
| C | 4 | `dead-src`: D1 to D27, A3, A5, A6, A9, A10, A11, pylint `--fail-on` widened. `wrappers`: D29 to D33, W2 to W12, branched from the verified `dead-src` because both edit the interpreters and the catalog. | chained, one integrator |
| D | 5 | one unit per codemod in the audit's order: C1, A2 then C4 `CachedSentence`, C5, C4 rest, C7, C8, C6, C9 to C11, C2, C3 | sequential, goldens between |
| E | 6 | P1 module by module, P3, P4 and P5, P6 and X1, P8 P10 P12 P13 X2, then P2 behind a `benchmarks.md` row | sequential |

Wave A units conflict only on `architecture.md` (`docs` retires HANDOVER, `claude-md` receives its
section 11) and on the docstrings that cite HANDOVER. The integrator resolves those by intent.
`docs` deletes a finished doc only after every citation of it is repointed.

## Success criteria

| Wave | Gate |
|---|---|
| every wave | `make ci-full` green on the merged tree, both golden compares identical, `pytest -n auto` count reported before and after |
| A | `git ls-files` down by about 1,500 entries, tracked data down by about 17 MB, `CLAUDE.md` under about 1,600 words with `TRAPS.md` and `architecture.md` holding the moved entries, a test fails when a tracked receipt has no reader and when a tracked JSON holds a machine path |
| B | `tests/` down by about 13,000 lines, the three contract tests parametrized in `test_module_cc_census.py`, zero `.clear()` on a process-wide cache in `tests/`, zero campaign-named test files |
| C | `src/` down by about 2,100 lines plus the wrappers, `import src.calculator.quantity` under 100 ms, pylint `--fail-on` widened to `E0102` |
| D | each codemod's commit shows identical goldens, `derive_self_healing` takes one `SelfHealCtx`, the seven silent prose readers raise on a miss |
| E | `scripts/literal_defaults.py` reports zero engine-row sites, `test_literal_defaults.py` deleted, one `InterpretationError`, `SurvivalAction` split with its bench row |

## Results

| Wave | Merged at | Lines removed | Files removed | Notes |
|---|---|---|---|---|
| A | `7ad31845` | 603,956 against 2,315 added | 720 tracked, 14.9 MB | All four units merged. Full suite 16,363 passed, 47 skipped, against 16,433 collected on main and 16,410 here. Both goldens identical. `CLAUDE.md` 1,290 words, `TRAPS.md` 5,367, `architecture.md` 6,971. Two conflicts, both resolved by intent: the `item_support_effects` assignment record takes the compacted shape with the corrected import count, and the SD2 receipt stays deleted. Three fixes the integrator owns: the orphan guard names no tracked family in its own fixture, `ui/build.mjs` compares newlines-normalised so the check passes on a CRLF checkout and its bundle loop runs at all, and the retired source-admission review's Camille and Yasuo defects became backlog rows SA2 and SA3. `docs/cast-dependency-audit.json` was already stale on main and is regenerated here. |
| B | `02f966f7` | 18,326 against 6,500 added; `tests/` 274,933 to 261,172 | 11 tracked, 71 renamed | All three units merged. Full suite 16,552 passed, 32 skipped, against 16,410 collected on main and 16,584 here, the rise being the census parametrization. Both goldens identical against dead-tests' Akshan re-capture, whose only non-Akshan leaves against main are `git_head` and `src_tree_sha`. Criteria: the three contract tests are parametrized rows in `test_module_cc_census.py` over 173 champions with a nine-champion `UNREVIEWED` pin, no `.clear()` in `tests/` touches a process-wide cache (three remain, each on a test-local object), zero campaign-named test files, and the Akshan probe numbers are in `d80edacb`. Twenty-six conflicts in six shapes, each resolved by intent: a deletion beats a citation repoint into it (18 files), the file relocate renamed and dead-tests deleted stays deleted, the two script extractions keep their script-backed tests while the reason tautologies go, both sides' import drops land, the `needs_node` marker survives its neighbour's deletion, and the Olaf docstring is the union of two rewrites with its section range corrected to S11. Four fixes the integrator owns: the `needs_node` marker the deletion took with it, the Gnar grep pin losing `test_jayce_form_transition.py`, `receipt_walk_schedule.deferral_rows` reading an absent deferral block as a paid debt after 2.8 retired the machinery, and `TRAPS.md`'s word budget at 6,900, measured from a wave. Two citations the merge itself broke, both repointed. `repin_corpus` and `capture_coverage_classification` reverted as stamp-only. `CLAUDE.md` 1,299 words, `TRAPS.md` 6,134, `architecture.md` 6,971. Every gate ran at `02f966f7`, and this row is the only commit above it on `campaign/slop-b`. |
