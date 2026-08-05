"""Exact packet wrappers for the CP10.4 champion batch.

The numeric packet is read from the local, patch-pinned reviewed-packet asset.
This wrapper is deliberately separate from ``generated`` so the registry can
distinguish a full-entry-reviewed module from a runnable but unreviewed packet.
The corresponding full parent-page and P/Q/W/E/R template receipts are kept
in ``docs/wiki-full-entry-audit.json`` and ``docs/cp10-batch-04.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .packet_module import build_packet_module

BATCH_04 = (
    "Lucian",
    "Lulu",
    "Lux",
    "Malphite",
    "Malzahar",
    "Maokai",
    "Master Yi",
    "Mel",
    "Milio",
    "Miss Fortune",
    "Mordekaiser",
    "Morgana",
)

_AUDIT_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "wiki-full-entry-audit.json"
)


def _full_entry_sources(name: str) -> list[dict[str, object]]:
    """Load the parent plus P/Q/W/E/R source receipts from the local audit."""

    try:
        payload = json.loads(_AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Full-entry audit is unavailable: {_AUDIT_PATH}") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError("Full-entry audit has no entry list")
    receipt = next(
        (
            row
            for row in entries
            if isinstance(row, dict)
            and row.get("kind") == "champion"
            and row.get("name") == name
        ),
        None,
    )
    if not isinstance(receipt, dict):
        raise RuntimeError(f"Full-entry audit has no receipt for {name!r}")
    parent = {
        "label": f"{name} parent entry",
        "url": receipt.get("source_url"),
        "revision_id": receipt.get("revision_id"),
        "revision_timestamp": receipt.get("revision_timestamp"),
    }
    templates = receipt.get("ability_templates")
    if not isinstance(templates, list) or len(templates) != 5:
        raise RuntimeError(f"Full-entry audit for {name!r} does not cover P/Q/W/E/R")
    rows = [parent]
    rows.extend(
        {
            "label": f"{name} {template.get('slot')} ability entry",
            "url": template.get("source_url"),
            "revision_id": template.get("revision_id"),
            "revision_timestamp": template.get("revision_timestamp"),
        }
        for template in templates
        if isinstance(template, dict)
    )
    if len(rows) != 6 or any(not all(row.values()) for row in rows):
        raise RuntimeError(
            f"Full-entry audit for {name!r} has incomplete source receipts"
        )
    return rows


def build_batch_module(name: str):
    """Return the packet parser plus explicit reviewed metadata for *name*."""

    if name not in BATCH_04:
        raise KeyError(f"CP10.4 does not contain {name!r}")
    parse, slots, assumptions, sources, options = build_packet_module(name)
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
