# Scryglass Monitoring Guide (P0b)

What to watch on the closed beta, where each signal comes from, and when to
page someone. The deep health probe is `/api/health/deep`; the remaining
signals come from Sentry, access logs, and `/api/cache-status`.

## Deep health probe

`GET /api/health/deep` — public (no session needed), returns one JSON object:

```json
{
  "status": "ok",
  "checks": {
    "db":     {"status": "ok", "backend": "postgresql", "configured": true},
    "cache":  {"status": "ok", "enabled": true, "backend": "redis",
               "hits": 12841, "misses": 902, "hit_ratio": 0.934,
               "cached_entries": 711},
    "golden": {"status": "ok", "patch": "16.15", "checked_at": "2026-08-06T...",
               "age_days": 0.2, "stale_threshold_days": 14},
    "engine": {"status": "ok", "registered": 173, "reviewed": 173,
               "module_contract": "champion_module_v1"}
  },
  "generated_at": "..."
}
```

Overall status: `ok` when every check is ok, `degraded` when a check is
stale/missing/degraded, `error` when any check failed.

| Check | Fails when | Meaning |
| --- | --- | --- |
| `db` | `SELECT 1` fails | Persistence is down — every save/share/feedback path breaks. **Page.** |
| `cache` | counters unreadable (Redis/DB error) | The result cache backend is down; cache reads fail closed rather than serve stale data. **Page.** |
| `golden` | `staleness.json` age ≥ 14 days (`stale`), or missing | The data cache has not been re-validated against the current patch. **Alert; run patch regression.** |
| `engine` | registered champion count is 0 (`degraded`) | Champion modules failed to load — the certified engine is empty. **Page.** |

Alert cadence: poll every 60s; alert on `status != ok` for more than 3
consecutive polls (15 min of staleness is a warning, not an incident; `error`
status is immediate).

## The five operational signals

### 1. Error rate (Sentry + logs)

- **Source**: Sentry (when `SENTRY_DSN` is set; `SENTRY_ENVIRONMENT`
  optional) + Gunicorn `--error-logfile`.
- **What to watch**: 500s per minute. The app reports every unhandled
  exception via `capture_exception` (rate-limit 429s are deliberately
  excluded). Zero 500s is the steady state; any 500 is a bug in the beta.
- **Threshold**: alert on any 500 spike > 0 sustained for 5 minutes, or any
  single 500 on a `reviewed_event_order` champion (certified modules should
  never throw).

### 2. 429 rate (abuse control)

- **Source**: access logs (`status=429`) or a log aggregation query on the
  `Retry-After` header.
- **What to watch**: 429s are the token bucket doing its job — expected
  during UI bursts, bad when sustained. Budgets: `/api/calculate` 40-burst /
  20 req/s refill; `/api/optimize` 2-burst / 1 per 10 s refill.
- **Threshold**: sustained > 5% of API requests returning 429 over 15
  minutes → check for a runaway client or an attack; the same pattern with
  `Retry-After` climbing is a legitimate overload signal → scale workers.

### 3. BIS p95 latency

- **Source**: `scripts/load_sanity.py` (p95 < 5s budget) or APM timings on
  `/api/bis`.
- **What to watch**: BIS is the most expensive endpoint (exhaustive candidate
  ranking over the shop). p95 trending toward the 5s budget means the
  optimizer is slowing down — usually a data-size regression, not load.
- **Threshold**: p95 ≥ 5s on the weekly load sanity run → investigate before
  patch day.

### 4. Cache hit ratio

- **Source**: `/api/cache-status` (`hits`, `misses`, `cached_entries`);
  `hit_ratio` is computed in `/api/health/deep` → `checks.cache`.
- **What to watch**: steady-state ratio below ~0.9 means the UI is generating
  many distinct loadouts (normal for a research tool) or the cache is being
  flushed too often (patch updates clear it — expect a dip right after).
- **Threshold**: ratio < 0.7 for a full day → inspect `cached_entries` and
  request-key diversity; consider raising `CACHE_TTL_SECONDS`.

### 5. Staleness age

- **Source**: `/api/health/deep` → `checks.golden` (`age_days` vs
  `stale_threshold_days = 14`).
- **What to watch**: every new LoL patch (two-week cadence) the data cache
  must be re-pulled (`scripts/patch_update.py run`) and the staleness report
  regenerated (`python scripts/patch_regression.py check ...`). An `age_days`
  crossing 14 means the golden check goes `stale` and the calculator can no
  longer vouch for current-game numbers.
- **Threshold**: page the on-call on the day a patch ships if the report has
  not been refreshed.

## How to query each signal

```bash
# Deep health (public)
curl -fsS https://scryglass-item-calculator.vercel.app/api/health/deep

# Cache counters
curl -fsS https://scryglass-item-calculator.vercel.app/api/cache-status

# Liveness (uptime monitors)
curl -fsS https://scryglass-item-calculator.vercel.app/healthz

# Load sanity against a local server (weekly)
python scripts/load_sanity.py            # spawns its own server
python scripts/load_sanity.py --url http://127.0.0.1:8000
```

## Incident response shortcuts

- **Cache backend down**: cache reads raise `CacheUnavailable` —
  `/api/cache-status` 503s and cached endpoints error rather than serve stale
  data. Restart/repair Redis; the cache self-heals under load (no data loss —
  it is derived).
- **Golden stale**: run `scripts/patch_update.py run`, commit the refreshed
  `data/`, deploy. The badge (`/api/staleness`) and `checks.golden` flip back
  to ok automatically once the new report is live.
- **Engine degraded**: `checks.engine.registered == 0` means champion module
  loading broke — check the deploy for a missing module file, roll back the
  app immediately.
- **DB down**: all persistence endpoints 503/500. Restore per
  `docs/backup-runbook.md`; consider provider PITR first, logical dump second.
