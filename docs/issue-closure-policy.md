# Issue-closure policy (issue #77)

Every GitHub issue closure claim on Scryglass must be **commit-addressed and gated**:

1. **Commit-addressed** — the closing comment cites the exact merge commit SHA, confirmed merged with `git branch -r --contains <sha>` (never a dirty working tree).
2. **Gate-checked** — the gates in `CLAUDE.md` § *Commands and gates* are green on that commit with a clean tree.
3. **Deployment-gated** — when the fix is user-visible, the deployed SHA contains the commit (`git merge-base --is-ancestor <sha> <deployed-sha>`), so nothing is closed while production serves an older engine.
4. **Evidence** — the closing comment names the issue, the commit SHA, the tests that pin the fix, and (for modeling issues) the golden/corpus status.
