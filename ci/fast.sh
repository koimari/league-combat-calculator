#!/usr/bin/env bash
# ci-fast: the pre-push loop. The shared UI gates, formatting, the two
# golden compares and the whitespace check: everything that finishes in
# under a minute. The full pytest suite, pylint, the census and the
# container belong to ci-full.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

ci_section "fast: shared UI"
run_step "npm run typecheck" bash -c "cd ui && npm run typecheck"
run_step "npm test" bash -c "cd ui && npm test"
run_step "node build.mjs --check" bash -c "cd ui && node build.mjs --check"

ci_section "fast: whitespace"
run_step "git diff --check" git diff --check HEAD --

ci_section "fast: Python"
if ci_require_python; then
  if BLACK="$(ci_python_tool black)"; then
    run_step "black --check src/ tests/ scripts/" "$BLACK" --check src/ tests/ scripts/
  else
    ci_fail "black missing from the venv (pip install -r requirements.txt)"
  fi
  run_step "golden_snapshot compare (pair)" "$CI_PY" scripts/golden_snapshot.py compare scripts/golden_baseline.json
  run_step "golden_snapshot compare (coupled)" "$CI_PY" scripts/golden_snapshot.py compare scripts/golden_coupled_baseline.json
fi

ci_summary
