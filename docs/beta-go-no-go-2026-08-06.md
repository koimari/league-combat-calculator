# Beta Go / No-Go Decision — 2026-08-06

**Decision: NO-GO** (not GO)

## Summary

The F4 code fix is verified and the full test suite passes (4154 tests passed).
However, operational evidence required for beta go remains insufficient, so the
gate remains **PENDING** and the decision is **NO-GO**.

## Current Operational State

| Item | Status |
|---|---|
| F4 code fix | Fixed — full suite: **4154 passed** |
| `beta_metrics` — sessions_observed | **0** |
| `beta_metrics` — metrics_events | **0** |
| `beta_metrics` — receipts | **0** |
| Activation status | **insufficient_data** |
| Retention status | **insufficient_data** |
| Receipts status | **insufficient_data** |
| Staleness status | **insufficient_data** |
| Beta gate | **PENDING** |
| Production commit `3c11a59` | Deployed **READY** under `koidevelopments` |
| `/healthz` | HTTP **200** |
| `/api/health/deep` | HTTP **200** |
| Sentry DSN | **Unavailable** (billing inactive) |
| Auth encrypted env values | **Configured encrypted; values not printed** |

## Production Metrics Verification

Production metrics were verified by running:

```
vercel env run --scope koidevelopments -e production -- .venv/bin/python scripts/beta_metrics.py --beta-start 2026-08-06T22:29:00+00:00 --weeks 2 --json
```

This returned `sessions_observed=0`, `builds=0`, `metrics_events=0`,
`receipts=0`, and the beta gate remained **PENDING** — the window is not yet
complete.

The canonical completed window was also checked:

```
vercel env run --scope koidevelopments -e production -- .venv/bin/python scripts/beta_metrics.py --beta-start 2026-07-23 --weeks 2 --json
```

It returned receipts **FAIL** (0/week for both weeks) and an overall **FAIL**.

Because the GO criteria are unmet, **no invites were distributed**.

## Team-scoped deployment verification

The latest semantic F4 patch (`3c11a59`) was deployed with
`vercel deploy --scope koidevelopments --prod --yes` as deployment
`dpl_HtZB2GNy8CmY67X6PdMHiV42LNcS`. The production alias remains healthy:
`/healthz` and `/api/health/deep` return HTTP 200, with Postgres, Redis, and
173/173 reviewed champions reported healthy. This deployment does not change
the NO-GO decision: production beta traffic is still absent.

## Go Thresholds (evidence required before GO)

- Activation **>= 60%**
- Retention **>= 25%**
- Receipts **>= 20 / week**
- No stale flag **> 72h**
- Exact evidence required before GO (metrics must be populated and statuses
  no longer `insufficient_data`)

## Required before reconsidering GO

1. Real beta traffic producing `sessions_observed > 0`, `metrics_events > 0`,
   and receipts.
2. Activation, retention, receipts, and staleness statuses computed from real
   data, meeting the thresholds above.
3. Sentry DSN availability resolved (billing reactivated) or explicitly
   waived with rationale.
4. Auth encrypted env values verified (decryption/load check passed).
5. Beta gate flipped to PASSED only after all evidence is exact and recorded.

## Notes

- No secret values are included in this document.
- The decision record itself contains no source changes; subsequent semantic
  fixes and the team-scoped deployment are recorded separately in git and the
  deployment verification section above.
- No `git fetch` was used.
