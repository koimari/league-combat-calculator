# Beta operations

Everything that keeps the closed beta trustworthy between patch days: the weekly
checklist, the deep health probe, the five signals to watch, and what to do when one of
them goes red.

## Weekly checklist

30 minutes, once per week, before the patch-week cycle starts.

| # | Item | Command or endpoint | What to look for | Budget |
|---|---|---|---|---|
| 1 | Health and cache status | `curl https://<beta-host>/healthz`, `curl https://<beta-host>/api/health/deep` | `/healthz` 200; `checks.cache` ok with the backend up; hit and miss counters sane, since a miss spike means the cache was flushed rather than an outage | 5 min |
| 2 | Error surface | app logs (Vercel): 5xx, 429s, `CacheUnavailable`, SQLAlchemy errors | no new 503 or 500 classes; 429s on `/api/calculate` at the cap are normal, sustained 429s are not | 5 min |
| 3 | Backup verification | managed Postgres snapshot and Redis persistence (provider console, or a `pg_dump` dry run) | snapshot completed this week, and the restore path in `docs/backup-runbook.md` is current | 5 min |
| 4 | Validation-corpus bias scan | `curl https://<beta-host>/api/validation/champions`, `curl "https://<beta-host>/api/validation?champion=<name>"` | `flagged: true` entries, meaning n >= 5 receipts with \|bias\| > 15%; open a tracking issue and note it in the next announcement | 5 min |
| 5 | Feedback triage | `curl "https://<beta-host>/api/feedback?limit=50"`, with `?champion=` for flagged champions | unmatched receipts (`matched: false`), new champions users are testing, recurring notes | 5 min |
| 6 | Staleness sanity | `curl https://<beta-host>/api/staleness` | report exists; `patch` matches the live game patch (`cdtb versions game -a`) | 2 min |
| 7 | Log and decide | none | file findings, update the tracking issue, decide whether a mid-patch data refresh is needed (`docs/patch-day-runbook.md`) | 3 min |

Notes on three of the rows:

- **Bias-scan semantics** (`src/db.py::validation_summary`): bias is the signed mean
  percentage error of receipt deltas, `(observed - predicted) / predicted * 100`, and a
  champion is flagged when at least 5 receipts show a bias beyond 15%. A flag is a
  *corpus* signal, so triage whether it is a calculator bug, a test-practice error, or a
  loadout-context mismatch before touching the engine.
- **Backup verification**: an untested backup is not a backup. The five-minute version
  confirms snapshots exist and the documented restore path is current; restore-test at
  least monthly.
- **Staleness sanity**: if `/api/staleness` reports an older patch than the live game, a
  patch day has passed without a re-cert. Start the patch-day runbook immediately, against
  a detection SLA of 4 hours.

Any finding that changes calculation code triggers the full gate set in `CLAUDE.md`.
Docs-only findings commit without engine gates.

## Deep health probe

`GET /api/health/deep` is public and returns one JSON object:

```json
{
  "status": "ok",
  "checks": {
    "db":     {"status": "ok", "backend": "postgresql", "configured": true},
    "cache":  {"status": "ok", "enabled": true, "backend": "redis",
               "hits": 12841, "misses": 902, "hit_ratio": 0.934,
               "cached_entries": 711},
    "golden": {"status": "ok", "patch": "16.15", "checked_at": "...",
               "age_days": 0.2, "stale_threshold_days": 14},
    "engine": {"status": "ok", "registered": 173,
               "module_contract": "champion_module_v1"}
  },
  "generated_at": "..."
}
```

Overall status is `ok` when every check is ok, `degraded` when a check is stale, missing
or degraded, and `error` when any check failed.

| Check | Fails when | Meaning |
| --- | --- | --- |
| `db` | `SELECT 1` fails | Persistence is down, so every save, share and feedback path breaks. **Page.** |
| `cache` | counters unreadable | The result cache backend is down; cache reads fail closed rather than serve stale data. **Page.** |
| `golden` | `staleness.json` age >= 14 days, or missing | The data cache has not been re-validated against the current patch. **Alert, run patch regression.** |
| `engine` | registered champion count is 0 | Champion modules failed to load, so the certified engine is empty. **Page.** |

Poll every 60s and alert on `status != ok` for more than 3 consecutive polls. 15 minutes
of staleness is a warning, not an incident; an `error` status is immediate.

## The five operational signals

| Signal | Source | Threshold |
| --- | --- | --- |
| Error rate | Sentry when `SENTRY_DSN` is set, plus Gunicorn `--error-logfile`. Every unhandled exception is reported through `capture_exception`; rate-limit 429s are deliberately excluded | any 500 spike sustained for 5 minutes, or any single 500 on a `reviewed_event_order` champion, because a certified module should never throw |
| 429 rate | access logs (`status=429`). Budgets: `/api/calculate` 40-burst and 20 req/s refill, `/api/optimize` 2-burst and 1 per 10 s refill | sustained above 5% of API requests over 15 minutes. Check for a runaway client; the same pattern with `Retry-After` climbing is a legitimate overload signal, so scale workers |
| BIS p95 latency | `scripts/load_sanity.py`, or APM timings on `/api/bis`. BIS is the most expensive endpoint, ranking every candidate in the shop | p95 at or above 5s on the weekly run. That usually means a data-size regression rather than load, so investigate before patch day |
| Cache hit ratio | `/api/health/deep`, `checks.cache` | below 0.7 for a full day. Inspect `cached_entries` and request-key diversity, and consider raising `CACHE_TTL_SECONDS`. A steady-state ratio near 0.9 is normal for a research tool, and a patch update flushes the cache, so expect a dip right after one |
| Staleness age | `/api/health/deep`, `checks.golden` (`age_days` against `stale_threshold_days = 14`) | page on the day a patch ships if the report has not been refreshed. Past 14 days the golden check goes `stale`, and a stale check means the calculator cannot vouch for current-game numbers |

```bash
curl -fsS https://scryglass-item-calculator.vercel.app/api/health/deep
curl -fsS https://scryglass-item-calculator.vercel.app/healthz
python scripts/load_sanity.py            # spawns its own server
python scripts/load_sanity.py --url http://127.0.0.1:8000
```

## Incident response

- **Cache backend down**: cache reads raise `CacheUnavailable`, `checks.cache` reports
  `error`, and cached endpoints error rather than serve stale data. Repair Redis; the
  cache is derived, so it self-heals under load with no data loss.
- **Golden stale**: run `scripts/patch_update.py run`, commit the refreshed `data/`, and
  deploy. `/api/staleness` and `checks.golden` flip back to ok once the new report is live.
- **Engine degraded**: `checks.engine.registered == 0` means champion module loading
  broke. Check the deploy for a missing module file and roll the app back immediately.
- **DB down**: every persistence endpoint returns 503 or 500. Restore per
  `docs/backup-runbook.md`, trying provider point-in-time recovery first and a logical
  dump second.
