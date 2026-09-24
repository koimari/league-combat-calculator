# Local CI

The calculator's CI runs on this machine, job for job the same as
`.github/workflows/tests.yml`, so a change is proven before it is pushed and
the repo does not depend on GitHub Actions to know its own state. The
workflow stays in place for now because the repo is public and Vercel
deploys from `main` on green checks.

Each workflow job runs `bash ci/<job>.sh`, so a gate command has one home,
the script, and the workflow only provisions a runner: generating `ci/*.sh`
from the workflow would need a per-step override table for everything the
local runner does and hosted CI does not, and deleting them for `act` would
need Docker on every local run, including the pre-push loop.

```bash
make ci-fast      # pre-push loop: UI gates, black, golden compares, whitespace
make ci-full      # every job tests.yml runs, all failures reported
make hooks        # install the pre-push hook that runs ci-fast
```

Individual jobs: `ci-shared-ui`, `ci-test`, `ci-static`, `ci-coverage-census`,
`ci-property-sweep`, `ci-container`.

Every target exits non-zero on failure and prints a PASS/FAIL/SKIP summary.
A check that needs a tool you have not installed skips with the install
command rather than silently passing. `LCC_CI_STRICT=1` turns a skip into a
failure, which is what the workflow sets on every job: a hosted runner
installs everything, so a skip there is a gate that did not run. One check
is exempt, `trivy image`, because the workflow scans with the trivy action
instead; it prints `[by design]` and never fails. Python steps run the
checkout's own `.venv` (override with `LCC_CI_PYTHON`), a linked worktree
falling back to the main checkout's, never a bare `python3`.

Build artifacts (matrix receipts, scan reports) go to `build/ci/`, which is
gitignored. Nothing is written into the source tree.

## What maps to what

One script per job, and the flags live in the script.

| Workflow job | Script | Local target | Checks |
|---|---|---|---|
| `shared-ui` | `ci/shared_ui.sh` | `ci-shared-ui` | `npm ci` (skipped when `ui/node_modules` exists; `LCC_CI_NPM_CI=1` forces it), `npm run typecheck`, `npm test`, `node build.mjs --check` |
| `test` | `ci/test.sh` | `ci-test` | `pytest`, `golden_snapshot.py compare` (pair and coupled), `acceptance_matrix.py` and `champion_optimizer_matrix.py` into `build/ci/backend/`, `validate_receipt.py` over both |
| `static` | `ci/static.sh` | `ci-static` | `black`, `pylint`, `pip-audit` over both requirement files, `bandit` over `src/` |
| `coverage-census` (4 shards) | `ci/coverage_census.sh` | `ci-coverage-census` | `coverage_census.py check docs/coverage-census.json`; `LCC_CI_CENSUS_SHARD=K/4` runs one runner's cut |
| `property-sweep` (4 shards) | `ci/property_sweep.sh` | `ci-property-sweep` | `property_sweep.py`; `LCC_CI_SWEEP_SHARD=K/4` runs one runner's cut |
| `container` | `ci/container.sh` | `ci-container` | `docker build`, the smoke (health, non-root, one calculate, metrics module, HEALTHCHECK healthy), `trivy image` when installed, which on the workflow is its own action step |

`ci-fast` is not a workflow job. It is the subset that finishes in under a
minute, for the pre-push hook: the three UI gates, `black --check`, both golden
compares and `git diff --check`.

## Tools you need

- The repo `.venv` with `requirements.txt` installed (pytest, black, pylint,
  pip-audit and bandit come from it).
- Node at the version `engines.node` in `ui/package.json` states, with
  `ui/node_modules` installed (`npm ci` in `ui/`).
- Docker Desktop for `ci-container`; `brew install trivy` for the image scan.

## Timings on an M4 (2026-09-10)

| Target | About |
|---|---|
| `ci-fast` | 30 s |
| `ci-test` | 7 min (pytest) plus the matrices |
| `ci-static` | 5 min (pylint) |
| `ci-coverage-census` | 10 min for all shards |
| `ci-property-sweep` | 30 s for all shards on 12 cores |
| `ci-container` | 3 min after the first image build |
