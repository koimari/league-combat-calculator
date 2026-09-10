#!/usr/bin/env bash
# Install local git hooks. Hooks live outside version control, so they do
# not follow a clone: rerun this after cloning or if .git is recreated.
# In a linked worktree the hooks directory is the main checkout's.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

hooks_dir="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks_dir"
hook="$hooks_dir/pre-push"

cat > "$hook" <<'HOOK'
#!/bin/sh
# The local stand-in for the required status check. Bypass with --no-verify.
echo "pre-push: running make ci-fast"
make ci-fast
HOOK

chmod +x "$hook"
echo "installed $hook"
