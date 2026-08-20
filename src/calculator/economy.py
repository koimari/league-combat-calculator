"""Recipe-aware purchase economics: combine credit, auto-combine cascades,
40% sell-back, and transformation-item gating.

This module is the single source of truth for how a gold amount is spent on
an inventory.  It does not evaluate combat; the optimizer scores the resolved
final loadouts through the existing fight pipeline.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any, Iterable

from .data_fetcher import fetch_item_data
from .data_registry import data_version
from .economics_data import sourced_combine_cost, sourced_sell_value, sourced_total
from .loadout_rules import ITEM_TO_EXCLUSIVITY_GROUPS, inventory_capacity

BASIC = "BASIC"
EPIC = "EPIC"
LEGENDARY = "LEGENDARY"
STARTER = "STARTER"
BOOTS = "BOOTS"

_PURCHASABLE_RANKS = {BASIC, EPIC, LEGENDARY, BOOTS}
_STACKABLE_RANKS = {BASIC}


_ITEM_BY_ID_SOURCE: dict[str, Any] | None = None
_ITEM_BY_ID_VERSION: int = -1
_ITEM_BY_ID_MEMO: dict[int, dict[str, Any]] = {}


def _item_by_id() -> dict[int, dict[str, Any]]:
    """Id-keyed view of the item cache, memoized by cache generation.

    The optimizer prices thousands of plans per request; rebuilding this
    mapping per call dominated enumeration.  The memo is valid while both
    the cache object and ``data_version()`` are unchanged: the identity
    check catches a replaced cache, and the version catches a cache
    refreshed in place, which identity alone cannot see (D-49).
    """
    global _ITEM_BY_ID_SOURCE, _ITEM_BY_ID_MEMO  # pylint: disable=global-statement
    global _ITEM_BY_ID_VERSION  # pylint: disable=global-statement
    source = fetch_item_data()
    version = data_version()
    if source is not _ITEM_BY_ID_SOURCE or version != _ITEM_BY_ID_VERSION:
        _ITEM_BY_ID_SOURCE = source
        _ITEM_BY_ID_VERSION = version
        _ITEM_BY_ID_MEMO = {int(item_id): item for item_id, item in source.items()}
    return _ITEM_BY_ID_MEMO


def item_total(item: dict[str, Any]) -> int:
    """Return the sourced total shop price, failing closed on missing data.

    Prefers the DDragon total from the atomized economics tables: the wiki
    cache can carry stale buy prices (Redemption cached at 2250 while the
    real total is 2300).  Falls back to the cache when no sourced row exists.
    """
    name = str(item.get("name") or "Unknown item")
    sourced = sourced_total(item)
    if sourced is not None:
        return sourced
    prices = item.get("shop", {}).get("prices", {})
    if "total" not in prices:
        raise KeyError(f"{name}: shop.prices.total")
    total = int(prices["total"])
    if total <= 0:
        raise ValueError(f"{name}: shop.prices.total must be positive")
    return total


def item_sell_value(item: dict[str, Any]) -> int:
    """Return the sourced sell refund for an item.

    The real refund is 70% of total for most items (the vendored cache
    hard-codes 40%, wrong for 185 of 209 shop items); the sourced table
    carries per-item DDragon values with the reviewed exceptions.
    """
    return sourced_sell_value(item)


def combine_cost(item: dict[str, Any]) -> int:
    """Return the combine fee: total minus the sum of direct component totals.

    Prefers the sourced combine table (it corrects stale cached totals, e.g.
    Redemption) and derives from the cache only when the item has no sourced
    row, failing closed on any missing price.
    """
    name = str(item.get("name") or "Unknown item")
    sourced = sourced_combine_cost(item)
    if sourced is not None:
        return sourced
    total = item_total(item)
    components = recipe_demand(item)
    if not components:
        return 0
    by_id = _item_by_id()
    invested = sum(
        item_total(by_id[component_id]) * count
        for component_id, count in components.items()
    )
    combined = total - invested
    if combined < 0:
        raise ValueError(f"{name}: combine cost {combined} is negative")
    return combined


def recipe_demand(item: dict[str, Any]) -> dict[int, int]:
    """Return the direct recipe demand as {item_id: count} (multiset)."""
    demand: dict[int, int] = collections.Counter()
    for component_id in item.get("buildsFrom", []) or []:
        demand[int(component_id)] += 1
    return dict(demand)


def is_transformation_item(item: dict[str, Any]) -> bool:
    """Return True for items that only exist by transforming another item.

    Transformation items (Seraph's Embrace, Muramana, Fimbulwinter, Diadem
    of Songs, Runic Compass, ...) cannot be bought in the shop; they appear
    through ``specialRecipe`` transitions and must never be purchase
    candidates.
    """
    return bool(int(item.get("specialRecipe", 0) or 0))


def is_purchasable(item: dict[str, Any], include_starters: bool = False) -> bool:
    """Return whether the item can be bought in the modeled shop scope.

    Boots are purchasable through the dedicated boots slot; the optimizer
    keeps them in a separate pool by rank.
    """
    if is_transformation_item(item):
        return False
    ranks = {str(rank).upper() for rank in item.get("rank", []) or []}
    if not ranks & _PURCHASABLE_RANKS:
        return False
    if STARTER in ranks and not include_starters:
        return False
    return True


def _stackable_epics() -> frozenset[str]:
    """EPIC items that may appear more than once in a legal inventory.

    Derived from the cache: any EPIC appearing at least twice across the
    recipe graph is stackable (the game allows duplicate components such as
    2x Serrated Dirk).  Every other EPIC fails closed to unique until the
    wiki limit column is ingested.
    """
    counts: collections.Counter[int] = collections.Counter()
    for item in _item_by_id().values():
        for component_id in item.get("buildsFrom", []) or []:
            counts[int(component_id)] += 1
    by_id = _item_by_id()
    return frozenset(
        by_id[component_id]["name"]
        for component_id, count in counts.items()
        if count >= 2
        and EPIC in {str(r).upper() for r in by_id[component_id].get("rank", []) or []}
    )


def is_stackable(item: dict[str, Any]) -> bool:
    """Return whether duplicate copies of the item are legal mid-inventory."""
    ranks = {str(rank).upper() for rank in item.get("rank", []) or []}
    if ranks & _STACKABLE_RANKS:
        return True
    if LEGENDARY in ranks or STARTER in ranks or BOOTS in ranks:
        return False
    name = str(item.get("name") or "")
    return name in _stackable_epics()


@dataclass
class PriceRow:
    """One priced step in a purchase plan (a buy, a completion, or a sell)."""

    item: str
    list_price: int = 0
    components_consumed: list[dict[str, Any]] = field(default_factory=list)
    combined_charged: int = 0
    sell_refund: int = 0
    net: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "list_price": self.list_price,
            "components_consumed": [
                {
                    "name": row["name"],
                    "count": row["count"],
                    "value": row["value"],
                }
                for row in self.components_consumed
            ],
            "combined_charged": self.combined_charged,
            "sell_refund": self.sell_refund,
            "net": self.net,
        }


@dataclass
class PurchasePlan:
    """A complete, priced shop plan producing a resolved final loadout."""

    sell_items: list[str] = field(default_factory=list)
    purchases: list[str] = field(default_factory=list)
    final_items: list[dict[str, Any]] = field(default_factory=list)
    final_boots: dict[str, Any] | None = None
    price_rows: list[PriceRow] = field(default_factory=list)
    spend: int = 0
    refund: int = 0
    remaining: int = 0
    incomplete_combine: bool = False


_COMBINABLE_ROWS_SOURCE: dict[int, dict[str, Any]] | None = None
_COMBINABLE_ROWS: list[tuple[int, dict[int, int]]] = []


def _combinable_recipe_rows(
    by_id: dict[int, dict[str, Any]],
) -> list[tuple[int, dict[int, int]]]:
    """(item_id, demand) for every purchasable, combinable recipe.

    Memoized by the identity of ``by_id``: the optimizer scans the shop's
    recipes thousands of times per request, and re-walking every item's
    purchasability and recipe per scan dominated plan pricing.
    """
    global _COMBINABLE_ROWS_SOURCE, _COMBINABLE_ROWS  # pylint: disable=global-statement
    if by_id is not _COMBINABLE_ROWS_SOURCE:
        rows = []
        for item_id, item in by_id.items():
            if not is_purchasable(item) or is_transformation_item(item):
                continue
            demand = recipe_demand(item)
            if demand:
                rows.append((item_id, demand))
        _COMBINABLE_ROWS_SOURCE = by_id
        _COMBINABLE_ROWS = rows
    return _COMBINABLE_ROWS


def combine_candidates(
    inventory: dict[int, int],
    by_id: dict[int, dict[str, Any]],
) -> list[tuple[int, dict[int, int], int]]:
    """Return every recipe currently satisfiable by the inventory multiset.

    Each candidate is ``(item_id, demand, fee)`` where fee is the real
    combine price (total minus the totals of the components it consumes).
    """
    candidates: list[tuple[int, dict[int, int], int]] = [
        (item_id, demand, combine_cost(by_id[item_id]))
        for item_id, demand in _combinable_recipe_rows(by_id)
        if all(
            inventory.get(component_id, 0) >= count
            for component_id, count in demand.items()
        )
    ]
    candidates.sort(key=lambda row: (-row[2], row[0]))
    return candidates


def apply_purchase_plan(
    owned_items: Iterable[dict[str, Any]],
    owned_boots: dict[str, Any] | None,
    buys: Iterable[dict[str, Any]],
    gold_on_hand: int,
    sell_items: Iterable[dict[str, Any]] | None = None,
    combine_items: Iterable[dict[str, Any]] | None = None,
    combine_policy: str = "shop_combine",
    role: str = "",
    role_quest_complete: bool = False,
    flag_incomplete_combine: bool = True,
) -> PurchasePlan:
    """Apply a real-shop plan to the owned inventory and return the priced result.

    Model matches the LoL shop exactly:

    * **Buy** pays the full list price (no credit, no auto-combine).
    * **Combine** is an explicit action: it consumes the owned components and
      charges the combine fee ``total - sum(component totals)``.
    * **Sell** refunds ``floor(0.4 * total)`` before purchases.
    * Under ``shop_combine``, recipes left fully satisfied but uncombined are
      flagged ``incomplete_combine`` so the optimizer can offer the combine;
      under ``component_accumulate`` they are simply left as components.
    """
    if combine_policy not in {"shop_combine", "component_accumulate"}:
        raise ValueError(
            "combine_policy must be 'shop_combine' or 'component_accumulate'"
        )
    by_id = _item_by_id()
    registry: dict[int, dict[str, Any]] = {}
    inventory: dict[int, int] = collections.Counter()
    for item in owned_items:
        item_id = int(item["id"])
        registry[item_id] = item
        inventory[item_id] += 1
    for item in buys:
        registry[int(item["id"])] = item
    for item in combine_items or ():
        registry[int(item["id"])] = item

    plan = PurchasePlan(
        sell_items=[item["name"] for item in (sell_items or ())],
        purchases=[item["name"] for item in buys],
    )
    remaining = gold_on_hand
    for sold in sell_items or ():
        refund = item_sell_value(sold)
        sold_id = int(sold["id"])
        if inventory.get(sold_id, 0) <= 0:
            raise ValueError(f"Cannot sell {sold['name']}: not owned")
        inventory[sold_id] -= 1
        if inventory[sold_id] <= 0:
            del inventory[sold_id]
        remaining += refund
        plan.refund += refund
        plan.price_rows.append(
            PriceRow(item=sold["name"], sell_refund=refund, net=-refund)
        )

    boots = owned_boots
    for buy in buys:
        name = str(buy.get("name") or "Unknown item")
        if not is_purchasable(buy):
            raise ValueError(f"{name} is not purchasable in the modeled shop")
        ranks = {str(rank).upper() for rank in buy.get("rank", []) or []}
        if BOOTS in ranks:
            cost = item_total(buy)
            if remaining < cost:
                raise ValueError(
                    f"{name}: costs {cost} gold, only {remaining} available"
                )
            remaining -= cost
            plan.spend += cost
            if boots is not None:
                raise ValueError(f"{name}: a pair of boots is already owned")
            boots = buy
            plan.price_rows.append(PriceRow(item=name, list_price=cost, net=cost))
            continue

        # Buying a completed item charges the remaining cost: total minus the
        # totals of owned components, which are consumed (wiki Item: "an
        # advanced item can be purchased without having all of its components
        # ... the combined cost will be increased by the cost of the missing
        # components").  Buying a plain component never combines anything.
        demand = recipe_demand(buy)
        credit = 0
        consumed = []
        if demand:
            for component_id, count in demand.items():
                use = min(inventory.get(component_id, 0), count)
                if use:
                    consumed.append(
                        {
                            "name": by_id[component_id]["name"],
                            "count": use,
                            "value": item_total(by_id[component_id]) * use,
                        }
                    )
                    credit += item_total(by_id[component_id]) * use
                    inventory[component_id] -= use
                    if inventory[component_id] <= 0:
                        del inventory[component_id]
        cost = item_total(buy) - credit
        if remaining < cost:
            raise ValueError(f"{name}: costs {cost} gold, only {remaining} available")
        remaining -= cost
        plan.spend += cost
        inventory[int(buy["id"])] += 1
        plan.price_rows.append(
            PriceRow(
                item=name,
                list_price=item_total(buy),
                components_consumed=consumed,
                combined_charged=0,
                net=cost,
            )
        )

    for combine in combine_items or ():
        name = str(combine.get("name") or "Unknown item")
        if not is_purchasable(combine) or is_transformation_item(combine):
            raise ValueError(f"{name} is not a combinable shop item")
        demand = recipe_demand(combine)
        if not demand:
            raise ValueError(f"{name} has no recipe; it cannot be combined")
        if not all(
            inventory.get(component_id, 0) >= count
            for component_id, count in demand.items()
        ):
            raise ValueError(f"{name}: not all components are owned")
        fee = combine_cost(combine)
        if remaining < fee:
            raise ValueError(
                f"{name}: combining costs {fee} gold, only {remaining} available"
            )
        consumed = [
            {
                "name": by_id[component_id]["name"],
                "count": count,
                "value": item_total(by_id[component_id]) * count,
            }
            for component_id, count in sorted(demand.items())
        ]
        for component_id, count in demand.items():
            inventory[component_id] -= count
            if inventory[component_id] <= 0:
                del inventory[component_id]
        inventory[int(combine["id"])] += 1
        remaining -= fee
        plan.spend += fee
        plan.price_rows.append(
            PriceRow(
                item=name,
                list_price=item_total(combine),
                components_consumed=consumed,
                combined_charged=fee,
                net=fee,
            )
        )

    # The shop-wide recipe scan is a receipt detail, not a pricing input;
    # search pricing skips it (flag_incomplete_combine=False) and recomputes
    # it for the winning plan via plan_incomplete_combine.
    if (
        flag_incomplete_combine
        and combine_policy == "shop_combine"
        and combine_candidates(inventory, by_id)
    ):
        plan.incomplete_combine = True
    plan.final_items = [
        registry[item_id]
        for item_id in sorted(inventory)
        for _ in range(inventory[item_id])
    ]
    plan.final_boots = boots
    plan.remaining = remaining
    return plan


def plan_incomplete_combine(plan: PurchasePlan) -> bool:
    """Recompute the incomplete_combine receipt for a priced plan's inventory."""
    inventory = collections.Counter(int(item["id"]) for item in plan.final_items)
    return bool(combine_candidates(inventory, _item_by_id()))


def _find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for item in items:
        if item["name"] == name:
            return item
    raise LookupError(name)
