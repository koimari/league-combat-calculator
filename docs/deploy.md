# Deploying the calculator

The app is a stateless Flask service: no database, no logins, and the entire
data layer is the git-tracked `data/` cache (~10 MB of JSON). The server never
writes anything at runtime — patch-day updates happen locally and reach the
site as ordinary commits. That makes deployment "build the Docker image, run
it" with nothing to migrate or back up.

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
`/api/update-data` wiki re-scrape endpoint. **Never set it on a deployment** —
the endpoint is unauthenticated, hammers the wiki from the server's IP, and
with multiple gunicorn workers would refresh only one worker's memory. Unset,
the endpoint 404s and the frontend hides the button.

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
   (static asset caching, bot absorption, rate limiting for `/api/optimize`).

Any Docker host works the same way — Fly.io and Cloud Run need only
"deploy this Dockerfile, listen on `PORT`".

## Testing the production image locally

```bash
docker build -t lol-calc .
docker run --rm -p 8000:8000 lol-calc
# http://localhost:8000 — verify the Update Data button is absent
# and /api/update-data returns 404
```

## Possible later optimizations (not needed at launch)

- Slim the image: the Dockerfile installs the full `requirements.txt`,
  including scraper/test/lint deps the server never imports. A runtime-only
  manifest would shave ~80 MB off the image if build time ever matters.
- Cache `/api/optimize` results: requests run with `deterministic=True`, so
  an LRU keyed on the request body makes repeated popular configs free.
