"""Public loader for champion full-entry source receipts.

Historical CP10 assets remain generated evidence, not runtime architecture.
This module is their one reader: named champion modules ask for their own
rows without importing batch membership or private cross-module helpers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_STATIC_ROOT = Path(__file__).resolve().parents[3] / "static"
_PACKET_MANIFEST = _STATIC_ROOT / "reviewed-packets.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Champion source receipts are unavailable: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Champion source receipt asset is not an object: {path}")
    return payload


def _valid_rows(rows: Any) -> list[dict[str, Any]] | None:
    """Return typed copies of revision-receipt rows, or None when malformed.

    Every published row must carry the canonical receipt shape: a non-empty
    ``label`` and ``url``, a positive integer ``revision_id``, and a non-empty
    ``revision_timestamp``.  A regenerated asset that loses that shape must
    fail closed here rather than flow untyped into ``/api/config``.
    """
    if not isinstance(rows, list) or not rows:
        return None
    for row in rows:
        if not isinstance(row, dict):
            return None
        label = row.get("label")
        url = row.get("url")
        revision_id = row.get("revision_id")
        revision_timestamp = row.get("revision_timestamp")
        if (
            not isinstance(label, str)
            or not label
            or not isinstance(url, str)
            or not url
            or isinstance(revision_id, bool)
            or not isinstance(revision_id, int)
            or revision_id <= 0
            or not isinstance(revision_timestamp, str)
            or not revision_timestamp
        ):
            return None
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def _source_index() -> dict[str, tuple[dict[str, Any], ...]]:
    """Index generated receipts without preserving campaign membership."""

    index: dict[str, tuple[dict[str, Any], ...]] = {}
    for path in sorted(_STATIC_ROOT.glob("cp10_batch_*_sources.json")):
        for name, rows in _read_json(path).items():
            valid = _valid_rows(rows)
            if valid is None:
                raise RuntimeError(
                    f"Champion source receipts for {name!r} are incomplete in {path}"
                )
            source_rows = tuple(valid)
            prior = index.get(str(name))
            if prior is not None and prior != source_rows:
                raise RuntimeError(
                    f"Champion source receipts for {name!r} conflict across assets"
                )
            index[str(name)] = source_rows

    manifest = _read_json(_PACKET_MANIFEST)
    champions = manifest.get("champions")
    if not isinstance(champions, dict):
        raise RuntimeError("reviewed-packets.json has no champion map")
    for name, entry in champions.items():
        if name in index or not isinstance(entry, dict):
            continue
        valid = _valid_rows(entry.get("sources"))
        if valid is not None:
            index[str(name)] = tuple(valid)
    return index


def load_champion_sources(name: str) -> list[dict[str, Any]]:
    """Return a defensive copy of the generated receipts for *name*."""

    rows = _source_index().get(name)
    if rows is None:
        raise RuntimeError(f"No source receipts are published for {name!r}")
    return [dict(row) for row in rows]
