# Issue closeout campaign (2026-09-02)

Two serial waves of five Opus workers, one worktree each forked from `main`
(442b0cf9). Each wave merges into one campaign branch, the regenerator ladder
runs once on the merged tree, one PR per wave, CI green, merge, close issues
per `docs/issue-closure-policy.md`.

## Waves

| Wave | Branch | Issues |
|---|---|---|
| 1 | `campaign/issue-closeout-w1` | #232 ControlScope one-target casts, #233 Immortal Path Slay declaration, #234 QSS under stasis, #236 per-clause restricted-channel adjudication, #263 xdist contamination |
| 2 | `campaign/issue-closeout-w2` | #230 Manaflow for all five holders + Mercurial accessor, #229 Vi Blast Shield walk-side rebind, #228 MODULE_CC slot completeness + Fimbulwinter proc certification, #226 participant[2] support staging, #216 reviewed-packets gate sqlite |

Wave 1 holds the one-seam fixes. Wave 2 holds the engine-shaped ones (walk,
staging, packet gate) that need the most review.

## Decisions

- #234: wire stasis into the cleanse kernel's active controls. The module's
  own atom says the cast is blocked and the use kept, so the walk's narrower
  view is a modelling artifact, not a documented boundary.
- #236: implement branch-level attribution now rather than wait for a third
  holder. The per-item admission is a latent wrong number.
- #216: the sqlite is a sibling-repo asset. Build the `pages` table the gate
  reads (title, revision_id, revision_timestamp, namespace) from the wiki
  API through the `decompose_wiki.py` fetch layer. The file stays gitignored
  and the builder is the reviewable artifact.
- Workers recapture goldens on their own branch with every diff explained in
  the commit. The orchestrator re-runs the whole regenerator ladder
  (`CLAUDE.md`, Known Quirks, "Regenerators after a merge") on the merged
  tree and takes either side on derived-receipt conflicts.
- Workers never regenerate `docs/coverage-census.json`. They report whether
  `coverage_census.py check` moved.

## Worker contract

One brief per worker under the session scratchpad (`briefs/<issue>.md`).
Report `PASS`, `ISSUES` or `BLOCKED` with branch, commit SHA, files touched,
gate outputs (pytest -n auto, black --check, pylint src/, golden compare,
literal defaults, prose lint, census check), and the tests that pin the fix.

## Gate ladder (once, on each merged campaign branch)

1. Regenerator ladder in the documented order.
2. `pytest -n auto`, `black --check`, `pylint src/`, golden compare on both
   pinned targets, `literal_defaults.py`, `prose_lint.py`.
3. `coverage_census.py run --output` then `check`.
4. Push, PR, CI green (test, static, coverage-census x4, container).
5. Merge. Close each issue with the merge SHA and the pinning tests.

## Success criteria

- Two PRs merged to `main`, CI green on each merge commit.
- All ten issues closed, each closure comment commit-addressed.
- Decision log (`decisions.tsv`, session scratchpad) walks against the
  commits and PRs.
