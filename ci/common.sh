#!/usr/bin/env bash
# Shared helpers for the local CI runner (ci/*.sh).
#
# Every ci/*.sh script sources this file. It provides:
#   - repo_root plumbing and the build/ci artifact directory
#   - pass/fail/skip bookkeeping with a summary printed on exit
#   - require_* helpers that SKIP (do not fail) when an optional tool is
#     missing, printing the exact command that installs it
#   - the repo's own Python: .venv/bin/python, never a bare python3
#
# Exit code contract: a script that sources this file and calls
# `ci_summary` at the end exits 1 if any check failed, 0 if every check
# passed or was skipped.

set -o pipefail

CI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CI_ROOT

# Build artifacts (matrix receipts, scan reports) never belong in the tree.
: "${CI_ARTIFACTS:=$CI_ROOT/build/ci}"
export CI_ARTIFACTS
mkdir -p "$CI_ARTIFACTS"

CI_PASS_COUNT=0
CI_FAIL_COUNT=0
CI_SKIP_COUNT=0
CI_FAILED_NAMES=()
CI_SKIPPED_NAMES=()

_ci_color() {
  if [ -t 1 ]; then
    printf '\033[%sm%s\033[0m' "$1" "$2"
  else
    printf '%s' "$2"
  fi
}

ci_section() {
  echo ""
  echo "== $* =="
}

ci_pass() {
  CI_PASS_COUNT=$((CI_PASS_COUNT + 1))
  echo "$(_ci_color 32 PASS) - $*"
}

ci_fail() {
  CI_FAIL_COUNT=$((CI_FAIL_COUNT + 1))
  CI_FAILED_NAMES+=("$*")
  echo "$(_ci_color 31 FAIL) - $*"
}

ci_skip() {
  CI_SKIP_COUNT=$((CI_SKIP_COUNT + 1))
  CI_SKIPPED_NAMES+=("$*")
  echo "$(_ci_color 33 SKIP) - $*"
}

# run_step <label> <command...>: records PASS/FAIL by exit code, never stops
# the script, so one job reports every failure the way hosted CI did.
run_step() {
  local label="$1"
  shift
  echo ""
  echo "--- $label ---"
  if "$@"; then
    ci_pass "$label"
    return 0
  else
    local status=$?
    ci_fail "$label (exit $status)"
    return "$status"
  fi
}

# require_tool <binary> <install-hint>: 0 if on PATH, else records a SKIP.
require_tool() {
  local tool="$1"
  local hint="$2"
  if command -v "$tool" >/dev/null 2>&1; then
    return 0
  fi
  ci_skip "$tool not installed: install with: $hint"
  return 1
}

# The repo's pinned interpreter. LCC_CI_PYTHON overrides it; the default is
# the checkout's own .venv, which every gate in CLAUDE.md already assumes.
ci_require_python() {
  local candidate
  local main_root
  # A linked worktree (.claude/worktrees/<name>) has no venv of its own;
  # the main checkout's .venv serves every worktree of the same repo.
  main_root="$(cd "$(git -C "$CI_ROOT" rev-parse --git-common-dir)/.." 2>/dev/null && pwd)"
  for candidate in "${LCC_CI_PYTHON:-}" "$CI_ROOT/.venv/bin/python" "${main_root:+$main_root/.venv/bin/python}"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      CI_PY="$candidate"
      export CI_PY
      return 0
    fi
  done
  ci_skip "Python venv not found at $CI_ROOT/.venv: create it with: uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements.txt"
  return 1
}

# ci_python_tool <name>: the venv's copy of a console tool (pytest, black,
# pylint, pip-audit, bandit) so the versions requirements.txt pins are the
# ones that run.
ci_python_tool() {
  local tool="$1"
  local venv_dir
  venv_dir="$(dirname "$(dirname "$CI_PY")")"
  if [ -x "$venv_dir/bin/$tool" ]; then
    printf '%s' "$venv_dir/bin/$tool"
    return 0
  fi
  return 1
}

ci_summary() {
  echo ""
  echo "================ CI SUMMARY ================"
  echo "pass: $CI_PASS_COUNT   fail: $CI_FAIL_COUNT   skip: $CI_SKIP_COUNT"
  if [ "$CI_FAIL_COUNT" -gt 0 ]; then
    echo "failed checks:"
    for name in "${CI_FAILED_NAMES[@]}"; do
      echo "  - $name"
    done
  fi
  if [ "$CI_SKIP_COUNT" -gt 0 ]; then
    echo "skipped checks:"
    for name in "${CI_SKIPPED_NAMES[@]}"; do
      echo "  - $name"
    done
  fi
  echo "=============================================="
  if [ "$CI_FAIL_COUNT" -gt 0 ]; then
    exit 1
  fi
  exit 0
}
