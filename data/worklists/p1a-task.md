You are building BETA ONBOARDING (P1a) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p1a (branch codex/p1a-onboarding). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: F0 just redesigned the frontend (quick mode = landing, analyst = single surface, trust chips visible). P0a added invite-gated auth + beta landing. The closed beta needs a 5-minute onboarding so invited users get value fast.

YOU OWN: static/js/app.js (onboarding overlay paths ONLY — it was just redesigned; make additive, minimal, no restructure), templates/index.html, docs/onboarding-guide.md (new), docs/invite-flow.md (new), tests/test_p1a_onboarding.py (new).

DELIVERABLES:
1. FIRST-RUN OVERLAY: a dismissible 3-step guided overlay shown on first login (localStorage flag `scryglass_onboarded`): (1) "Pick your champion + role", (2) "Press Best next item — top 3 with why", (3) "Dig deeper in Analyst — every number carries an exact/estimate/boundary chip". Non-blocking (Skip button), respects prefers-reduced-motion, works on mobile.
2. INVITE ONBOARDING FLOW doc (docs/invite-flow.md): how an invite is issued (SCRYGLASS_INVITE_CODES batch), what the invitee sees (beta landing → code+password → first-run overlay), invite rotation.
3. 5-MINUTE GUIDE (docs/onboarding-guide.md): quick mode 3-click path, reading top-3 cards (delta + why), certainty chips legend, STALE badge meaning, share links, feedback widget ("did this match?"), what to do on patch day.
4. tests: first-run overlay renders on fresh session, dismisses + persists flag, skip works, mobile viewport ok; guide/invite docs exist with required sections.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; node --check static/js/app.js; git diff --check; golden identical (UI-only).
COMMIT "feat(P1a): first-run onboarding overlay + invite flow + 5-minute guide" and PUSH origin/codex/p1a-onboarding. Do NOT merge.
Reply to parent: overlay design, guide outline, invite flow, tests, gates, commit SHA.