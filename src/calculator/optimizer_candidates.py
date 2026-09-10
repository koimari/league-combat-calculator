"""Which items a search may legally hold, and what they cost."""

from collections.abc import Iterable, Mapping
from typing import Any

from . import item_coverage
from .data_fetcher import fetch_item_data
from .item_source import is_ordinary_sr_item
from .loadout_rules import (
    conflicts_with_groups,
    occupied_groups,
    role_scoped_shop_items,
)


def _ordinary_sr_items() -> list[dict[str, Any]]:
    """Every cached item an ordinary Summoner's Rift build can hold.

    ``item_source`` reads availability off the cached sources, so an ARAM
    starter leaves the pool because the data says so, not a name list.
    """
    return [
        item_data
        for item_data in fetch_item_data().values()
        if item_data.get("name") and is_ordinary_sr_item(item_data)
    ]


def get_eligible_legendaries() -> list[dict[str, Any]]:
    """Return all legendary items eligible for the optimizer."""
    return [
        item_data
        for item_data in _ordinary_sr_items()
        if "LEGENDARY" in item_data.get("rank", [])
        and "BOOTS" not in item_data.get("rank", [])
    ]


def get_selectable_items() -> list[dict[str, Any]]:
    """Return ordinary Summoner's Rift build items for manual loadouts.

    The optimizer intentionally searches completed legendary items only.
    Manual scenario reconstruction also needs components and starters such as
    Ruby Crystal, Dark Seal, and Doran's Ring.
    """
    allowed_ranks = {"BASIC", "EPIC", "STARTER", "LEGENDARY"}
    return [
        item_data
        for item_data in _ordinary_sr_items()
        if allowed_ranks.intersection(item_data.get("rank", []))
        and "BOOTS" not in item_data.get("rank", [])
    ]


def get_eligible_boots(tier: int | None = 2) -> list[dict[str, Any]]:
    """Return boots eligible for the requested role-quest tier.

    Ordinary builds use tier 2. Completed mid-lane quests use tier 3.
    Passing ``None`` returns both tiers for the role-aware manual picker.
    """
    return [
        item_data
        for item_data in _ordinary_sr_items()
        if "BOOTS" in item_data.get("rank", [])
        and item_data.get("tier", 0) >= 2
        and (tier is None or item_data.get("tier") == tier)
    ]


def _get_occupied_groups(items: Iterable[dict[str, Any]]) -> set[str]:
    """Return the set of exclusivity groups already occupied by *items*."""
    return occupied_groups(item.get("name", "") for item in items)


def _conflicts_with_build(
    candidate_name: str,
    occupied: set[str],
) -> bool:
    """Return True if *candidate_name* would violate an exclusivity group."""
    return conflicts_with_groups(candidate_name, occupied)


def item_gold(item: Mapping[str, Any]) -> int:
    """Return the sourced total shop price, failing closed on a broken record.

    ``shop.prices.total`` is cache-owned; a literal default here would make
    an item free the moment the parser stopped writing its price.
    """
    name = str(item.get("name") or "Unknown item")
    prices = item.get("shop", {}).get("prices", {})
    if "total" not in prices:
        raise KeyError(f"{name}: shop.prices.total")
    price = int(prices["total"])
    if price <= 0:
        raise ValueError(f"{name}: shop.prices.total must be positive")
    return price


def _build_gold(items: Iterable[dict[str, Any]]) -> int:
    """Return total shop price for a resolved build."""
    return sum(item_gold(item) for item in items)


_LEGAL_LOCKED_RANKS = {"BASIC", "EPIC", "LEGENDARY", "STARTER"}


def _legal_locked_shop_item(item: dict[str, Any]) -> bool:
    """Whether an item may be locked in an optimizer inventory.  Shop
    availability is not enough, since a consumable is buyable and is not a
    final-build item.
    """
    if not is_ordinary_sr_item(item):
        return False
    ranks = {str(rank).upper() for rank in item.get("rank", []) or []}
    return bool(ranks & _LEGAL_LOCKED_RANKS)


def get_purchase_items(role: str = "") -> list[dict[str, Any]]:
    """Return ordinary modeled singles for the purchase search.

    Components (BASIC/EPIC) plus role-scoped legendaries.  Boots stay in a
    separate pool and transformation items are excluded by ``is_purchasable``
    at the search site, never by this helper.
    """
    supported = item_coverage.optimizer_supported_items(_ordinary_sr_items())
    components = [
        item
        for item in supported
        if {"BASIC", "EPIC"}.intersection(item.get("rank", []))
        and "BOOTS" not in item.get("rank", [])
    ]
    legendaries = role_scoped_shop_items(
        [
            item
            for item in supported
            if "LEGENDARY" in item.get("rank", [])
            and "BOOTS" not in item.get("rank", [])
        ],
        role,
    )
    return components + legendaries
