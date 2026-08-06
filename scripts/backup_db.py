#!/usr/bin/env python3
"""Back up the Scryglass persistence layer (Postgres / SQLite) and optionally
snapshot the Redis result cache.

Usage
-----
    python scripts/backup_db.py [--out-dir backups] [--retention 7]
                               [--include-redis] [--dry-run]

- PostgreSQL (``DATABASE_URL`` starting with ``postgres://`` or
  ``postgresql://``): ``pg_dump`` a logical, plain-SQL backup.
- SQLite (``DATABASE_URL`` unset or a ``sqlite:///`` URL): the ``sqlite3
  .backup`` online backup command (safe against a live WAL-mode database).
- Redis (``REDIS_URL`` set and ``--include-redis``): issue ``SAVE`` so the
  provider/server writes its RDB snapshot. Managed Redis (Upstash etc.)
  owns its own snapshots; the result cache is a *derived* cache that can be
  rebuilt by re-running calculations, so RDB backups are an availability
  nicety, never the DR mechanism. See docs/backup-runbook.md for the
  read-only-replica note.

``--retention N`` keeps the N newest ``scryglass-db-*`` files in the output
directory and deletes older ones. ``--dry-run`` prints the plan without
executing anything.

The script is importable: ``build_commands`` and ``apply_retention`` are pure
helpers used by both the CLI and the test suite.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import os
import re
import subprocess
import sys
from pathlib import Path

BACKUP_PREFIX = "scryglass-db"
_FALLBACK_SQLITE_PATH = "/tmp/lol-calculator-fallback.sqlite3"
# Mirrors db.py's fallback when DATABASE_URL is unset.
_TIMESTAMP_PATTERN = re.compile(r"^" + BACKUP_PREFIX + r"-(\d{8}-\d{6})\.(sql|sqlite)$")


def _resolve_target(database_url: str | None) -> tuple[str, str]:
    """Return ``(kind, source)`` for the active persistence layer.

    kind is ``postgres`` (the URL itself) or ``sqlite`` (a filesystem path).
    """
    url = (database_url or "").strip()
    if not url:
        return "sqlite", _FALLBACK_SQLITE_PATH
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return "postgres", url
    if url.startswith("sqlite:///"):
        return "sqlite", url[len("sqlite:///") :]
    raise ValueError(f"Unsupported DATABASE_URL scheme: {url.split(':', 1)[0]}")


def build_commands(
    database_url: str | None,
    out_dir: str | Path,
    *,
    include_redis: bool = False,
    redis_url: str | None = None,
    timestamp: str | None = None,
) -> list[str]:
    """Return the shell commands for one backup run (no execution).

    ``timestamp`` defaults to local ``YYYYMMDD-HHMMSS``; Redis SAVE is only
    included when ``include_redis`` is true AND ``redis_url`` is configured.
    """
    stamp = timestamp or _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = Path(out_dir)
    kind, source = _resolve_target(database_url)
    if kind == "postgres":
        output = destination / f"{BACKUP_PREFIX}-{stamp}.sql"
        return [f'pg_dump --no-owner --no-privileges --file="{output}" "{source}"']
    output = destination / f"{BACKUP_PREFIX}-{stamp}.sqlite"
    commands = [f'sqlite3 "{source}" ".backup {output}"']
    if include_redis and (redis_url or "").strip():
        commands.append(f'redis-cli -u "{redis_url}" SAVE')
    return commands


def _backup_files(out_dir: str | Path) -> list[Path]:
    """Existing backup files in the output directory, newest first."""
    matches = []
    for path in Path(out_dir).glob(f"{BACKUP_PREFIX}-*"):
        if _TIMESTAMP_PATTERN.match(path.name):
            matches.append(path)
    matches.sort(key=lambda p: p.name, reverse=True)
    return matches


def apply_retention(
    out_dir: str | Path,
    retention: int,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Prune backups beyond the newest ``retention``; returns deleted paths."""
    if retention < 0:
        raise ValueError("retention must be >= 0")
    files = _backup_files(out_dir)
    doomed = files[retention:] if retention > 0 else files
    for path in doomed:
        if not dry_run:
            path.unlink(missing_ok=True)
    return doomed


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", ""))
    parser.add_argument("--out-dir", default="backups", help="backup output directory")
    parser.add_argument(
        "--retention", type=int, default=7, help="keep this many newest backups"
    )
    parser.add_argument(
        "--include-redis",
        action="store_true",
        help="also run `redis-cli SAVE` when REDIS_URL is configured",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan without executing anything",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    commands = build_commands(
        args.database_url,
        out_dir,
        include_redis=args.include_redis,
        redis_url=args.redis_url,
    )
    kind, source = _resolve_target(args.database_url)
    print(f"[backup_db] kind={kind} source={source}")
    if kind == "sqlite" and not Path(source).exists():
        print(
            f"[backup_db] warning: SQLite source {source} does not exist yet; "
            "the backup will produce an empty database",
            file=sys.stderr,
        )
    for command in commands:
        print(f"[backup_db] {'dry-run' if args.dry_run else 'run'}: {command}")

    if not args.dry_run:
        if not out_dir.exists():
            out_dir.mkdir(parents=True)
        for command in commands:
            result = subprocess.run(command, shell=True, check=False)
            if result.returncode != 0:
                print(f"[backup_db] FAILED: {command}", file=sys.stderr)
                return result.returncode

    if args.retention > 0 or not commands:
        doomed = apply_retention(out_dir, args.retention, dry_run=args.dry_run)
        for path in doomed:
            print(
                f"[backup_db] {'would delete' if args.dry_run else 'deleted'}: {path}"
            )
    print(
        f"[backup_db] {'planned' if args.dry_run else 'completed'}: "
        f"{len(commands)} command(s), {args.retention} retained"
    )
    if args.include_redis and args.redis_url:
        print(
            "[backup_db] note: the Redis result cache is derived/rebuildable; "
            "SAVE covers the local server, managed providers own their "
            "snapshots, and a read-only replica is the production DR pattern "
            "(docs/backup-runbook.md)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
