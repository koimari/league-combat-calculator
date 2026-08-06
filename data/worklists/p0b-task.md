You are building the CLOSED-BETA OPS FLOOR (P0b) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p0b (branch codex/p0b-ops). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

DELIVERABLES:
1. ERROR TRACKING: wire Sentry into src/app.py (sentry_sdk init when SENTRY_DSN env is set; lazy import; no-op without the DSN; capture_exception in the Flask error handlers + rate-limit 429s excluded). requirements entry. Tests: monkeypatched Sentry capture on a route error, no-DSN no-op.
2. DB BACKUPS: docs/backup-runbook.md + a scripts/backup_db.py (pg_dump for DATABASE_URL postgres, sqlite3 .backup for the SQLite fallback, Redis SAVE/read-only replication note; retention flags). Tests: dry-run mode.
3. MONITORING: a /healthz deep check extension — /api/health/deep returning a dict with db/cache/golden/engine statuses (golden stale when staleness.json age >= 14d) + docs/monitoring.md (what to watch: error rate, 429 rate, BIS p95 latency, cache hit ratio, staleness age).
4. LOAD SANITY TEST: scripts/load_sanity.py — concurrent /api/calculate + /api/bis requests (asyncio/httpx), N=10 concurrent users x 20 requests, asserting p95 latency budgets (calculate < 2s, bis < 5s) and that the result cache holds (2nd pass on the same loadout serves from cache — measure hit ratio >= 0.9). It must pass against a local server (start it in the script or document the requirement).
5. tests/test_p0b_ops.py.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden identical (no engine change).
COMMIT "feat(P0b): Sentry + backups + deep health + load sanity" and PUSH origin/codex/p0b-ops. Do NOT merge.
Reply to parent: wiring summary, load test results (latencies + cache hit ratio), docs, tests, gates, commit SHA.