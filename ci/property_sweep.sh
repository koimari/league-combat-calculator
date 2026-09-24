#!/usr/bin/env bash
# Local equivalent of tests.yml job: property-sweep
#   Hosted CI splits the champions over four runners with --shard K/4; one
#   machine runs them all. LCC_CI_SWEEP_SHARD=K/N runs one cut.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

ci_section "property-sweep: interpreter"
if ! ci_require_python; then
  ci_summary
fi

ci_section "property-sweep: every fight obeys the swept properties"
if [ -n "${LCC_CI_SWEEP_SHARD:-}" ]; then
  run_step "property_sweep --shard $LCC_CI_SWEEP_SHARD" "$CI_PY" scripts/property_sweep.py --shard "$LCC_CI_SWEEP_SHARD"
else
  run_step "property_sweep (all champions)" "$CI_PY" scripts/property_sweep.py
fi

ci_summary
