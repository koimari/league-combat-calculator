# Issue-closure policy (issue #77)

Every GitHub issue closure claim on Scryglass must be **commit-addressed and gated**:

1. **Commit-addressed** — the closing comment cites the exact merge commit SHA on `codex/deep-audit-2026-08` (never a dirty working tree).
2. **Gate-checked** — run `python scripts/issue_gate.py check --issue <n> --commit <sha> [--deploy-sha <sha>]` before closing. The gate verifies:
   - the commit is an ancestor of `origin/codex/deep-audit-2026-08` (merged),
   - the working tree is clean,
   - the full gates are green (pytest, golden compare, pylint >= 9),
   - optionally, the commit is an ancestor of a provided deployed SHA.
3. **Deployment-gated (full)** — the `--deploy-sha` hook is wired for explicit deployment SHAs today; when P10 (public auth/deployment) lands, the hook compares against the live Vercel deployment's commit so a "fixed" issue cannot be closed while production serves an older engine.
4. **Evidence** — the closing comment names the issue, the commit SHA, the tests that pin the fix, and (for modeling issues) the golden/corpus status.
