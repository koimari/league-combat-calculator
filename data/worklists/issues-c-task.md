You are resolving GitHub issue #82 on the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-issues-c (branch codex/issues-c-quests). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOU OWN: src/calculator/loadout_rules.py, src/calculator/role_quests.py, src/app.py (quest/boot routes only), static/js/app.js (quest/boot/copy/rerender UI paths ONLY — do not restructure unrelated UI), templates/index.html (quest/boot controls only), tests/test_issues_82.py (new), scripts/golden_baseline.json (re-capture + explain if needed).

#82 — certify role-quest boot upgrades and support-item progression across ALL effects. Acceptance pass over the issue's criteria:
1. Mid role quest completes -> selected tier-2 boot is replaced by its sourced tier-3 pair and REMAINS present through role, level, quest, copy, and rerender operations (normalizeRosterBootForRole + roleQuestBootUpgradeName exist — verify each transition with tests: role change, level change, quest toggle, copy A->B, rerender).
2. The upgraded boot's typed stats affect the calculation (test: mid + quest complete + tier-3 boot changes TDD/eHP vs tier-2).
3. Support-item progression: basic/upgraded stages legal per quest state across API, frontend, optimizer, and the coupled timeline (role_quest_complete flag; BIS sweep: the 5 support upgrades certify with quest complete). Verify + fix gaps.
4. Test the full UI flow in a headless browser if feasible (the repo has Playwright-core setup under /tmp/pw-qa from earlier QA; the P5 UX already verified quick mode) — at minimum assert the API contract transitions.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js; golden compare (explain diffs); git diff --check.
COMMIT "fix(#82): role-quest boot upgrade + support-item progression acceptance" and PUSH origin/codex/issues-c-quests. Do NOT merge.
Reply to parent: per acceptance criterion — verified/fixed + test evidence, commit SHA.