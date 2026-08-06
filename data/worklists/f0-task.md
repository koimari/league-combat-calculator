You are performing a GROUND-UP FRONTEND REVIEW of a League of Legends combat calculator (Scryglass) — F0 of the closed-beta goal.

YOUR WORKTREE: /Users/river/Projects/lcc-f0-frontend (branch codex/f0-frontend). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

THE PRODUCT (all real, all live):
- Backend: Flask API (/api/calculate, /api/bis, /api/optimize, /api/certainty, /api/not-modeled, /api/staleness, /api/builds, /api/share, /api/feedback, /api/receipts, /api/config capability contract).
- Data: 173 champion modules with per-champion OPTIONS (stacks/procs/uptime toggles), item effects with typed receipts, per-ability certainty (exact/estimate/boundary), staleness (patch drift), validation feedback.
- UI (static/js/app.js ~270k chars + templates/index.html + static/css): an analyst-grade builder (champion/role/level/quest/boots/items A+B/keystone/abilities options/roster enemies+allies/fight window) + the newer P5 'Quick 3 clicks' flow (champion->role->enemy->items->Best next item -> top-3 cards) + build sharing (?share= token) + presets + certainty chips + staleness badges + a validation feedback widget (static/js/feedback.js).

YOUR JOB — three deliverables:
1. **Findings doc (docs/frontend-review-findings.md)**: a ground-up audit covering (a) BUGS and inconsistencies you find by actually running the app (start the server: .venv/bin/python -m flask --app src.app run --port 5000; use the Playwright setup at /tmp/pw-qa with chromium at /Users/river/Library/Caches/ms-playwright/chromium-1129/chrome-mac/Chromium.app/Contents/MacOS/Chromium) across desktop + mobile viewport; (b) DEAD CODE / duplication (e.g. the legacy renderBuilder mentioned by the #78 agent, duplicate template ids); (c) UX friction and information architecture issues (is the analyst/quick split right? does the data surface clearly? certainty chips/staleness discoverable?); (d) accessibility + mobile; (e) performance (bundle size, render churn, BIS latency feedback).
2. **Recommended design (docs/frontend-design.md)**: the best possible frontend design to fit and leverage the data — proposed information architecture, visual hierarchy, component model, quick-vs-analyst relationship, how certainty/staleness/feedback should surface, mobile strategy. Concrete enough to implement.
3. **Implementation**: implement the agreed design on this branch (you own static/js/app.js, static/css/, templates/index.html, static/js/feedback.js if needed) with tests (tests/test_f0_frontend.py) + full gates. Keep the backend API contract unchanged (you may add frontend-only features; any needed API addition must be reported for me to apply after this branch).

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js; git diff --check; golden compare identical (UI-only).
COMMIT "feat(F0): ground-up frontend review + redesign implementation" and PUSH origin/codex/f0-frontend. Do NOT merge.
Reply to parent: findings summary (bugs found + fixed), the design recommendations, what was implemented, tests, gates, commit SHA.