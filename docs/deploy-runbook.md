# Scryglass Closed-Beta Deployment Runbook (P0a)

This runbook is the step-by-step path from "code merged on
`codex/p0a-deploy`" to a live, invite-gated beta on Vercel backed by
managed Postgres (Neon / Supabase / RDS) and Redis (Upstash).

Read `docs/deploy.md` first for the baseline Vercel flow; this document
covers the P0a managed-infrastructure and invite-gate specifics.

## Topology

```
Browser ──► Vercel (Flask, src/app.py)
              │  app-level gate: SCRYGLASS_AUTH_REQUIRED + invite code
              ├─► Postgres (DATABASE_URL)  builds / share links / feedback
              └─► Redis (REDIS_URL)        calculation result cache
```

- The **app gate is the access control**. Vercel's own Deployment Protection
  must be **off** (see below) or it would intercept every request — including
  the login page itself — before the app can authenticate anyone.
- `/healthz` is public (no auth) so uptime monitors and the platform can
  probe liveness.
- `/privacy` and `/api/auth/invite` are also public pre-auth surface: the
  landing page links to them while the visitor is logged out.

## 1. Provision the database (Postgres)

The app reads `DATABASE_URL` at first database use and creates its tables
automatically (`Base.metadata.create_all`), so no migration step is needed.
Choose one provider:

- **Neon** — create a project, copy the pooled or direct connection string:
  `postgresql://user:password@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`.
  Add `?sslmode=require` to keep TLS on.
- **Supabase** — create a project, use the connection string from
  *Settings → Database*: `postgresql://postgres:password@db.xxx.supabase.co:5432/postgres`.
- **AWS RDS** — create a Postgres instance; allow the Vercel deployment's
  region in the security group (or use a VPC peering / proxy setup if your
  Vercel project is team-scoped): `postgresql://user:password@db-instance.region.rds.amazonaws.com:5432/lcc`.

Notes:

- `postgres://` and `postgresql://` URLs are normalized to the psycopg3
  driver automatically; either scheme works.
- Timestamps are stored as naive UTC; set the server timezone to UTC
  (Neon/Supabase default; RDS set `timezone = 'UTC'`).
- Keep the fallback in mind: with no `DATABASE_URL` the app uses a local
  SQLite file — fine for development, never for the beta.

## 2. Provision Redis (result cache)

The result cache uses Redis when `REDIS_URL` is set and otherwise falls back
to the `CachedResult` table in Postgres. For the beta, put the cache in
managed Redis so cache churn never touches the transactional database.

- **Upstash** — create a database (e.g. `scryglass-cache`), copy the TLS
  URL: `rediss://default:password@xxx.upstash.io:6379`. Prefer the `rediss://`
  (TLS) endpoint.
- The `redis` package is imported lazily: SQLite-only installs and the test
  suite never need it, and the Docker image ships it in
  `requirements-runtime.txt`.

Cache behavior:

- Entries are stored under `scryglass:cache:entry:*` with a TTL of
  `CACHE_TTL_SECONDS` (default 86400 = 24h).
- Hit/miss counters live in the `scryglass:cache:counters` hash; they are
  *not* wiped by a cache flush.
- `cache_delete_all()` (called after data updates) clears only the entry
  prefix.
- If Redis is unreachable, cache reads raise `CacheUnavailable` and the
  affected requests fail closed rather than serve stale data;
  `/api/health/deep` reports `checks.cache.status: "error"` with the backend
  name.

## 3. Configure Vercel

### Project setup

```bash
vercel link --project scryglass-item-calculator
```

### Build command

**None required.** Vercel detects the Python runtime from `pyproject.toml`
and installs the small production dependency set (`Flask`, `gunicorn`,
`SQLAlchemy`, `psycopg`, `redis`) with its native uv builder. `src/app.py`
is the detected WSGI entry point. If you ever need an explicit install step
(legacy CLI path), the pinned equivalent is:

```text
installCommand: python3 -m pip install -r requirements-runtime.txt
```

### Environment variables (Production)

Set every variable below in *Vercel → Project → Settings → Environment
Variables → Production*. Secrets (`SCRYGLASS_AUTH_SECRET`,
`SCRYGLASS_AUTH_USERS`, `DATABASE_URL`, `REDIS_URL`) should be marked
"Encrypt" / sensitive. See `.env.example` for the full annotated list.

| Variable | Value |
| --- | --- |
| `SCRYGLASS_AUTH_REQUIRED` | `1` |
| `SCRYGLASS_AUTH_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SCRYGLASS_AUTH_USERS` | JSON object of account → `scrypt$` hash (generator in `.env.example`) |
| `SCRYGLASS_INVITE_CODES` | comma-separated codes, e.g. `BETA-2026,PRESS-CLUB` |
| `DATABASE_URL` | managed Postgres URL from step 1 |
| `REDIS_URL` | managed Redis URL from step 2 |
| `CACHE_TTL_SECONDS` | optional, default `86400` |

### Turn OFF Vercel Deployment Protection

*Vercel → Project → Settings → Deployment Protection*: **disable** the
built-in authentication (set to "Disabled" / standard protection). The app
gate is the access control; Vercel's layer would lock out the invite form
and `/api/auth/invite` before they ever reach Flask.

### Deploy

```bash
git push origin codex/p0a-deploy          # reviewed branch only
vercel deploy --prod
```

Promote only after the verification gates pass (see `README.md`):
`pytest`, `pylint`, `black --check`, golden snapshot.

## 4. Health check

- Public probe: `curl -fsS https://scryglass-item-calculator.vercel.app/healthz`
  → `{"status":"ok"}`.
- Deeper check after deploy:
  `curl -fsS https://…/api/health/deep` → `checks.cache` carries `backend`,
  `enabled`, `hits`, `misses`, `cached_entries`; `checks.db` carries
  `backend` and `configured`. Expect `"backend":"redis"` under `cache` and
  `"configured":true` under `db` on the beta.
- Optional uptime monitor (UptimeRobot / Cronitor) hitting `/healthz` every
  60s; alert on non-200.

## 5. Rollback

1. **App code**: `vercel rollback <deployment-url>` to the last known-good
   deployment (or redeploy a previous commit). The env vars stay attached to
   the project, so rollback is instant.
2. **Database**: schema changes are additive-only (`create_all` never drops
   columns), so no migration rollback is needed. If a bad deploy wrote bad
   rows, clean them with SQL against the managed DB — the app tolerates a
   missing row (404) but not a malformed one.
3. **Cache**: after rolling code back, flush the result cache so stale
   payloads from the bad deploy don't linger under the 24h TTL:
   `redis-cli -u $REDIS_URL --scan --pattern 'scryglass:cache:entry:*' | xargs redis-cli -u $REDIS_URL del`
   (or `DEL` via the Upstash console). The counters hash is left intact.

## 6. Day-2 operations

- **Rotating invite codes**: change `SCRYGLASS_INVITE_CODES` and redeploy.
  Existing sessions keep their recorded invite source until the 7-day cookie
  expires; new logins need a current code.
- **Adding a research account**: generate an `scrypt$` hash with the Python
  used by the test suite (see `.env.example`) and add the account to
  `SCRYGLASS_AUTH_USERS`, then redeploy.
- **Data updates (patch day)**: run `scripts/patch_update.py run` locally,
  commit the refreshed `data/` cache, deploy. The deploy-time data update
  endpoints are dev-only; the result cache is invalidated automatically on
  updates that run through `/api/update-data` locally.
