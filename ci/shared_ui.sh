#!/usr/bin/env bash
# Local equivalent of tests.yml job: shared-ui (ui/)
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

cd ui || { echo "missing ui/"; exit 1; }

ci_section "shared-ui: install dependencies (npm ci)"
if [ "${LCC_CI_NPM_CI:-0}" != "1" ] && [ -d node_modules ]; then
  ci_skip "npm ci (node_modules present; set LCC_CI_NPM_CI=1 to reinstall from the lockfile)"
else
  run_step "npm ci" npm ci
fi

ci_section "shared-ui: type check"
run_step "npm run typecheck" npm run typecheck

ci_section "shared-ui: unit tests"
run_step "npm test" npm test

ci_section "shared-ui: committed bundle matches source"
run_step "node build.mjs --check" node build.mjs --check

ci_summary
