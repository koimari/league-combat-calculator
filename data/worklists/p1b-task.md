You are defining BETA METRICS + the pass/fail gate (P1b) for the Scryglass calculator.

YOUR WORKTREE: /Users/river/Projects/lcc-p1b (branch codex/p1b-metrics). Python: /Users/river/Projects/league-combat-calculator-audit/.venv/bin/python.

CONTEXT: The beta has: P7 validation feedback (/api/receipts + /api/validation), staleness (/api/staleness), build/share persistence (Postgres), result cache (Redis), P0b deep health (/api/health/deep). Now define what "beta success" means and instrument it.

YOU OWN: src/app.py (metrics routes only), src/db.py (metrics tables only if needed), scripts/beta_metrics.py (new), docs/beta-metrics.md (new), tests/test_p1b_metrics.py (new).

DELIVERABLES:
1. docs/beta-metrics.md — the beta success framework with a PASS/FAIL gate:
   - Activation: % of invited users who complete champion→role→Best-next-item in <10s (measure: a lightweight frontend event POST /api/metrics/event {event: "quick_complete", took_ms} — add that endpoint; anonymous session-scoped, no PII).
   - Retention: users returning within 7 days (DB: builds/shares created per user per week — but auth has no user table; measure via session cookie id recorded on builds/share_links/feedback rows — add a session_id column where missing).
   - Validation receipts: >= N receipts/week (N defined), bias scan via /api/validation stays < ±15% flagged count.
   - Stale flags: zero stale flags > 72h (P0d SLA) — via /api/staleness + /api/health/deep.
   - PASS criteria: activation >= 60%, 7-day retention >= 25%, receipts >= 20/week, no stale > 72h — for a 2-week beta. FAIL = any criterion missed 2 weeks running.
2. scripts/beta_metrics.py — a CLI that queries the DB (builds/share_links/feedback/cache/staleness) + the event log and prints the scorecard with PASS/FAIL per criterion. --json output for the dashboard.
3. Endpoints: POST /api/metrics/event (anonymous, rate-limited, stores to a metrics_events table) + GET /api/metrics (auth-gated, returns the scorecard).
4. tests: event recording + rate limit, scorecard computation from seeded rows, PASS/FAIL logic, docs exist.

GATES: pytest -q full; pylint src/ --fail-under=9; black --check src/ tests/; git diff --check; golden identical (no engine change).
COMMIT "feat(P1b): beta metrics + pass/fail gate + event capture" and PUSH origin/codex/p1b-metrics. Do NOT merge.
Reply to parent: metric definitions + PASS/FAIL thresholds, endpoints, scorecard CLI, tests, gates, commit SHA.