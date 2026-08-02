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

If Vercel rejects a CLI upload because the local Git author is not a team member, deploy an archive without `.git` metadata. Do not rewrite commit authorship.
