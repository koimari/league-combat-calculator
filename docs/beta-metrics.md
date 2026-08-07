# Beta Metrics & Pass/Fail Gate (P1b)

What "beta success" means for the Scryglass closed beta, how each metric is
measured, and the gate that decides PASS/FAIL.  The operational readers of
this document are: the beta operator (weekly checklist in
`docs/beta-operations.md`), the dashboard consuming `scripts/beta_metrics.py
--json`, and any future work that touches the event stream.

## The gate in one paragraph

The beta runs for **2 weeks**.  A beta **PASSES** when all four criteria
hold:

| Criterion | Threshold |
| --- | --- |
| Activation | ≥ 60% of engaged sessions complete champion → role → Best-next-item in < 10 s |
| 7-day retention | ≥ 25% of sessions return within 7 days of their first activity |
| Validation receipts | ≥ 20 receipts per week, with ≤ 2 champions flagged by the bias scan |
| Staleness SLA | no staleness flag older than 72 h (patch-regression report fresh) |

A beta **FAILS** when **any criterion is missed 2 weeks running** (the
"2-weeks-running" rule).  A criterion missed in exactly one week is
**at-risk** (gate `pending`), not failed.  The gate is evaluated by
`scripts/beta_metrics.py` (CLI) and served by `GET /api/metrics` (dashboard
endpoint); both run the same `compute_scorecard` function so the two can
never disagree.

## Why session ids instead of a user table

Auth (`P0a`) has no user table — only signed stateless cookies.  Building
one just for metrics would be the biggest piece of the beta.  Instead every
metric that is "per user" is measured through an **anonymous session id**:

- The app mints a random first-party cookie (`scryglass_anon`,
  `secrets.token_urlsafe(24)`, HttpOnly, SameSite=Lax, 90-day lifetime) on
  the first instrumented write and records it on **`builds`**,
  **`share_links`**, **`validation_feedback`** and **`metrics_events`**
  rows (`session_id` column).
- The id is random and carries **no PII** — no username, email, invite
  code, or IP.  It cannot be reversed into an account.
- Legacy rows saved before P1b have `session_id = NULL` and are excluded
  from per-session metrics (counted in `data_sources.sessions_without_id`).

This is a proxy, and the proxy is documented: "users" below means
"sessions", and a session that never touches an instrumented endpoint is
invisible.  Activation is therefore measured among **engaged sessions**
(sessions that saved a build, shared one, posted feedback, or fired an
event) — a conservative funnel that cannot over-count.

## Metric definitions

### Activation — `quick_complete` funnel

The frontend fires `POST /api/metrics/event` with
`{"event": "quick_complete", "took_ms": <ms>}` when a user completes the
onboarding flow champion → role → Best-next-item.  `took_ms` is the
wall-clock time from flow start to the Best-next-item result.

```
activation = sessions with a quick_complete event (took_ms < 10000)
           / sessions with any activity in the window
```

- The `< 10 s` boundary is strict: `took_ms < 10000` counts,
  `took_ms >= 10000` does not.
- The event is **anonymous** (session-scoped, no PII), **rate-limited**
  (60-burst / 1 per 5 s sustained) and **pre-auth** so funnel events are
  collectable even from sessions that never log in.
- The event whitelist lives in two mirrored places — `src/db.py`
  (`_VALID_METRIC_EVENTS`) and `src/app.py` (`_METRICS_EVENT_NAMES`).
  Adding a funnel step is a one-line extension of both.

### 7-day retention

```
retention = sessions whose first observed activity is followed by another
            activity 1-7 days later (a later-day visit within a week)
          / sessions first active in the window with >= 7 days elapsed
```

- "Returning" is a **later-day** visit: same-day duplicate activity (a
  build and an event at the same timestamp) does not count as a return.
- A session that first appears fewer than 7 days before the evaluation
  time is **not yet eligible** (it has not had a chance to return) and is
  excluded from the denominator; until any cohort is eligible the
  criterion reports `insufficient_data`.
- In a 2-week beta the week-1 cohort is the only fully observable cohort;
  its 7-day return rate is the retention number the gate uses.

### Validation receipts + bias scan

- **Receipts** = `validation_feedback` rows with a signed `delta`
  (exactly the population `POST /api/receipts` writes; plain P6 feedback
  rows have `delta = NULL` and do not count).  Threshold: **≥ 20 per
  week**.
- **Bias scan** = the `db.validation_summary` semantics, re-derived by the
  scorecard at each week boundary: a champion is **flagged** when it has
  `n >= 5` receipts and `|mean(observed - predicted) / predicted| > 15%`.
  Threshold: **≤ 2 flagged champions**.  A flag is a triage signal (see
  `docs/beta-operations.md` step 4), and the receipts criterion fails when
  the flagged count exceeds 2 for 2 weeks running.

### Staleness SLA (P0d)

The patch-regression report (`data/staleness.json`, served by
`/api/staleness`) is the age of every flag in it: the report's
`checked_at` is when each `stale: true` champion/item entry was last
verified.  The SLA is **no flag older than 72 h**, which is exactly
`now - checked_at <= 72 h` with a report present.

- Missing report → the criterion fails (a calculator with no verified
  patch state is stale).
- Per-week evaluation: a week passes when a report was checked during that
  week and was ≤ 72 h old at the week's end.  A report checked after a
  week ended leaves that week `insufficient_data` (no evidence).
- `/api/health/deep` (P0b) monitors the same state continuously; the
  scorecard is the weekly bookkeeping view.

## The 2-weeks-running gate

`scripts/beta_metrics.compute_scorecard` evaluates every criterion over the
last two complete 7-day windows of the beta:

- **2 misses** in the last two complete weeks → criterion `fail`.
- **1 miss** → `at_risk`.
- In-progress (incomplete) weeks are never judged — a partial week cannot
  produce a miss.
- `retention` is a cohort metric: it has a single evaluation at beta end
  (week-1 cohort).  Its fail is a gate fail.
- `staleness` is a continuous SLA: its weekly verdicts come from the
  report's `checked_at`; a report that predates a week fails that week.

Overall gate:

| gate status | meaning |
| --- | --- |
| `pass` | every criterion passes and the beta is complete |
| `pending` | beta in progress, or a criterion is `at_risk`/`insufficient_data` |
| `fail` | any criterion missed 2 weeks running (or a cohort/SLA criterion failed at its single evaluation) |

An empty database fails `receipts` (0 < 20 in both weeks) and leaves
`activation`/`retention` `insufficient_data` → gate `fail`/`pending`
depending on staleness.  Operators should therefore start the clock with
`--beta-start` at the real beta launch instead of the default (14 days
before the run).

## Endpoints

### `POST /api/metrics/event` — anonymous funnel events

```json
{"event": "quick_complete", "took_ms": 1234}
```

- `event` must be a whitelisted name; `took_ms` an integer in
  `[0, 3_600_000]`.  Rejections are `400` with a JSON `error`.
- Rate-limited via the shared token-bucket store (policy
  `metrics_event`); `429` when the budget is spent.
- Pre-auth (exempt from the auth gate) so it works in any browser session.
- Mints/sets the `scryglass_anon` cookie on first use; the recorded
  `session_id` is that cookie's value.
- `201 {"event_id": N, "event": "quick_complete"}`.

### `GET /api/metrics` — scorecard (auth-gated)

- Behind the closed-beta auth gate (not on the pre-auth allowlist).
- Returns exactly the `compute_scorecard` payload below.

## Scorecard CLI

```bash
DATABASE_URL=postgresql+psycopg://... python scripts/beta_metrics.py
DATABASE_URL=... python scripts/beta_metrics.py --json          # dashboard
DATABASE_URL=... python scripts/beta_metrics.py \
    --beta-start 2026-07-23 --weeks 2 --json
```

| flag | default | meaning |
| --- | --- | --- |
| `--json` | off | emit the raw scorecard JSON instead of the human table |
| `--now` | now | evaluation time (ISO date or datetime) |
| `--beta-start` | now − 14 d | first day of the beta |
| `--weeks` | 2 | beta length in weeks |
| `--staleness-report` | `data/staleness.json` | patch-regression report path |

Exit code: `0` when the gate is `pass` or `pending`, `1` when `fail`
(so dashboards/CI can react).  The CLI reads the same `DATABASE_URL` as the
app and queries `builds`, `share_links`, `validation_feedback`,
`metrics_events` plus the cache counters.

### Scorecard JSON schema

```jsonc
{
  "generated_at": "2026-08-06T16:45:42Z",
  "beta": {"start": "...", "end": "...", "weeks": 2, "window_days": 14, "complete": true},
  "data_sources": {
    "sessions_observed": 50, "sessions_without_id": 3,
    "builds": 40, "shares": 12, "feedback": 30, "metrics_events": 120,
    "receipts": 25,
    "cache": {"backend": "...", "hits": 100, "misses": 20, "hit_ratio": 0.83, "cached_entries": 5}
  },
  "criteria": {
    "activation": {
      "status": "pass|fail|at_risk|insufficient_data",
      "value": 0.7, "threshold": 0.6,
      "numerator": 35, "denominator": 50, "detail": "...",
      "weeks": [{"week": 1, "complete": true, "status": "pass", "value": 0.68,
                 "numerator": 17, "denominator": 25}]
    },
    "retention": { /* same shape, threshold 0.25 */ },
    "receipts": {
      "status": "pass", "value": 47, "threshold": 20,
      "weeks": [{"week": 1, "complete": true, "count": 25, "status": "pass"}]
    },
    "bias": {
      "status": "pass", "value": 1, "threshold": 2,
      "weeks": [{"week": 1, "complete": true, "flagged": 1, "status": "pass"}]
    },
    "staleness": {
      "status": "pass", "value_hours": 4.3, "threshold_hours": 72,
      "report": {"exists": true, "patch": "16.15", "checked_at": "...",
                 "age_hours": 4.3, "stale_flags": 5},
      "weeks": [{"week": 1, "complete": true, "status": "insufficient_data", "detail": "..."}]
    }
  },
  "gate": {"status": "pass|pending|fail", "rule": "...",
           "missed_weeks": {"activation": 0, "receipts": 0, "bias": 0, "staleness": 0},
           "verdict": "PASS|PENDING|FAIL"}
}
```

## Data model & migration

New `metrics_events` table plus a `session_id` column on `builds`,
`share_links` and `validation_feedback` (nullable — legacy rows predate
the instrumentation).  `Base.metadata.create_all` creates the new table on
fresh databases; `db._ensure_metrics_schema` runs one guarded
`ALTER TABLE ... ADD COLUMN` per missing column so the **live beta Postgres
database upgrades in place** with no alembic step.  See
`docs/database-schema.md` for the schema contract.

## Privacy

The event stream stores only: event name, anonymous session id, `took_ms`
(a duration), and a small JSON payload.  No account identifiers, no IPs,
no free-text.  The `scryglass_anon` cookie is first-party, HttpOnly, and
never cross-linked to the signed auth cookie.

## Shared home (issue #144)

The scorecard implementation lives in `src/metrics.py` (ships in the deployed runtime package); `scripts/beta_metrics.py` is a thin CLI wrapper.
