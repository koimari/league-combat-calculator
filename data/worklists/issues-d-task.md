You are resolving GitHub issue #78 on the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-issues-d (branch codex/issues-d-capabilities). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

YOU OWN: src/calculator/capabilities.py, tests/test_issues_78.py (new). You may READ src/app.py, static/js/app.js, templates/index.html but DO NOT edit them (another agent owns the quest/boot UI paths; if you find drift that needs an app.py/app.js fix, report it precisely in your reply and I will apply it after the quest agent merges).

#78 — make ONE backend capability contract authoritative for every frontend control:
1. capabilities.py's public_capability_contract (schema v1) is the single source of truth — audit it: every control family the frontend renders (champion picker, role, level, quest toggle, boots toggle, item slots, keystone, ability ranks/options, fight window, roster enemies/allies, BIS, quick mode, share) must be declared in the contract with a stable frontend_token.
2. Add a static contract-coverage test (tests/test_issues_78.py) that: (a) scans static/js/app.js + templates/index.html for every control id/data-path/data-picker/capability attribute and asserts each maps to a declared capability token; (b) asserts every declared capability token is referenced by the frontend; (c) asserts the API responses that feed controls (e.g. /api/config, /api/abilities, champion_options_meta, item_input_options_meta) expose exactly the capability-declared fields.
3. Fix any drift INSIDE capabilities.py only (add missing declarations). Report app.py/app.js drift to me.
4. Tests must pass against the current frontend.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden compare (identical expected — no engine change).
COMMIT "fix(#78): authoritative capability contract + coverage test" and PUSH origin/codex/issues-d-capabilities. Do NOT merge.
Reply to parent: contract audit findings, the coverage test design, drift found (in capabilities.py vs app.py/app.js), commit SHA.