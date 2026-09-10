#!/usr/bin/env bash
# Local equivalent of tests.yml job: test
#   pytest -n auto, the golden snapshot gates, the backend acceptance
#   matrices and the receipt schema check over their artifacts.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

ci_section "test: interpreter"
if ! ci_require_python; then
  ci_summary
fi
PYTEST="$(ci_python_tool pytest)" || { ci_fail "pytest missing from the venv (pip install -r requirements.txt)"; ci_summary; }

ci_section "test: pytest -n auto"
run_step "pytest -n auto" "$PYTEST" -n auto -q -p no:cacheprovider

ci_section "test: numeric golden snapshots"
run_step "golden_snapshot compare (pair)" "$CI_PY" scripts/golden_snapshot.py compare scripts/golden_baseline.json
# The coupled baseline is pinned by tests/test_golden_snapshot.py; the
# compare here is the same instrument run standalone so a diff prints.
run_step "golden_snapshot compare (coupled)" "$CI_PY" scripts/golden_snapshot.py compare scripts/golden_coupled_baseline.json

ci_section "test: backend acceptance matrices"
BACKEND="$CI_ARTIFACTS/backend"
mkdir -p "$BACKEND"
run_step "acceptance_matrix --json" bash -c "\"$CI_PY\" scripts/acceptance_matrix.py --json > \"$BACKEND/acceptance_matrix.json\""
acceptance_status=$?
run_step "champion_optimizer_matrix --json" bash -c "\"$CI_PY\" scripts/champion_optimizer_matrix.py --json > \"$BACKEND/champion_optimizer_matrix.json\""
champion_status=$?
printf '{"acceptance_matrix":%s,"champion_optimizer_matrix":%s}\n' \
  "$acceptance_status" "$champion_status" > "$BACKEND/status.json"

ci_section "test: gate receipt schema"
# Runs even when a matrix gate is red: that is exactly when consumers need
# trustworthy artifacts (issue #139). Skipped only when nothing was written.
if [ -s "$BACKEND/acceptance_matrix.json" ] && [ -s "$BACKEND/champion_optimizer_matrix.json" ]; then
  run_step "validate_receipt" "$CI_PY" scripts/validate_receipt.py "$BACKEND/acceptance_matrix.json" "$BACKEND/champion_optimizer_matrix.json"
else
  ci_skip "validate_receipt (a matrix never wrote its receipt; see the failures above)"
fi
echo "backend acceptance evidence: $BACKEND/"

ci_summary
