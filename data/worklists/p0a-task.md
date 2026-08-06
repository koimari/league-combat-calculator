You are preparing the CLOSED-BETA DEPLOYMENT (P0a) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p0a (branch codex/p0a-deploy). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CURRENT STATE: Flask app in src/app.py with password auth (SCRYGLASS_AUTH_REQUIRED/SCRYGLASS_AUTH_SECRET/SCRYGLASS_AUTH_USERS env vars), vercel.json is empty {}, PostgreSQL layer src/db.py (DATABASE_URL; SQLite fallback for dev), docker-compose.yml with postgres, P5 quick mode + share links, P7 feedback.

DELIVERABLES:
1. **Invite-gated beta access**: keep the existing SCRYGLASS_AUTH gate; add an invite-code layer (SCRYGLASS_INVITE_CODES env, comma-separated) — the beta landing page asks for an invite code + the research-account password; a successful login sets the session with the invite source recorded. Add a simple /api/auth/invite endpoint (validate code) + frontend touch only if trivial (report app.js needs otherwise).
2. **Beta landing page**: a proper landing (what it is, how to use in 3 steps, Riot disclaimer, privacy link, 'Enter with invite code' form) — replace the bare "Private calculator" auth page; keep the gate.
3. **Managed DB wiring**: document + wire managed Postgres + Redis: DATABASE_URL, REDIS_URL env handling; result-cache should use Redis when REDIS_URL is set (extend src/db.py cache to a Redis backend with the same interface, SQLite fallback), .env.example with every SCRYGLASS_*/DATABASE_URL/REDIS_URL var documented.
4. **Deploy runbook**: docs/deploy-runbook.md — Vercel deployment steps (env vars, build command, removal of deployment-protection in favor of the app gate), DB provisioning (Neon/Supabase/RDS), Redis (Upstash), health check, rollback.
5. tests/test_p0a_deploy.py — invite-code validation, auth-with-invite flow, Redis-cache path (mock), env contract.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden identical.
COMMIT "feat(P0a): invite-gated beta auth + landing + managed DB wiring + runbook" and PUSH origin/codex/p0a-deploy. Do NOT merge.
Reply to parent: the auth/invite design, landing, DB/Redis wiring, runbook outline, tests, gates, commit SHA.