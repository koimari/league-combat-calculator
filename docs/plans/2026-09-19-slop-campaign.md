# Slop campaign

Source: `docs/audit/2026-09-19/issues.md` and the eleven per-dimension reports beside it. Goal:
land every finding the audit proposes, in the audit's phase order, with no behaviour change except
the correctness asides of its section 8. Ids below (`D1`, `2.4`, `W2`, `C1`, `P1`, `X6`, `A2`)
are the audit's own.

## Rules every unit follows

- One worker, one worktree, one branch `slop/<unit>`, one scope list. A worker edits nothing
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
  regenerates derived receipts in the CLAUDE.md order, runs `make ci-full`, and merges to `main`
  only on a green run. The campaign pushes nothing.

## Waves

| Wave | Audit phases | Units (branch) | Runs |
|---|---|---|---|
| A | 1, 2 | `data`: 1.1 tracked data, 1.4 guards, X5 machine-path lint, X6 one atomizer. `docs`: 1.2 finished docs, 6.2 merges, HANDOVER citations. `frontend`: D34 to D41, A4, A7, X7 escapers. `claude-md`: 6.4 split into `TRAPS.md` and `architecture.md`, HANDOVER section 11 lift, stale citations, word-budget test, pointer rule. | parallel, one integrator |
| B | 3 | `contract-tests`: 2.1, 2.2, 2.7 codemods. `dead-tests`: 2.3, 2.4, 2.5, 2.6 with A1 Akshan fixed first, 2.8, 2.9, A8, A12, A13. `relocate`: 2.10, 2.11, 2.12, X3 `ER5_TAIL` derivation. | parallel, one integrator |
| C | 4 | `dead-src`: D1 to D27, A3, A5, A6, A9, A10, A11. `wrappers`: D29 to D33, W2 to W12. | parallel, one integrator |
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
