#!/usr/bin/env bash
# Local equivalent of tests.yml job: coverage-census
#   Hosted CI splits the ~180k-cell census over four runners with
#   --shard K/4; one machine runs the whole receipt (about ten minutes on
#   an M4). LCC_CI_CENSUS_SHARD=K/N runs one cut, the way a runner did.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

ci_section "coverage-census: interpreter"
if ! ci_require_python; then
  ci_summary
fi

ci_section "coverage-census: the committed receipt reproduces"
if [ -n "${LCC_CI_CENSUS_SHARD:-}" ]; then
  run_step "coverage_census check --shard $LCC_CI_CENSUS_SHARD" "$CI_PY" scripts/coverage_census.py check docs/coverage-census.json --shard "$LCC_CI_CENSUS_SHARD"
else
  run_step "coverage_census check (all shards)" "$CI_PY" scripts/coverage_census.py check docs/coverage-census.json
fi

ci_summary
