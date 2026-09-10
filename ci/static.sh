#!/usr/bin/env bash
# Local equivalent of tests.yml job: static
#   black, pylint (score floor plus the undefined-name family), pip-audit
#   over both requirement files, bandit over src/.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=ci/common.sh
source ci/common.sh

ci_section "static: interpreter"
if ! ci_require_python; then
  ci_summary
fi

ci_section "static: formatting"
if BLACK="$(ci_python_tool black)"; then
  run_step "black --check src/ tests/ scripts/" "$BLACK" --check src/ tests/ scripts/
else
  ci_fail "black missing from the venv (pip install -r requirements.txt)"
fi

ci_section "static: linter"
# An undefined name fails the gate whatever the score: at 9.70 one passed
# in damage.py and sat as a latent NameError.
if PYLINT="$(ci_python_tool pylint)"; then
  run_step "pylint src/ --fail-under=9 --fail-on=E0601,E0602" "$PYLINT" src/ --jobs=0 --fail-under=9 --fail-on=E0601,E0602
else
  ci_fail "pylint missing from the venv (pip install -r requirements.txt)"
fi

ci_section "static: dependency audit"
if PIP_AUDIT="$(ci_python_tool pip-audit)"; then
  run_step "pip-audit -r requirements.txt" "$PIP_AUDIT" -r requirements.txt
  run_step "pip-audit -r requirements-runtime.txt" "$PIP_AUDIT" -r requirements-runtime.txt
else
  ci_skip "pip-audit not in the venv: install with: .venv/bin/pip install pip-audit"
fi

ci_section "static: source scan"
if BANDIT="$(ci_python_tool bandit)"; then
  run_step "bandit -r src -ll" "$BANDIT" -r src -ll
else
  ci_skip "bandit not in the venv: install with: .venv/bin/pip install bandit"
fi

ci_summary
