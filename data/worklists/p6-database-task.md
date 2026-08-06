You are building the REAL DATABASE layer (P6) for a League of Legends combat calculator, replacing the Vercel-frontend-only store.

YOUR WORKTREE: /Users/river/Projects/lcc-p6 (branch codex/p6-database). Work ONLY here. Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: The Flask backend (src/app.py) currently persists nothing except a SQLite token-bucket rate limiter in /tmp. The product needs: cached calculation results, saved builds, share links, validation feedback, and staleness state. The user said: "Vercel + frontend does not seem to be cutting it. we need a proper database."

DELIVERABLES:
1. src/db.py — a database layer using PostgreSQL via SQLAlchemy 2.x (psycopg3 driver). Models:
   - Build (id, champion, level, role, items JSON, item_options JSON, ability_ranks JSON, champion_options JSON, enemies JSON, allies JSON, fight_params JSON, created_at)
   - ShareLink (token UNIQUE, build_id FK, slug, views, created_at)
   - CachedResult (cache_key UNIQUE, payload JSON, created_at, expires_at) — for /api/calculate + /api/bis result caching with a TTL
   - ValidationFeedback (id, champion, loadout JSON, expected JSON, actual JSON, source "manual|combat_log|practice_tool", matched bool, note, created_at)
   - StalenessState (patch, payload JSON, checked_at)
2. Connection handling: DATABASE_URL env var; SQLite fallback ONLY for tests/local without Postgres (use a DATABASE_URL=sqlite:///... in tests); automatic table creation on first use (no alembic required, but document the schema).
3. New API endpoints in src/app.py:
   - POST /api/builds (save a build) → {"build_id": ...}
   - GET /api/builds/<id> → the build payload (or 404)
   - POST /api/share (create share link from a build) → {"token": ...}
   - GET /api/share/<token> → build payload (+view counter increment)
   - POST /api/feedback (validation feedback) → {"feedback_id": ...}
   - GET /api/feedback?champion=... → recent feedback (for the validation loop)
   - GET /api/cache-status → cache hit/miss counters
4. Wire result caching: /api/calculate and /api/bis consult CachedResult (key = stable hash of the request JSON) when DATABASE_URL is configured; bypass in TESTING. Cache invalidation on /api/update-data.
5. docker-compose.yml at repo root with a postgres service for local dev.
6. tests/test_p6_database.py — save/load build, share-link round-trip + view increment, feedback write/read, cache set/get/TTL, SQLite fallback path.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden compare (identical — engine untouched).
COMMIT "feat(P6): PostgreSQL persistence — builds, share links, result cache, validation feedback" and PUSH origin/codex/p6-database. Do NOT merge.
Reply to parent: schema, connection strategy, endpoints, cache semantics, docker-compose, tests, gates, commit SHA. Note any endpoint the P5 UX agent should consume for build-sharing.