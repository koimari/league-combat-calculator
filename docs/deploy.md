# Deploying the calculator

The app is a stateless Flask service: no business database, no logins, and the
entire data layer is the git-tracked `data/` cache (~10 MB of JSON). Patch-day
updates happen locally and reach the site as ordinary commits. At runtime, the
app writes only a disposable SQLite token-bucket file in the container's temp
directory so all Gunicorn workers share one CPU-abuse budget. There is nothing
to migrate or back up.

## The prod branch is the deploy gate

The hosting provider deploys from `prod`, never `master`. Work happens on
`master` as usual; the live site updates only when you promote:

```bash
git checkout prod
git merge --ff-only master   # refuses if prod has drifted; it never should
git push
git checkout master
```

Promote only when `pytest` and the golden gate are green on master.

## Dev mode vs. production

`LOL_CALC_DEV=1` (set by `run_web.bat`) enables the Update Data button and its
`/api/update-data` wiki re-scrape endpoint only for loopback requests. Render's
built-in `RENDER=true` marker disables it unconditionally, even if someone
accidentally sets `LOL_CALC_DEV`. The endpoint otherwise 404s and the frontend
hides the button. Local use also requires a localhost Host header and the
HttpOnly, SameSite=Strict bootstrap cookie set by `/api/config`, preventing a
website open in the browser from triggering the side-effectful SSE request.

Production env vars (Render dashboard → Environment):

- `PORT=10000` — Render routes to this port either way, but setting it
  explicitly skips Docker port *detection*, which on the first deploy took
  ~5 minutes — during which the edge intermittently answered plain-text
  `Not Found` (`x-render-routing: no-server`) instead of reaching the app.
  Every deploy repeats detection, so set this once and forget it.
- `WEB_CONCURRENCY=2` — Render auto-sets this to the CPU count (1 on
  Standard), and one sync gunicorn worker means a multi-second
  `/api/optimize` call blocks every other visitor. Two processes on one
  CPU timeshare, so cheap calculate requests keep flowing. Memory is not
  a constraint (~60 MB per worker on a 2 GB instance).

## Patch-day flow (unchanged, plus one merge)

1. On `master`, locally: `python scripts/patch_update.py run` (see the
   `/patch-update` skill for the judgment steps)
2. Commit the `data/` + baseline changes as usual
3. Promote to `prod` as above — the host rebuilds and the site is on the new
   patch

## Render setup (one-time)

1. Render dashboard → New → Web Service → connect the GitHub repo
   (private repos work fine)
2. Runtime: **Docker** (it finds the `Dockerfile` automatically);
   Branch: **prod**
3. Instance: **Standard** (2 GB / 1 CPU, ~$25/mo) to start. Set the two
   env vars above before the first deploy. If `/api/optimize` queues up
   under real traffic, move to a multi-CPU instance and raise
   `WEB_CONCURRENCY` to match cores — that endpoint runs a multi-second
   CPU-bound build search and is the only scaling pressure.
4. Optional but recommended: put the domain behind Cloudflare's free tier
   (static asset caching and bot absorption). The application itself applies
   process-shared global budgets to `/api/calculate` and `/api/optimize`.
   The optimizer allows a two-request burst and then one request per 10 seconds;
   that was calibrated against a 1.81 CPU-second max-valid local benchmark to
   keep sustained abuse near 20% of one core. Under abuse, optimizer callers
   receive `429` while the calculator keeps its independent budget.
   Re-run `.venv/Scripts/python scripts/benchmark_security_budget.py` after
   optimizer or fight-engine performance changes and update the measured
   comment/policy together.
5. Set Render's health check path to `/healthz`.

Any Docker host works the same way — Fly.io and Cloud Run need only
"deploy this Dockerfile, listen on `PORT`".

## Testing the production image locally

```bash
docker build -t lol-calc .
docker run --rm -d --name lol-calc -p 8000:8000 lol-calc
# http://localhost:8000 — verify the Update Data button is absent
# and /api/update-data returns 404
docker inspect --format '{{json .State.Health}}' lol-calc
docker stop lol-calc
```

The production image applies Debian security updates, installs the hash-locked
`requirements-runtime.txt`, runs as an unprivileged `app` user, and excludes
scraper/test/lint dependencies. CI rebuilds and scans the image so OS fixes
published after the pinned base-image snapshot are still required before a
release passes. To change a runtime dependency, edit `requirements-runtime.in`
and regenerate:

```bash
uv pip compile requirements-runtime.in --universal --generate-hashes \
  --output-file requirements-runtime.txt
```

## Possible later optimization

- Cache `/api/optimize` results: requests run with `deterministic=True`, so
  an LRU keyed on the request body makes repeated popular configs free.
