# Local CI

The calculator's CI runs on this machine, job for job the same as
`.github/workflows/tests.yml`, so a change is proven before it is pushed and
the repo does not depend on GitHub Actions to know its own state. The
workflow stays in place for now because the repo is public and Vercel
deploys from `main` on green checks; both runners read the same commands.

```bash
make ci-fast      # pre-push loop: UI gates, black, golden compares, whitespace
make ci-full      # every job tests.yml runs, all failures reported
make hooks        # install the pre-push hook that runs ci-fast
```

Individual jobs: `ci-shared-ui`, `ci-test`, `ci-static`, `ci-coverage-census`,
`ci-container`.

Every target exits non-zero on failure and prints a PASS/FAIL/SKIP summary.
A check that needs a tool you have not installed skips with the install
command rather than silently passing. Python steps run the checkout's own
`.venv` (override with `LCC_CI_PYTHON`), never a bare `python3`.

Build artifacts (matrix receipts, scan reports) go to `build/ci/`, which is
gitignored. Nothing is written into the source tree.

## What maps to what

| Workflow job → step | Local target | Checks |
|---|---|---|
| `shared-ui` | `ci-shared-ui` | `npm ci` (skipped when `ui/node_modules` exists; `LCC_CI_NPM_CI=1` forces it), `npm run typecheck`, `npm test`, `node build.mjs --check` |
| `test` | `ci-test` | `pytest -n auto`, `golden_snapshot.py compare` (pair and coupled), `acceptance_matrix.py --json` and `champion_optimizer_matrix.py --json` into `build/ci/backend/`, `validate_receipt.py` over both |
| `static` | `ci-static` | `black --check`, `pylint src/ --fail-under=9 --fail-on=E0601,E0602`, `pip-audit` over both requirement files, `bandit -r src -ll` |
| `coverage-census` (4 shards) | `ci-coverage-census` | `coverage_census.py check docs/coverage-census.json`; `LCC_CI_CENSUS_SHARD=K/4` runs one runner's cut |
| `container` | `ci-container` | `docker build`, the same smoke (health, non-root, one calculate, metrics module, HEALTHCHECK healthy), `trivy image` when installed |

`ci-fast` is not a workflow job. It is the subset that finishes in under a
minute, for the pre-push hook: the three UI gates, `black --check`, both golden
compares and `git diff --check`.

## Tools you need

- The repo `.venv` with `requirements.txt` installed (pytest, black, pylint,
  pip-audit and bandit come from it).
- Node 24 or newer with `ui/node_modules` installed (`npm ci` in `ui/`).
- Docker Desktop for `ci-container`; `brew install trivy` for the image scan.

## Timings on an M4 (2026-09-10)

| Target | About |
|---|---|
| `ci-fast` | 30 s |
| `ci-test` | 7 min (pytest) plus the matrices |
| `ci-static` | 5 min (pylint) |
| `ci-coverage-census` | 10 min for all shards |
| `ci-container` | 3 min after the first image build |
