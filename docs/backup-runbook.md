# Scryglass Database Backup Runbook (P0b)

How to back up and restore the Scryglass persistence layer: the managed
Postgres database (builds, share links, validation feedback, staleness
state), the SQLite development fallback, and the Redis result cache.

The operator entry point is `scripts/backup_db.py`; this document covers
what it does, why, and how to restore from the artifacts it produces.

## What needs backing up (and why)

| Store | Contents | Backup role |
| --- | --- | --- |
| Postgres (`DATABASE_URL`) | builds, share links, feedback, staleness state | **Primary** — user data. Must be backed up. |
| SQLite fallback (no `DATABASE_URL`) | same schema, local file `/tmp/lol-calculator-fallback.sqlite3` | Dev-only; back up before destructive local work. |
| Redis (`REDIS_URL`) | calculation-result cache (`scryglass:cache:entry:*`) | **Derived** — rebuildable by re-running calculations. Snapshots are a convenience, never the DR mechanism. |

## 1. Logical backup with `backup_db.py`

```bash
python scripts/backup_db.py                       # pg_dump or sqlite3 .backup
python scripts/backup_db.py --out-dir backups     # default already: backups/
python scripts/backup_db.py --retention 14        # keep 14 newest backups
python scripts/backup_db.py --include-redis       # also SAVE the local Redis
python scripts/backup_db.py --dry-run             # print the plan, change nothing
```

Behavior by backend:

- **Postgres** (`DATABASE_URL` starts with `postgres://`/`postgresql://`):
  `pg_dump --no-owner --no-privileges --file=backups/scryglass-db-<ts>.sql <url>`.
  Plain-SQL logical format — portable across providers and restoreable with
  `psql` or `pg_restore`. It does not need database downtime.
- **SQLite** (no `DATABASE_URL`, or a `sqlite:///` URL): the `sqlite3`
  `.backup` command, which is the *online* backup mechanism — safe against a
  live database in WAL mode (the app runs `PRAGMA journal_mode=WAL`).
  Backing up the file with `cp` while the app is writing can produce a
  corrupt copy; always use `.backup`.
- **Redis** (`--include-redis` with `REDIS_URL` set): runs
  `redis-cli -u <url> SAVE` so the local server writes its RDB snapshot.
  Managed providers (Upstash, etc.) run their own snapshot schedule — check
  their console instead of issuing SAVE yourself. Note printed by the script:
  the result cache is derived data; losing it costs recompute time, not data.

Retention: `--retention N` (default 7) keeps the `N` newest
`scryglass-db-*` files in the output directory and deletes older ones.
`--dry-run` prints the full plan (commands + deletion list) without touching
anything — use it in cron smoke tests and in CI.

### Scheduled backups (cron)

```cron
# nightly at 02:30 UTC, keep 14 backups
30 2 * * *  cd /path/to/repo && /path/to/.venv/bin/python scripts/backup_db.py --retention 14 >> backups/backup.log 2>&1
```

For managed Postgres, prefer the provider's point-in-time recovery (PITR) as
the first line of defense and the logical `pg_dump` as the portable, cross-
provider artifact:

- **Neon**: automatic PITR (branches/timelines) — logical dumps add portability.
- **Supabase**: daily backups on paid plans plus `pg_dump` for restores elsewhere.
- **RDS**: automated snapshots (PITR) — `pg_dump` for cross-region/offsite copies.

Keep at least one backup **off the same host** (object storage, another
region, a local machine) — a provider outage should not take the backups with it.

## 2. Restore

### Postgres (plain SQL dump)

```bash
# target a fresh database
createdb "$DATABASE_URL"        # or create via the provider console
psql "$DATABASE_URL" -f backups/scryglass-db-20260806-023000.sql
```

The app creates its tables automatically on first use
(`Base.metadata.create_all`), so restoring into an empty database is safe;
into an existing one the dump re-creates rows idempotently enough for a
rollback (additive data only — the app never drops columns).

### SQLite

```bash
sqlite3 /tmp/lol-calculator-fallback.sqlite3 ".restore backups/scryglass-db-20260806-023000.sqlite"
# or restore to a fresh file and point DATABASE_URL at it:
sqlite3 /tmp/restored.sqlite3 ".restore backups/scryglass-db-20260806-023000.sqlite"
DATABASE_URL=sqlite:////tmp/restored.sqlite3  # for the app process
```

### Redis (result cache)

- **Missing snapshot is fine**: restart with an empty cache and let requests
  repopulate it. The 24h TTL self-heals.
- **Local server with a snapshot**: after restoring the RDB, restart Redis;
  the cache entries reappear with their original TTLs.
- **Managed Redis**: provider-managed snapshots/`SAVE` only where the
  provider exposes it (Upstash: on-demand backups in the console).

## 3. DR pattern for Redis: read-only replica

For a production closed beta the recommended pattern is a **read-only
replica** rather than snapshot-and-restore:

- Point the app's `REDIS_URL` at a replica endpoint; replica reads are
  eventually consistent with the primary.
- Writes (cache `SET`, counters) still target the primary; a replica failure
  degrades to cache misses (fresh compute) without data loss.
- `backup_db.py --include-redis` is for self-hosted single-node setups; the
  replica is what makes a primary outage non-urgent.

## 4. Restore drills

- Run `scripts/backup_db.py --dry-run` after every dependency/environment
  change to confirm the plan still resolves to the intended backend.
- Monthly: restore the newest dump into a scratch database and boot the app
  against it (`DATABASE_URL=... python -c "from src.app import app"` plus a
  `/api/health/deep` call) — a backup that has never been restored is a hope,
  not a backup.
