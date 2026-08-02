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

The tracked `data/` cache is read-only at runtime. `/api/update-data` is available only in explicit local development mode; patch refreshes are committed before deployment.

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
