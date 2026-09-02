"""PostgreSQL persistence layer for the LoL damage calculator.

Replaces the Vercel-frontend-only store with a real database behind the
Flask API.  SQLAlchemy 2.x declarative models, psycopg3 driver for
PostgreSQL, and a SQLite fallback that is used only for local development
and tests (set ``DATABASE_URL=sqlite:///...`` explicitly in tests).

Result caching (P0a)
--------------------
The result cache uses Redis when ``REDIS_URL`` is set (managed deployments,
e.g. Upstash), otherwise the SQLAlchemy ``CachedResult`` table (Postgres in
production, SQLite in dev/tests).  The cache helpers ``cache_get``,
``cache_set``, ``cache_delete_all`` and ``cache_stats`` dispatch to the
configured backend behind one interface; the ``redis`` package is imported
lazily so SQLite-only installs and the test suite never need it.  Persistent
records (builds, share links, feedback, staleness) always live in the
SQLAlchemy database named by ``DATABASE_URL``.

Connection strategy
-------------------
* ``DATABASE_URL`` is read from the environment at first use (lazy engine
  creation, so importing this module never touches the network or disk).
* ``postgres://`` and ``postgresql://`` URLs are normalized to
  ``postgresql+psycopg://`` so the psycopg3 driver is always used for
  PostgreSQL.
* With no ``DATABASE_URL`` set, a local SQLite file under the system temp
  directory is used.  This fallback exists only so the app works out of the
  box locally without Postgres; production always configures ``DATABASE_URL``.
* Tables are created automatically on first use (``create_all``), so no
  alembic migration step is required.  Schema documentation lives in
  ``docs/database-schema.md``.

All timestamps are stored as naive UTC.  On PostgreSQL the session timezone
is pinned to UTC by deployment configuration (see docker-compose.yml); the
helpers here never depend on the server converting zones.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_FALLBACK_SQLITE_URL = "sqlite:////tmp/lol-calculator-fallback.sqlite3"
_DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60  # safety net; update-data invalidates
_VALID_FEEDBACK_SOURCES = frozenset({"manual", "combat_log", "practice_tool"})


def _utcnow() -> datetime:
    """Naive UTC now; the storage convention for every timestamp column."""
    return datetime.now(UTC).replace(tzinfo=None)


def _resolve_database_url() -> str:
    """Return the engine URL, normalizing PostgreSQL URLs to psycopg3."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return _FALLBACK_SQLITE_URL
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def cache_ttl_seconds() -> int:
    """TTL for cached calculation results, overridable via env."""
    raw = os.environ.get("CACHE_TTL_SECONDS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _DEFAULT_CACHE_TTL_SECONDS


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base shared by every persistence model."""


class Build(Base):
    """One saved build scenario, mirroring the /api/calculate request shape."""

    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Anonymous session id (see docs/beta-metrics.md) attributed at save time.
    # Nullable: rows saved before P1b instrumentation have no session.
    session_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    champion: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    item_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ability_ranks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    champion_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enemies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    allies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fight_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class ShareLink(Base):
    """Public share link pointing at a saved build."""

    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    build_id: Mapped[int] = mapped_column(
        ForeignKey("builds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Anonymous session id of the sharer (see docs/beta-metrics.md).
    session_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class CachedResult(Base):
    """Serialized /api/calculate and /api/bis responses, keyed by request."""

    __tablename__ = "cached_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)


class ValidationFeedback(Base):
    """A validation observation from the manual review loop, combat log, or
    practice tool, driving the champion-module validation backlog."""

    __tablename__ = "validation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    champion: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Anonymous session id of the observer (see docs/beta-metrics.md).
    session_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    loadout: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actual: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Signed observed-minus-predicted total damage delta.  NULL for manual
    # P6-style feedback rows that carry no engine prediction; the receipt
    # endpoints always populate it so systematic bias can be aggregated.
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class CacheCounter(Base):
    """Single-row hit/miss counters for /api/health/deep (checks.cache).

    Kept in the database rather than in memory so every gunicorn worker
    reports the same totals.
    """

    __tablename__ = "cache_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class MetricsEvent(Base):
    """One anonymous, session-scoped product event (P1b beta metrics).

    No PII by construction: ``session_id`` is a random first-party cookie
    id minted by the app, never an account name or email.  ``took_ms`` is
    the wall-clock duration of the instrumented flow, when it has one.
    """

    __tablename__ = "metrics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    took_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow, index=True
    )


# ---------------------------------------------------------------------------
# Engine lifecycle
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_engine_lock = threading.Lock()


def _ensure_metrics_schema(engine: Engine) -> None:
    """Idempotently backfill P1b columns onto pre-existing tables.

    ``create_all`` only creates missing tables; a database created before
    the metrics work (the live beta Postgres) already has ``builds``,
    ``share_links`` and ``validation_feedback`` without ``session_id``.
    This runs one guarded ``ALTER TABLE ... ADD COLUMN`` per missing
    column (no alembic migration step exists in this project).  Fresh
    databases get the columns from the model DDL and this is a no-op.
    """
    for table_name, column_name in (
        ("builds", "session_id"),
        ("share_links", "session_id"),
        ("validation_feedback", "session_id"),
    ):
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name in existing:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(100)")
            )


def get_engine() -> Engine:
    """Create (once) and return the SQLAlchemy engine, creating tables."""
    global _engine, _session_factory
    with _engine_lock:
        if _engine is None:
            url = _resolve_database_url()
            kwargs: dict[str, Any] = {}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False}
            else:
                kwargs["pool_pre_ping"] = True
            _engine = create_engine(url, future=True, **kwargs)
            Base.metadata.create_all(_engine)
            _ensure_metrics_schema(_engine)
            _session_factory = sessionmaker(
                bind=_engine, expire_on_commit=False, future=True
            )
        return _engine


def reset() -> None:
    """Drop cached engine/session state so the next use re-reads the env.

    Tests call this after pointing ``DATABASE_URL`` at a fresh SQLite file;
    it also releases the previous engine's connection pool and drops any
    cached Redis client so a changed ``REDIS_URL`` takes effect.
    """
    global _engine, _session_factory, _redis_state
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
        _redis_state = {"client": None, "error_type": None}


def is_configured() -> bool:
    """True when ``DATABASE_URL`` is explicitly configured."""
    return bool(os.environ.get("DATABASE_URL", "").strip())


def is_postgres() -> bool:
    """True when the active engine is PostgreSQL (vs the SQLite fallback)."""
    return _resolve_database_url().startswith("postgresql")


def session() -> Session:
    """Open a new ORM session bound to the lazily created engine."""
    get_engine()
    assert _session_factory is not None
    return _session_factory()


# ---------------------------------------------------------------------------
# Redis result cache
# ---------------------------------------------------------------------------

# Result-cache entries live under this prefix; the hit/miss counter hash sits
# outside it so ``cache_delete_all`` never wipes the counters.
_REDIS_ENTRY_PREFIX = "scryglass:cache:entry:"
_REDIS_COUNTER_KEY = "scryglass:cache:counters"

# Lazy singleton state: the redis package is imported only when REDIS_URL is
# actually configured, so SQLite-only installs and the test suite (which
# mocks the client) never need it installed.
_redis_state: dict[str, Any] = {"client": None, "error_type": None}


class CacheUnavailable(RuntimeError):
    """Raised when the configured result-cache backend cannot be reached."""


def redis_url() -> str | None:
    """Return the configured ``REDIS_URL``, or None when unset."""
    url = os.environ.get("REDIS_URL", "").strip()
    return url or None


def redis_configured() -> bool:
    """True when ``REDIS_URL`` is explicitly configured."""
    return redis_url() is not None


def cache_backend() -> str:
    """Name of the active result-cache backend: redis, postgresql, sqlite."""
    if redis_configured():
        return "redis"
    return "postgresql" if is_postgres() else "sqlite"


def _redis_client() -> Any:
    """Return the lazily created Redis client for ``REDIS_URL``."""
    if _redis_state["client"] is None:
        try:
            # pylint: disable-next=import-outside-toplevel  # deliberate, see docstring
            import redis as redis_lib
        except ImportError as exc:
            raise RuntimeError(
                "REDIS_URL is set but the redis package is not installed"
            ) from exc
        _redis_state["error_type"] = redis_lib.exceptions.RedisError
        _redis_state["client"] = redis_lib.Redis.from_url(
            redis_url(), decode_responses=True
        )
    return _redis_state["client"]


def _redis_call(method: str, *args: Any, **kwargs: Any) -> Any:
    """Run one Redis command, normalizing backend failures to a clean error.

    The cache is an availability optimization, but it must never silently
    serve stale data: any backend failure surfaces as ``CacheUnavailable``
    so the caller can fail closed instead of guessing.
    """
    client = _redis_client()
    try:
        return getattr(client, method)(*args, **kwargs)
    # pylint: disable-next=broad-exception-caught
    except Exception as exc:
        raise CacheUnavailable(f"Redis cache unavailable: {exc}") from exc


def _redis_entry_key(cache_key: str) -> str:
    """Full Redis key for one cache entry."""
    return _REDIS_ENTRY_PREFIX + cache_key


def _redis_record_counter(*, hits: bool) -> None:
    """Atomically bump the shared hit/miss counter hash."""
    _redis_call("hincrby", _REDIS_COUNTER_KEY, "hits" if hits else "misses", 1)


def _serialize_datetime(value: datetime | None) -> str | None:
    """ISO-8601 UTC string for API output (storage is naive UTC)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------

_BUILD_COLUMNS = (
    "champion",
    "level",
    "role",
    "items",
    "item_options",
    "ability_ranks",
    "champion_options",
    "enemies",
    "allies",
    "fight_params",
)

# Keys that map onto dedicated Build columns; everything else in a saved
# calculate-style payload is preserved inside ``fight_params``.
_BUILD_TOP_LEVEL_KEYS = frozenset(
    {
        "champion",
        "level",
        "role",
        "items",
        "item_options",
        "ability_ranks",
        "champion_options",
        "enemies",
        "allies",
    }
)


def save_build(payload: Mapping[str, Any], session_id: str | None = None) -> int:
    """Persist one build payload, returning its id.

    Dedicated columns take the obvious keys; any remaining keys (boots,
    fight_mode, target stats, rotations, ...) are stored losslessly in
    ``fight_params`` so the original request can be reconstructed.
    ``session_id`` is the anonymous beta-metrics session (see
    docs/beta-metrics.md); it never identifies the account.
    """
    values: dict[str, Any] = {}
    for key in _BUILD_COLUMNS:
        if key == "level":
            values[key] = int(payload.get("level", 1))
        elif key in {"items", "enemies", "allies"}:
            values[key] = list(payload.get(key, []) or [])
        elif key in {
            "item_options",
            "ability_ranks",
            "champion_options",
            "fight_params",
        }:
            values[key] = dict(payload.get(key, {}) or {})
        else:
            values[key] = payload.get(key)
    remainder = {
        key: value for key, value in payload.items() if key not in _BUILD_TOP_LEVEL_KEYS
    }
    values["fight_params"].update(remainder)
    values["session_id"] = session_id
    with session() as db_session:
        build = Build(**values)
        db_session.add(build)
        db_session.commit()
        return build.id


def _build_to_dict(build: Build) -> dict[str, Any]:
    """JSON-safe view of a Build row, plus the reconstructed request."""
    request = {key: getattr(build, key) for key in _BUILD_TOP_LEVEL_KEYS}
    request.update(build.fight_params or {})
    return {
        "build_id": build.id,
        "champion": build.champion,
        "level": build.level,
        "role": build.role,
        "items": build.items or [],
        "item_options": build.item_options or {},
        "ability_ranks": build.ability_ranks or {},
        "champion_options": build.champion_options or {},
        "enemies": build.enemies or [],
        "allies": build.allies or [],
        "fight_params": build.fight_params or {},
        "created_at": _serialize_datetime(build.created_at),
        "request": request,
    }


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------


def _generate_token() -> str:
    """URL-safe unique token (22 characters, ~128 bits of entropy)."""
    return secrets.token_urlsafe(16)


def create_share_link(
    build_id: int, slug: str | None = None, session_id: str | None = None
) -> dict[str, Any]:
    """Create a share link for an existing build; raises KeyError when the
    build is missing.  ``session_id`` is the sharer's anonymous beta-metrics
    session (see docs/beta-metrics.md)."""
    with session() as db_session:
        build = db_session.get(Build, int(build_id))
        if build is None:
            raise KeyError(build_id)
        for _attempt in range(3):
            token = _generate_token()
            share = ShareLink(
                token=token,
                build_id=build.id,
                slug=slug or None,
                session_id=session_id,
            )
            db_session.add(share)
            try:
                db_session.commit()
            except SQLAlchemyError:
                db_session.rollback()  # token collision; try another one
                continue
            return {
                "token": share.token,
                "build_id": share.build_id,
                "slug": share.slug,
                "url": f"/api/share/{share.token}",
            }
        raise SQLAlchemyError("could not allocate a unique share token")


def get_share_link(
    token: str, *, increment_views: bool = False
) -> dict[str, Any] | None:
    """Resolve a share token to its build payload (optionally +1 view)."""
    with session() as db_session:
        share = db_session.execute(
            select(ShareLink).where(ShareLink.token == token)
        ).scalar_one_or_none()
        if share is None:
            return None
        if increment_views:
            db_session.execute(
                update(ShareLink)
                .where(ShareLink.id == share.id)
                .values(views=ShareLink.views + 1)
            )
            db_session.commit()
            db_session.refresh(share)
        build = db_session.get(Build, share.build_id)
        if build is None:
            return None
        payload = _build_to_dict(build)
        payload.update(
            {
                "share": {
                    "token": share.token,
                    "slug": share.slug,
                    "views": share.views,
                    "created_at": _serialize_datetime(share.created_at),
                }
            }
        )
        return payload


# ---------------------------------------------------------------------------
# Validation feedback
# ---------------------------------------------------------------------------


def add_feedback(
    *,
    champion: str,
    loadout: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
    actual: Mapping[str, Any] | None = None,
    source: str = "manual",
    matched: bool = False,
    delta: float | None = None,
    note: str | None = None,
    session_id: str | None = None,
) -> int:
    """Persist one validation observation, returning its id.

    ``session_id`` is the observer's anonymous beta-metrics session (see
    docs/beta-metrics.md); it never identifies the account.
    """
    if source not in _VALID_FEEDBACK_SOURCES:
        raise ValueError(f"source must be one of {sorted(_VALID_FEEDBACK_SOURCES)}")
    if delta is not None:
        delta = float(delta)
        if not math.isfinite(delta):
            raise ValueError("delta must be finite")
    with session() as db_session:
        feedback = ValidationFeedback(
            champion=champion,
            loadout=dict(loadout or {}),
            expected=dict(expected or {}),
            actual=dict(actual or {}),
            source=source,
            matched=bool(matched),
            delta=delta,
            note=note,
            session_id=session_id,
        )
        db_session.add(feedback)
        db_session.commit()
        return feedback.id


def list_feedback(
    champion: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent feedback, newest first, optionally filtered.

    ``limit`` is bounded at the API boundary (``app._FEEDBACK_PAGE_MAX``).
    """
    statement = select(ValidationFeedback).order_by(ValidationFeedback.id.desc())
    if champion:
        statement = statement.where(ValidationFeedback.champion == champion)
    if source:
        if source not in _VALID_FEEDBACK_SOURCES:
            raise ValueError(f"source must be one of {sorted(_VALID_FEEDBACK_SOURCES)}")
        statement = statement.where(ValidationFeedback.source == source)
    statement = statement.limit(limit)
    with session() as db_session:
        rows = db_session.execute(statement).scalars().all()
        return [
            {
                "feedback_id": row.id,
                "champion": row.champion,
                "loadout": row.loadout or {},
                "expected": row.expected or {},
                "actual": row.actual or {},
                "source": row.source,
                "matched": row.matched,
                "delta": row.delta,
                "note": row.note,
                "created_at": _serialize_datetime(row.created_at),
            }
            for row in rows
        ]


def validation_summary(
    champion: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Aggregate validation receipts into per-champion bias statistics.

    Bias is the signed mean percentage error of the receipt deltas
    (``(observed - predicted) / predicted * 100``); only rows that carry a
    delta AND a numeric predicted total in ``expected["tdd"]`` contribute.
    A champion is flagged when at least 5 receipts show a bias beyond
    +-15%.  The counts include every feedback row for the champion, so the
    flag never depends on the API page size.
    """
    statement = select(ValidationFeedback)
    if champion:
        statement = statement.where(ValidationFeedback.champion == champion)
    with session() as db_session:
        rows = db_session.execute(statement).scalars().all()

    by_champion: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = by_champion.setdefault(
            row.champion,
            {
                "champion": row.champion,
                "count": 0,
                "receipts": 0,
                "bias": None,
                "n": 0,
                "flagged": False,
            },
        )
        entry["count"] += 1
        if row.delta is None:
            continue
        entry["receipts"] += 1
        expected_tdd = None
        if isinstance(row.expected, dict):
            raw = row.expected.get("tdd")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                expected_tdd = float(raw)
        if expected_tdd is None or expected_tdd <= 0:
            continue
        entry["n"] += 1
        entry.setdefault("_bias_sum", 0.0)
        entry["_bias_sum"] += row.delta / expected_tdd * 100.0

    summary: list[dict[str, Any]] = []
    for entry in by_champion.values():
        if entry["n"]:
            entry["bias"] = round(entry.pop("_bias_sum") / entry["n"], 2)
            entry["flagged"] = entry["n"] >= 5 and abs(entry["bias"]) > 15.0
        summary.append(entry)
    summary.sort(key=lambda entry: (-entry["flagged"], entry["champion"]))
    return summary[:limit]


# ---------------------------------------------------------------------------
# Result cache
# ---------------------------------------------------------------------------


def stable_cache_key(namespace: str, payload: Mapping[str, Any]) -> str:
    """Deterministic 64-char key for one request payload.

    ``namespace`` separates endpoint families (calculate vs bis) so two
    endpoints can never collide on the same body.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(namespace.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical)
    return digest.hexdigest()


def _record_cache_counter(db_session: Any, *, hits: bool) -> None:
    """Atomically bump the shared hit/miss counter row (id == 1).

    The first call seeds the row with the correct base values; every later
    call increments exactly one column via ``ON CONFLICT DO UPDATE``.
    """
    insert_cls = postgres_insert if is_postgres() else sqlite_insert
    statement = (
        insert_cls(CacheCounter)
        .values(id=1, hits=1 if hits else 0, misses=0 if hits else 1)
        .on_conflict_do_update(
            index_elements=[CacheCounter.id],
            set_={
                "hits": CacheCounter.hits + (1 if hits else 0),
                "misses": CacheCounter.misses + (1 if not hits else 0),
            },
        )
    )
    db_session.execute(statement)


def cache_get(cache_key: str) -> dict[str, Any] | None:
    """Return a non-expired cached payload, or None (recording the miss).

    Dispatches to Redis when ``REDIS_URL`` is configured; expiry is enforced
    by the Redis TTL, so a missing key is simply a miss.
    """
    if redis_configured():
        raw = _redis_call("get", _redis_entry_key(cache_key))
        if raw is None:
            _redis_record_counter(hits=False)
            return None
        _redis_record_counter(hits=True)
        return json.loads(raw)
    now = _utcnow()
    with session() as db_session:
        row = db_session.execute(
            select(CachedResult).where(CachedResult.cache_key == cache_key)
        ).scalar_one_or_none()
        if row is None:
            _record_cache_counter(db_session, hits=False)
            db_session.commit()
            return None
        if row.expires_at <= now:
            db_session.delete(row)
            _record_cache_counter(db_session, hits=False)
            db_session.commit()
            return None
        _record_cache_counter(db_session, hits=True)
        db_session.commit()
        return dict(row.payload)


def cache_set(
    cache_key: str, payload: Mapping[str, Any], ttl_seconds: int | None = None
) -> None:
    """Store (or refresh) a cached payload with the configured TTL.

    One ``ON CONFLICT DO UPDATE`` decides the row, so two requests computing
    the same ``cache_key`` concurrently both store their result instead of the
    loser of a read-then-insert breaking the unique index out of ``commit()``.
    """
    ttl = int(ttl_seconds) if ttl_seconds is not None else cache_ttl_seconds()
    if ttl <= 0:
        return
    if redis_configured():
        _redis_call("set", _redis_entry_key(cache_key), json.dumps(payload), ex=ttl)
        return
    now = _utcnow()
    entry = {
        "payload": dict(payload),
        "created_at": now,
        "expires_at": now + timedelta(seconds=ttl),
    }
    insert_cls = postgres_insert if is_postgres() else sqlite_insert
    statement = (
        insert_cls(CachedResult)
        .values(cache_key=cache_key, **entry)
        .on_conflict_do_update(index_elements=[CachedResult.cache_key], set_=entry)
    )
    with session() as db_session:
        db_session.execute(statement)
        db_session.commit()


def cache_delete_all() -> int:
    """Drop every cached result (used on data updates); returns row count."""
    if redis_configured():
        keys = list(_redis_call("scan_iter", match=_REDIS_ENTRY_PREFIX + "*"))
        if keys:
            _redis_call("delete", *keys)
        return len(keys)
    with session() as db_session:
        rows = db_session.execute(select(CachedResult.id)).scalars().all()
        count = len(rows)
        if count:
            db_session.execute(
                CachedResult.__table__.delete().where(CachedResult.id.in_(rows))
            )
            db_session.commit()
        return count


def cache_stats() -> dict[str, Any]:
    """Hit/miss counters plus live (non-expired) entry count."""
    if redis_configured():
        counters = _redis_call("hgetall", _REDIS_COUNTER_KEY) or {}
        hits = int(counters.get("hits") or 0)
        misses = int(counters.get("misses") or 0)
        live = sum(1 for _ in _redis_call("scan_iter", match=_REDIS_ENTRY_PREFIX + "*"))
        return {"hits": hits, "misses": misses, "cached_entries": live}
    now = _utcnow()
    with session() as db_session:
        row = db_session.get(CacheCounter, 1)
        live = (
            db_session.execute(
                select(CachedResult).where(CachedResult.expires_at > now)
            )
            .scalars()
            .all()
        )
        return {
            "hits": row.hits if row else 0,
            "misses": row.misses if row else 0,
            "cached_entries": len(live),
        }


# ---------------------------------------------------------------------------
# Beta metrics events (P1b)
# ---------------------------------------------------------------------------

# The one home of the event whitelist and the ``took_ms`` bound: the API
# route imports both to reject bad input before spending a rate-limit token,
# and this helper checks them again so direct callers (tests, scripts)
# cannot write arbitrary names either.
METRIC_EVENT_NAMES = frozenset({"page_view"})
METRIC_EVENT_MAX_TOOK_MS = 3_600_000


def record_metric_event(
    *,
    event: str,
    session_id: str,
    took_ms: int | None = None,
    payload: Mapping[str, Any] | None = None,
) -> int:
    """Persist one anonymous product event, returning its id.

    ``session_id`` is the app-minted anonymous session id (a random cookie
    id, never an account name).  ``took_ms`` is the wall-clock duration of
    the instrumented flow; the whitelist and bounds mirror the API route so
    direct callers get the same rejections.
    """
    if event not in METRIC_EVENT_NAMES:
        raise ValueError(f"event must be one of {sorted(METRIC_EVENT_NAMES)}")
    if not session_id or not isinstance(session_id, str) or len(session_id) > 100:
        raise ValueError("session_id must be a non-empty string of at most 100 chars")
    if took_ms is not None:
        took_ms = int(took_ms)
        if took_ms < 0 or took_ms > METRIC_EVENT_MAX_TOOK_MS:
            raise ValueError(
                f"took_ms must be between 0 and {METRIC_EVENT_MAX_TOOK_MS}"
            )
    with session() as db_session:
        row = MetricsEvent(
            event=event,
            session_id=session_id,
            took_ms=took_ms,
            payload=dict(payload or {}),
        )
        db_session.add(row)
        db_session.commit()
        return row.id
