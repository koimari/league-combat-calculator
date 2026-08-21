# Database schema (P6)

The Flask app persists product state in PostgreSQL through SQLAlchemy 2.x
(`src/db.py`).  Tables are created automatically on first use
(`Base.metadata.create_all`), so there is no alembic migration step for the
initial schema.  This document is the schema contract.

## Connection

| Setting | Meaning |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL.  `postgres://` and `postgresql://` are normalized to `postgresql+psycopg://` (psycopg3 driver). |
| unset `DATABASE_URL` | Local SQLite fallback at `sqlite:////tmp/lol-calculator-fallback.sqlite3`, so the app works without Postgres during development. |
| `CACHE_TTL_SECONDS` | Result-cache TTL in seconds (default 86400, one day). |

Timestamps are stored as **naive UTC**.  The postgres service in
`docker-compose.yml` pins `TZ`/`PGTZ` to UTC so bound datetimes are never
zone-shifted; API responses serialize timestamps as ISO-8601 with a `Z`
suffix.

## Models

### `builds` — saved builds

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `session_id` | varchar(100) null | anonymous beta-metrics session (P1b); indexed, nullable for pre-P1b rows |
| `champion` | varchar(100) | indexed |
| `level` | integer | |
| `role` | varchar(20) null | |
| `items` | JSON | item-name list |
| `item_options` | JSON | |
| `ability_ranks` | JSON | |
| `champion_options` | JSON | |
| `enemies` | JSON | roster list |
| `allies` | JSON | roster list |
| `fight_params` | JSON | every remaining request key (boots, fight_mode, target stats, rotations, …) so a saved build reconstructs a full `/api/calculate` payload |
| `created_at` | timestamp | |

### `share_links` — public build shares

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `token` | varchar(64) | **unique**, URL-safe, generated server-side |
| `build_id` | integer FK → `builds.id` | `ON DELETE CASCADE`, indexed |
| `slug` | varchar(50) null | optional vanity slug |
| `session_id` | varchar(100) null | anonymous beta-metrics session (P1b); indexed, nullable for pre-P1b rows |
| `views` | integer | incremented atomically per `GET /api/share/<token>` |
| `created_at` | timestamp | |

### `cached_results` — /api/calculate + /api/bis + /api/optimize result cache

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `cache_key` | varchar(64) | **unique**; sha256 of `namespace + "\x00" + canonical request JSON` |
| `payload` | JSON | serialized endpoint response |
| `created_at` | timestamp | |
| `expires_at` | timestamp | `created_at + TTL`; expired rows are lazily deleted on lookup |

Consulted only when `DATABASE_URL` or `REDIS_URL` is configured **and** the
app is not in `TESTING` (Redis holds the entries when `REDIS_URL` is set).
`/api/update-data` calls `cache_delete_all()` after a successful data refresh.

### `validation_feedback` — validation loop observations

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `champion` | varchar(100) | indexed |
| `session_id` | varchar(100) null | anonymous beta-metrics session (P1b); indexed, nullable for pre-P1b rows |
| `loadout` | JSON | |
| `expected` | JSON | |
| `actual` | JSON | |
| `source` | varchar(20) | `manual` \| `combat_log` \| `practice_tool` |
| `matched` | boolean | |
| `delta` | float null | signed observed-minus-predicted total damage; `POST /api/receipts` (the only writer) always populates it, NULL only on legacy rows that predate the receipt endpoint |
| `note` | text null | |
| `created_at` | timestamp | |

Receipt rows store the engine prediction in `expected` (`{"tdd": …,
"sources": {…}}`) and the user's observation in `actual` (same shape), so
`delta` can be re-derived and the signed percentage bias
(`delta / expected.tdd * 100`, see `db.validation_summary`) aggregated per
champion.

### `cache_counters` — shared cache hit/miss counters

Single row (`id = 1`) updated atomically (`INSERT … ON CONFLICT DO UPDATE`)
so every gunicorn worker reports the same totals for `/api/health/deep`.

| Column | Type |
| --- | --- |
| `id` | integer PK |
| `hits` | integer |
| `misses` | integer |
| `updated_at` | timestamp |

### `metrics_events` — anonymous product events (P1b beta metrics)

Anonymous product events recorded by `POST /api/metrics/event`.  No PII: `session_id`
is a random first-party cookie id, never an account identifier.  See
`docs/beta-metrics.md` for the metric definitions.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `event` | varchar(50) | indexed; whitelisted in `src/db.py::METRIC_EVENT_NAMES` (currently `page_view`) |
| `session_id` | varchar(100) null | indexed; the `scryglass_anon` cookie value |
| `took_ms` | integer null | wall-clock duration of the instrumented flow |
| `payload` | JSON | optional bounded extras |
| `created_at` | timestamp | indexed |

## Migration note (P1b)

`create_all` creates the new `metrics_events` table automatically; the
`session_id` columns on `builds` / `share_links` / `validation_feedback`
are backfilled onto pre-existing databases by `db._ensure_metrics_schema`
(guarded `ALTER TABLE ... ADD COLUMN`, idempotent).  There is no alembic
step.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `POST /api/builds` | save a build → `{"build_id": …}` (201) |
| `POST /api/share` | `{"build_id": …, "slug": …}` → `{"token": …, "url": "/api/share/<token>"}` (201) |
| `GET /api/share/<token>` | build payload + `share` block; increments `views` |
| `POST /api/receipts` | record one game-receipt observation; the engine computes `expected`/`matched`/`delta` itself → `{"feedback_id": …, …}` (201) |
| `GET /api/feedback?champion=&source=&limit=` | recent feedback, newest first (`limit` 1–200, default 50; anything else is a 400) |
