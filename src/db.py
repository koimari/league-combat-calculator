"""PostgreSQL persistence layer for the LoL damage calculator.

Replaces the Vercel-frontend-only store with a real database behind the
Flask API.  SQLAlchemy 2.x declarative models, psycopg3 driver for
PostgreSQL, and a SQLite fallback that is used only for local development
and tests (set ``DATABASE_URL=sqlite:///...`` explicitly in tests).

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
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_FALLBACK_SQLITE_URL = "sqlite:////tmp/lol-calculator-fallback.sqlite3"
_DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60  # safety net; update-data invalidates
_VALID_FEEDBACK_SOURCES = frozenset({"manual", "combat_log", "practice_tool"})


def _utcnow() -> datetime:
    """Naive UTC now; the storage convention for every timestamp column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    practice tool, used to drive the champion-module validation backlog."""

    __tablename__ = "validation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    champion: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    loadout: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actual: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class StalenessState(Base):
    """One row per patch holding staleness/coverage bookkeeping payloads."""

    __tablename__ = "staleness_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patch: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow
    )


class CacheCounter(Base):
    """Single-row hit/miss counters for /api/cache-status.

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


# ---------------------------------------------------------------------------
# Engine lifecycle
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_engine_lock = threading.Lock()


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
            _session_factory = sessionmaker(
                bind=_engine, expire_on_commit=False, future=True
            )
        return _engine


def reset() -> None:
    """Drop cached engine/session state so the next use re-reads the env.

    Tests call this after pointing ``DATABASE_URL`` at a fresh SQLite file;
    it also releases the previous engine's connection pool.
    """
    global _engine, _session_factory
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None


def is_configured() -> bool:
    """True when ``DATABASE_URL`` is explicitly configured."""
    return bool(os.environ.get("DATABASE_URL", "").strip())


def is_postgres() -> bool:
    """True when the active engine is PostgreSQL (vs the SQLite fallback)."""
    return _resolve_database_url().startswith("postgresql")


def session() -> Any:
    """Open a new ORM session bound to the lazily created engine."""
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def _serialize_datetime(value: datetime | None) -> str | None:
    """ISO-8601 UTC string for API output (storage is naive UTC)."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


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


def save_build(payload: Mapping[str, Any]) -> int:
    """Persist one build payload, returning its id.

    Dedicated columns take the obvious keys; any remaining keys (boots,
    fight_mode, target stats, rotations, ...) are stored losslessly in
    ``fight_params`` so the original request can be reconstructed.
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


def get_build(build_id: int) -> dict[str, Any] | None:
    """Load one build as a JSON-safe dict, or None when missing."""
    with session() as db_session:
        build = db_session.get(Build, int(build_id))
        if build is None:
            return None
        return _build_to_dict(build)


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------


def _generate_token() -> str:
    """URL-safe unique token (22 characters, ~128 bits of entropy)."""
    return secrets.token_urlsafe(16)


def create_share_link(build_id: int, slug: str | None = None) -> dict[str, Any]:
    """Create a share link for an existing build; raises KeyError when the
    build is missing."""
    with session() as db_session:
        build = db_session.get(Build, int(build_id))
        if build is None:
            raise KeyError(build_id)
        for _attempt in range(3):
            token = _generate_token()
            share = ShareLink(token=token, build_id=build.id, slug=slug or None)
            db_session.add(share)
            try:
                db_session.commit()
                return {
                    "token": share.token,
                    "build_id": share.build_id,
                    "slug": share.slug,
                    "url": f"/api/share/{share.token}",
                }
            except SQLAlchemyError:
                db_session.rollback()  # token collision; try another one
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
    note: str | None = None,
) -> int:
    """Persist one validation observation, returning its id."""
    if source not in _VALID_FEEDBACK_SOURCES:
        raise ValueError(f"source must be one of {sorted(_VALID_FEEDBACK_SOURCES)}")
    with session() as db_session:
        feedback = ValidationFeedback(
            champion=champion,
            loadout=dict(loadout or {}),
            expected=dict(expected or {}),
            actual=dict(actual or {}),
            source=source,
            matched=bool(matched),
            note=note,
        )
        db_session.add(feedback)
        db_session.commit()
        return feedback.id


def list_feedback(
    champion: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent feedback, newest first, optionally filtered."""
    statement = select(ValidationFeedback).order_by(ValidationFeedback.id.desc())
    if champion:
        statement = statement.where(ValidationFeedback.champion == champion)
    if source:
        if source not in _VALID_FEEDBACK_SOURCES:
            raise ValueError(f"source must be one of {sorted(_VALID_FEEDBACK_SOURCES)}")
        statement = statement.where(ValidationFeedback.source == source)
    statement = statement.limit(max(1, min(int(limit), 200)))
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
                "note": row.note,
                "created_at": _serialize_datetime(row.created_at),
            }
            for row in rows
        ]


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
    """Return a non-expired cached payload, or None (recording the miss)."""
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
    """Store (or refresh) a cached payload with the configured TTL."""
    ttl = int(ttl_seconds) if ttl_seconds is not None else cache_ttl_seconds()
    if ttl <= 0:
        return
    now = _utcnow()
    with session() as db_session:
        row = db_session.execute(
            select(CachedResult).where(CachedResult.cache_key == cache_key)
        ).scalar_one_or_none()
        if row is None:
            db_session.add(
                CachedResult(
                    cache_key=cache_key,
                    payload=dict(payload),
                    created_at=now,
                    expires_at=now + timedelta(seconds=ttl),
                )
            )
        else:
            row.payload = dict(payload)
            row.created_at = now
            row.expires_at = now + timedelta(seconds=ttl)
        db_session.commit()


def cache_delete_all() -> int:
    """Drop every cached result (used on data updates); returns row count."""
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
# Staleness state
# ---------------------------------------------------------------------------


def staleness_set(patch: str, payload: Mapping[str, Any]) -> None:
    """Upsert the staleness/coverage payload for one patch."""
    with session() as db_session:
        row = db_session.execute(
            select(StalenessState).where(StalenessState.patch == patch)
        ).scalar_one_or_none()
        if row is None:
            db_session.add(
                StalenessState(patch=patch, payload=dict(payload), checked_at=_utcnow())
            )
        else:
            row.payload = dict(payload)
            row.checked_at = _utcnow()
        db_session.commit()


def staleness_get(patch: str) -> dict[str, Any] | None:
    """Load one patch's staleness payload, or None."""
    with session() as db_session:
        row = db_session.execute(
            select(StalenessState).where(StalenessState.patch == patch)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "patch": row.patch,
            "payload": row.payload or {},
            "checked_at": _serialize_datetime(row.checked_at),
        }
