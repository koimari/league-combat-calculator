# Deployment

The app deploys as one Flask function on Vercel. `src/app.py` is the detected WSGI entry point; no build command or output directory is required.

## Preview

```bash
vercel link --project scryglass-item-calculator
vercel deploy
```

## Production

Run the full verification commands in `README.md`, verify the preview, then deploy the reviewed branch. A successful production deployment receives the `https://scryglass-item-calculator.vercel.app` alias.

```bash
vercel deploy --prod
```

The tracked `data/` cache is read-only at runtime. `/api/update-data` is available only in explicit local development mode and only when `LOL_CALC_DEV_UPDATE_TOKEN` is set — unset, it 404s on every worker. Never set either variable on a deployment; patch refreshes are committed before deployment.

## Private access

The production calculator is gated by a small local username/password form. Set
these Vercel Production variables before promoting a deployment:

```text
SCRYGLASS_AUTH_REQUIRED=1
SCRYGLASS_AUTH_SECRET=<long random signing secret>
SCRYGLASS_AUTH_USERS=<JSON object of account names to scrypt$ hashes>
```

Passwords are never committed to the repository. Generate a hash with the same
Python 3.14 environment used by the test suite, then add the resulting JSON as
the sensitive `SCRYGLASS_AUTH_USERS` variable. The app stores only a signed,
seven-day session cookie; `/healthz` remains public for deployment probes.

If Vercel rejects a CLI upload because the local Git author is not a team member, deploy an archive without `.git` metadata. Do not rewrite commit authorship.

## Metrics smoke (issue #144)

After deploy, `GET /api/metrics` must return the scorecard, not a 503 — "Metrics module unavailable" means the module failed to ship, "Database unavailable" means Postgres is unreachable. Assert the shape, not the status:

```bash
curl --silent --show-error --cookie "scryglass_session=<session>" \
  https://<beta-host>/api/metrics | python -c 'import json,sys
s = json.load(sys.stdin)
assert set(s["criteria"]) == {"retention", "receipts", "bias", "staleness"}, s
assert s["gate"]["verdict"] in {"PASS", "PENDING", "FAIL"}, s["gate"]
print(s["gate"]["verdict"], {k: v["status"] for k, v in s["criteria"].items()})'
```

The CI container job runs without a database, so it asserts only what a
DB-less container can show: the module shipped (`gate` present, or the
distinct "Database unavailable" 503).
