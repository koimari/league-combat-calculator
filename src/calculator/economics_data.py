"""Patch-pinned economics tables sourced from DDragon 16.15.1 and the wiki.

The cached item data derives ``shop.prices.sell`` with a hard-coded 40%
rule (vendored parser), which is wrong for 185 of 209 ordinary shop items:
the real refund is 70% of total for most items, with reviewed exceptions
(40% starters/support chain/consumables/Guardian Angel/Rejuvenation Bead/
Seeker's Armguard, 30% Slightly Magical Footwear, 0% jungle pets).

This module reads the sourced tables and fails closed: an item missing from
the sourced sell table raises rather than falling back to the stale cache.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "economics-sourced.json"


class _Tables:
    _loaded: dict[str, Any] | None = None

    @classmethod
    def load(cls) -> dict[str, Any]:
        if cls._loaded is None:
            with _DATA_PATH.open(encoding="utf-8") as handle:
                cls._loaded = json.load(handle)
        return cls._loaded


def sourced_total(item: Mapping[str, Any]) -> int | None:
    """Return the sourced DDragon total price, or None when unavailable."""
    item_id = int(item.get("id") or 0)
    for row in _Tables.load().get("per_item_sell", []):
        if row.get("id") == item_id:
            value = row.get("total")
            if value is None:
                raise KeyError(
                    f"{item.get('name')}: economics-sourced per_item_sell.total"
                )
            return int(value)
    return None


def sourced_sell_value(item: Mapping[str, Any]) -> int:
    """Return the sourced sell refund for an item (never the stale cache)."""
    name = str(item.get("name") or "Unknown item")
    item_id = int(item.get("id") or 0)
    rows = _Tables.load().get("per_item_sell", [])
    for row in rows:
        if row.get("id") == item_id:
            value = row.get("ddragon_sell")
            if value is None:
                raise KeyError(f"{name}: economics-sourced per_item_sell.ddragon_sell")
            return int(value)
    raise KeyError(f"{name}: economics-sourced per_item_sell")


def sourced_combine_cost(item: Mapping[str, Any]) -> int | None:
    """Return the sourced combine fee, or None when the item has no recipe."""
    name = str(item.get("name") or "Unknown item")
    item_id = int(item.get("id") or 0)
    rows = _Tables.load().get("combine_costs", [])
    for row in rows:
        if row.get("id") == item_id:
            value = row.get("derived_combine")
            if value is None:
                raise KeyError(
                    f"{name}: economics-sourced combine_costs.derived_combine"
                )
            return int(value)
    return None
