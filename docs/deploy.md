# Deployment

The app deploys as one Flask function on Vercel. `src/app.py` is the detected WSGI entry
point, and no build command or output directory is required: Vercel reads the Python
runtime from `pyproject.toml` and installs the production dependency set with its uv
builder. The pinned equivalent, if an explicit install step is ever needed, is
`python3 -m pip install -r requirements-runtime.txt`.

```
Browser ──► Vercel (Flask, src/app.py)
              │  app-level gate: SCRYGLASS_AUTH_REQUIRED + invite code
              ├─► Postgres (DATABASE_URL)  builds / share links / feedback
              └─► Redis (REDIS_URL)        calculation result cache
```

The **app gate is the access control**, so Vercel's own Deployment Protection must be
disabled under *Settings, Deployment Protection*. Its layer would intercept every request
including the login page, locking out the invite form and `/api/auth/invite` before they
reach Flask. `/healthz`, `/privacy` and `/api/auth/invite` are public pre-auth surface.

## Backing services

The app reads `DATABASE_URL` at first database use and creates its tables through
`Base.metadata.create_all`, so there is no migration step. Any managed Postgres works
(Neon, Supabase, RDS); keep TLS on with `?sslmode=require`, and set the server timezone to
UTC, because timestamps are stored as naive UTC. With no `DATABASE_URL` the app falls back
to a local SQLite file, which is for development only.

The result cache uses Redis when `REDIS_URL` is set and otherwise falls back to the
`CachedResult` table in Postgres. Prefer a managed `rediss://` endpoint so cache churn
never touches the transactional database. Entries live under `scryglass:cache:entry:*`
with a TTL of `CACHE_TTL_SECONDS`, and `cache_delete_all()` clears only that prefix, so
the `scryglass:cache:counters` hash survives a flush. If Redis is unreachable, cache reads
raise `CacheUnavailable` and the affected requests fail closed rather than serve stale
data, and `/api/health/deep` reports `checks.cache.status: "error"` with the backend name.

## Environment

Set every variable below in *Vercel, Project, Settings, Environment Variables,
Production*. Mark `SCRYGLASS_AUTH_SECRET`, `SCRYGLASS_AUTH_USERS`, `DATABASE_URL` and
`REDIS_URL` sensitive. `.env.example` carries the full annotated list and the hash
generator.

| Variable | Value |
| --- | --- |
| `SCRYGLASS_AUTH_REQUIRED` | `1` |
| `SCRYGLASS_AUTH_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SCRYGLASS_AUTH_USERS` | JSON object of account name to `scrypt$` hash |
| `SCRYGLASS_INVITE_CODES` | comma-separated codes, for example `BETA-2026,PRESS-CLUB` |
| `DATABASE_URL` | managed Postgres URL |
| `REDIS_URL` | managed Redis URL |
| `CACHE_TTL_SECONDS` | optional, default `86400` |

Passwords are never committed. Generate a hash with the same Python 3.14 environment the
test suite uses. The app stores only a signed, seven-day session cookie.

The tracked `data/` cache is read-only at runtime. `/api/update-data` is available only in
explicit local development mode and only when `LOL_CALC_DEV_UPDATE_TOKEN` is set;
unset, it 404s on every worker. Never set either variable on a deployment, because patch
refreshes are committed before deployment.

## Deploy

```bash
vercel link --project scryglass-item-calculator
vercel deploy            # preview
vercel deploy --prod     # production
```

Run the verification commands in `README.md`, verify the preview, then deploy the reviewed
branch. A successful production deployment receives the
`https://scryglass-item-calculator.vercel.app` alias. If Vercel rejects a CLI upload
because the local Git author is not a team member, deploy an archive without `.git`
metadata. Do not rewrite commit authorship.

## Health check

- Public probe: `curl -fsS https://scryglass-item-calculator.vercel.app/healthz` returns
  `{"status":"ok"}`.
- Deeper check: `curl -fsS https://…/api/health/deep`. `checks.cache` carries `backend`,
  `enabled`, `hits`, `misses` and `cached_entries`; `checks.db` carries `backend` and
  `configured`. Expect `"backend":"redis"` and `"configured":true` on the beta.
- An uptime monitor hitting `/healthz` every 60s alerts on non-200.

## Metrics smoke

After deploy, `GET /api/metrics` must return the scorecard, not a 503. "Metrics module
unavailable" means the module failed to ship; "Database unavailable" means Postgres is
unreachable. Assert the shape, not the status:

```bash
curl --silent --show-error --cookie "scryglass_session=<session>" \
  https://<beta-host>/api/metrics | python -c 'import json,sys
s = json.load(sys.stdin)
assert set(s["criteria"]) == {"retention", "receipts", "bias", "staleness"}, s
assert s["gate"]["verdict"] in {"PASS", "PENDING", "FAIL"}, s["gate"]
print(s["gate"]["verdict"], {k: v["status"] for k, v in s["criteria"].items()})'
```

The CI container job runs without a database, so it asserts only what a DB-less container
can show: the module shipped (`gate` present, or the distinct "Database unavailable" 503).

## Rollback

1. **App code**: `vercel rollback <deployment-url>` to the last known-good deployment, or
   redeploy a previous commit. The env vars stay attached to the project, so rollback is
   instant.
2. **Database**: schema changes are additive only, since `create_all` never drops columns,
   so there is no migration rollback. Clean bad rows with SQL against the managed
   database; the app tolerates a missing row with a 404 but not a malformed one.
3. **Cache**: flush the result cache so stale payloads do not linger under the TTL:
   `redis-cli -u $REDIS_URL --scan --pattern 'scryglass:cache:entry:*' | xargs redis-cli -u $REDIS_URL del`.
   The counters hash is left intact.

Restoring data, rather than rolling back code, is `docs/backup-runbook.md`.

## Day-2 operations

- **Rotating invite codes**: change `SCRYGLASS_INVITE_CODES` and redeploy. Existing
  sessions keep their recorded invite source until the seven-day cookie expires; new
  logins need a current code.
- **Adding a research account**: generate an `scrypt$` hash with the Python the test suite
  uses, add the account to `SCRYGLASS_AUTH_USERS`, redeploy.
- **Data updates on patch day**: run `scripts/patch_update.py run` locally, commit the
  refreshed `data/` cache, deploy. The deploy-time data update endpoints are dev-only.
