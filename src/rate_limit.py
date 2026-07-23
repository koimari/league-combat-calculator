"""Process-shared token buckets for expensive public API routes.

Gunicorn workers are separate processes, so an in-memory limiter gives each
worker an independent budget.  This store keeps the tiny amount of transient
rate state in SQLite, which is shared by every worker in one container.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class TokenBucketStore:
    """Atomically spend tokens from named, process-shared rate buckets."""

    def __init__(self, database: str | Path) -> None:
        self._database = str(database)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS token_buckets (
                    scope TEXT PRIMARY KEY,
                    tokens REAL NOT NULL,
                    updated_at REAL NOT NULL
                ) WITHOUT ROWID
                """)

    def _connect(self) -> sqlite3.Connection:
        """Open one short-lived connection; SQLite coordinates the workers."""
        return sqlite3.connect(self._database, timeout=2.0)

    def consume(
        self,
        scope: str,
        *,
        capacity: int,
        refill_per_second: float,
        now: float | None = None,
    ) -> tuple[bool, float]:
        """Spend one token, returning ``(allowed, retry_after_seconds)``."""
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("Token bucket capacity and refill rate must be positive")

        observed_at = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT tokens, updated_at FROM token_buckets WHERE scope = ?",
                (scope,),
            ).fetchone()

            if row is None:
                tokens = float(capacity)
            else:
                previous_tokens, previous_time = row
                elapsed = max(0.0, observed_at - previous_time)
                tokens = min(
                    float(capacity),
                    previous_tokens + elapsed * refill_per_second,
                )

            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0

            connection.execute(
                """
                INSERT INTO token_buckets (scope, tokens, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    tokens = excluded.tokens,
                    updated_at = excluded.updated_at
                """,
                (scope, tokens, observed_at),
            )

        retry_after = 0.0 if allowed else (1.0 - tokens) / refill_per_second
        return allowed, retry_after
