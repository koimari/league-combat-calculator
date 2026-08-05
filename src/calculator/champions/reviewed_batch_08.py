"""Exact packet wrappers for the CP10.8 full-entry Wiki boundary."""

from __future__ import annotations

import json
from pathlib import Path

from .packet_module import build_packet_module

BATCH_08 = (
    "Sona",
    "Swain",
    "Sylas",
    "Talon",
    "Taric",
    "Teemo",
    "Thresh",
    "Tristana",
    "Trundle",
    "Tryndamere",
    "Twisted Fate",
    "Twitch",
)

_SOURCE_PATH = (
    Path(__file__).resolve().parents[3] / "static" / "cp10_batch_08_sources.json"
)


def _full_entry_sources(name: str) -> list[dict[str, object]]:
    """Load the parent plus P/Q/W/E/R receipts from the deployable asset."""

    try:
        payload = json.loads(_SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"CP10.8 source receipts are unavailable: {_SOURCE_PATH}"
        ) from exc
    rows = payload.get(name) if isinstance(payload, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 6
        or any(not isinstance(row, dict) or not all(row.values()) for row in rows)
    ):
        raise RuntimeError(f"CP10.8 source receipts for {name!r} are incomplete")
    return rows


def build_batch_module(name: str):
    """Return the packet parser plus explicit reviewed metadata for *name*."""

    if name not in BATCH_08:
        raise KeyError(f"CP10.8 does not contain {name!r}")
    parse, slots, assumptions, _sources, options = build_packet_module(name)
    assumptions = list(assumptions)
    assumptions.extend(
        (
            "The complete parent Wiki entry was read before certifying this module.",
            "Passive plus Q/W/E/R entries are represented by explicit packet or no-damage slot declarations.",
            "Rank arrays, cooldowns, typed target-health terms, and packet variants remain sourced from the local reviewed-packet asset.",
            "Non-damaging shields, buffs, movement, and utility branches remain explicit state/out-of-scope rows rather than invented damage.",
        )
    )
    return parse, slots, assumptions, _full_entry_sources(name), options
