# Scryglass Beta Operations — Weekly Checklist (P0d)

30 minutes, once per week (suggest: Monday, before the patch-week cycle
starts). Purpose: keep the beta trustworthy between patch days — monitoring,
backup verification, validation-corpus bias scan, feedback triage.

## Checklist

| # | Item | Command / endpoint | What to look for | Budget |
|---|---|---|---|---|
| 1 | Health & cache status | `curl https://<beta-host>/healthz`, `curl https://<beta-host>/api/health/deep` | `/healthz` 200; `checks.cache` ok with the backend up; hit/miss counters sane (a miss spike means the cache was flushed, not an outage) | 5 min |
| 2 | Error surface | app logs (Vercel) — 5xx, 429s, `CacheUnavailable`, SQLAlchemy errors | no new 503/500 classes; 429s on `/api/calculate` at the cap are normal, sustained 429s are not | 5 min |
| 3 | Backup verification | managed Postgres snapshot + Redis persistence (provider console, or a `pg_dump` dry run) | snapshot completed this week; restore path documented and current (`docs/deploy-runbook.md` §1-2) | 5 min |
| 4 | Validation-corpus bias scan | `curl https://<beta-host>/api/validation/champions`, `curl "https://<beta-host>/api/validation?champion=<name>"` | `flagged: true` entries — n >= 5 receipts with \|bias\| > 15% — open a tracking issue and note it in the next announcement | 5 min |
| 5 | Feedback triage | `curl "https://<beta-host>/api/feedback?limit=50"` (+ `?champion=` for flagged champions) | unmatched receipts (`matched: false`), new champions users are testing, recurring notes | 5 min |
| 6 | Staleness sanity | `curl https://<beta-host>/api/staleness` | report exists; `patch` matches the live game patch (`cdtb versions game -a`) | 2 min |
| 7 | Log & decide | — | file findings, update the tracking issue, decide whether a mid-patch data refresh is needed (patch-day runbook Steps 2-5) | 3 min |

## Notes

- **Bias-scan semantics** (`src/db.py::validation_summary`): bias is the
  signed mean percentage error of receipt deltas
  `(observed - predicted) / predicted * 100`; a champion is flagged when at
  least 5 receipts show a bias beyond ±15%. A flag is a *corpus* signal —
  triage whether it is a calculator bug, a test-practice error, or a
  loadout-context mismatch before touching the engine.
- **Backup verification**: an untested backup is not a backup. The 5-minute
  version here confirms snapshots exist and the documented restore path is
  current; actually restore-test at least monthly.
- **Staleness sanity**: if `/api/staleness` reports an older patch than the
  live game, a patch day has passed without a re-cert — start the patch-day
  runbook immediately (detection SLA: < 4h).
- **Gate rule**: any finding that changes calculation code triggers the full
  gate set per `CLAUDE.md` (`pytest -q`, `pylint src/`, golden compare,
  `black --check src/ tests/ scripts/`); docs-only findings commit without
  engine gates.
