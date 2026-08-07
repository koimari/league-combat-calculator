"""Tests for the recipe-aware purchase economics engine."""

import pytest

from src.calculator.data_fetcher import fetch_item_data, get_item_by_name
from src.calculator.economy import (
    apply_purchase_plan,
    combine_candidates,
    combine_cost,
    is_purchasable,
    is_stackable,
    is_transformation_item,
    item_sell_value,
    item_total,
    validate_economy_loadout,
)


def _item(name):
    return get_item_by_name(name)


def test_sell_value_matches_sourced_table_for_every_sourced_item():
    from src.calculator.economics_data import _Tables

    rows = _Tables.load()["per_item_sell"]
    assert len(rows) >= 200
    cache_by_id = {int(item_id): item for item_id, item in fetch_item_data().items()}
    for row in rows:
        item = cache_by_id.get(row["id"])
        assert item is not None, row["name"]
        from src.calculator.economy import item_sell_value

        assert item_sell_value(item) == row["ddragon_sell"], row["name"]


def test_sell_value_uses_real_70_percent_rule_not_stale_cache():
    # B. F. Sword: 1300 total -> 910 refund (70%), while the cache says 520 (40%).
    from src.calculator.economy import item_sell_value

    item = _item("B. F. Sword")
    assert item_sell_value(item) == 910
    assert item["shop"]["prices"]["sell"] == 520  # stale cache proves the fix


def test_sell_value_respects_reviewed_exceptions():
    from src.calculator.economics_data import _Tables
    from src.calculator.economy import item_sell_value

    assert item_sell_value(_item("Rejuvenation Bead")) == 120  # 40%
    assert item_sell_value(_item("Guardian Angel")) == 1280  # 40% legendary
    rows = {row["name"]: row for row in _Tables.load()["per_item_sell"]}
    assert rows["Redemption"]["ratio"] >= 0.7  # 70% ordinary legendary
    assert any(
        "Slightly Magical Footwear" in item
        for item in _Tables.load()["sell_rule"]["exceptions_30pct"]
    )


def test_combine_cost_identity_for_infinity_edge():
    assert combine_cost(_item("Infinity Edge")) == 725


def test_combine_cost_uses_sourced_table_for_stale_cache_items():
    # Redemption: the repo cache total is stale (2250) but DDragon gold.base
    # is authoritative (850, with real total 2300); the refreshed sourced
    # table carries the DDragon value, fixing the stale-cache derivation.
    assert combine_cost(_item("Redemption")) == 850
    assert _item("Redemption")["shop"]["prices"]["total"] == 2250  # stale cache


def test_buy_completed_item_charges_remaining_and_consumes_components():
    """H1b full: buying IE with BF+Pickaxe owned charges 1325 and consumes them."""
    plan = apply_purchase_plan(
        [_item("B. F. Sword"), _item("Pickaxe")],
        None,
        [_item("Infinity Edge")],
        gold_on_hand=1400,
    )
    assert [item["name"] for item in plan.final_items] == ["Infinity Edge"]
    assert plan.spend == 1325
    assert plan.remaining == 75


def test_buy_completed_item_with_no_components_is_full_price():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Infinity Edge")],
        gold_on_hand=3500,
    )
    assert [item["name"] for item in plan.final_items] == ["Infinity Edge"]
    assert plan.spend == 3500


def test_explicit_combine_consumes_components_and_charges_fee():
    plan = apply_purchase_plan(
        [_item("B. F. Sword"), _item("Pickaxe"), _item("Cloak of Agility")],
        None,
        [],
        gold_on_hand=725,
        combine_items=[_item("Infinity Edge")],
    )
    assert [item["name"] for item in plan.final_items] == ["Infinity Edge"]
    assert plan.spend == 725
    assert plan.remaining == 0


def test_buy_component_then_combine_recipe():
    plan = apply_purchase_plan(
        [_item("B. F. Sword"), _item("Pickaxe")],
        None,
        [_item("Cloak of Agility")],
        gold_on_hand=1400,
        combine_items=[_item("Infinity Edge")],
    )
    assert [item["name"] for item in plan.final_items] == ["Infinity Edge"]
    assert plan.spend == 1325
    assert plan.remaining == 75


def test_duplicate_component_recipe_combine_fee():
    plan = apply_purchase_plan(
        [_item("Needlessly Large Rod")],
        None,
        [_item("Needlessly Large Rod")],
        gold_on_hand=2300,
        combine_items=[_item("Rabadon's Deathcap")],
    )
    assert [item["name"] for item in plan.final_items] == ["Rabadon's Deathcap"]
    assert plan.spend == 2300
    assert plan.remaining == 0


def test_two_long_swords_legal_as_components():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Long Sword"), _item("Long Sword")],
        gold_on_hand=700,
    )
    assert [item["name"] for item in plan.final_items] == ["Long Sword", "Long Sword"]
    assert plan.spend == 700
    # 2x Long Sword satisfies Tiamat, Last Whisper and Serrated Dirk recipes
    assert plan.incomplete_combine is True


def test_component_accumulate_does_not_flag_leftover_recipes():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Long Sword"), _item("Long Sword")],
        gold_on_hand=700,
        combine_policy="component_accumulate",
    )
    assert [item["name"] for item in plan.final_items] == ["Long Sword", "Long Sword"]
    assert plan.incomplete_combine is False


def test_sell_refunds_before_purchase():
    plan = apply_purchase_plan(
        [_item("Long Sword")],
        None,
        [_item("Pickaxe")],
        gold_on_hand=900,
        sell_items=[_item("Long Sword")],
    )
    assert plan.refund == 245  # 70% of 350 (Long Sword)
    assert plan.remaining == 270
    assert [item["name"] for item in plan.final_items] == ["Pickaxe"]
    assert [row.item for row in plan.price_rows] == ["Long Sword", "Pickaxe"]


def test_boots_purchase_uses_dedicated_slot():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Sorcerer's Shoes")],
        gold_on_hand=1100,
    )
    assert plan.final_boots["name"] == "Sorcerer's Shoes"
    assert plan.final_items == []


def test_combine_candidates_requires_all_components():
    from collections import Counter

    from src.calculator.economy import _item_by_id

    by_id = _item_by_id()
    inv = Counter(
        int(item["id"])
        for item in [_item("Bramble Vest"), _item("Chain Vest"), _item("Ruby Crystal")]
    )
    candidates = combine_candidates(inv, by_id)
    assert any(by_id[item_id]["name"] == "Thornmail" for item_id, _d, _f in candidates)
    # One missing component removes the candidate.
    inv.pop(int(_item("Ruby Crystal")["id"]))
    candidates = combine_candidates(inv, by_id)
    assert not any(
        by_id[item_id]["name"] == "Thornmail" for item_id, _d, _f in candidates
    )


def test_transformation_items_are_not_purchasable():
    for name in ["Seraph's Embrace", "Muramana", "Fimbulwinter", "Runic Compass"]:
        item = _item(name)
        assert is_transformation_item(item)
        assert not is_purchasable(item)
    with pytest.raises(ValueError, match="not purchasable"):
        apply_purchase_plan([], None, [_item("Seraph's Embrace")], gold_on_hand=5000)


def test_stackability_review():
    assert is_stackable(_item("Long Sword"))  # BASIC
    assert is_stackable(_item("Serrated Dirk"))  # multi-demand EPIC
    assert not is_stackable(_item("Infinity Edge"))  # LEGENDARY
    assert not is_stackable(_item("Sorcerer's Shoes"))  # BOOTS


def test_duplicate_legendary_final_loadout_rejected():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Infinity Edge"), _item("Infinity Edge")],
        gold_on_hand=8000,
    )
    with pytest.raises(ValueError, match="Infinity Edge"):
        validate_economy_loadout(plan)


def test_duplicate_stackable_final_loadout_accepted():
    plan = apply_purchase_plan(
        [],
        None,
        [_item("Long Sword"), _item("Long Sword")],
        gold_on_hand=700,
    )
    validate_economy_loadout(plan)


def test_missing_price_fails_closed():
    with pytest.raises(KeyError, match=r"Broken Item: shop\.prices\.total"):
        item_total({"name": "Broken Item", "shop": {"prices": {}}})


def test_unaffordable_plan_raises():
    with pytest.raises(ValueError, match="costs"):
        apply_purchase_plan([], None, [_item("Infinity Edge")], gold_on_hand=100)


def by_name(items):
    return [item["name"] for item in items]


def test_buying_final_component_never_auto_combines():
    """H0 rejected: buying Cloak while owning BF+Pickaxe keeps all three items."""
    plan = apply_purchase_plan(
        [_item("B. F. Sword"), _item("Pickaxe")],
        None,
        [_item("Cloak of Agility")],
        gold_on_hand=600,
    )
    assert sorted(item["name"] for item in plan.final_items) == [
        "B. F. Sword",
        "Cloak of Agility",
        "Pickaxe",
    ]
    assert plan.spend == 600
    # The recipe is satisfiable but the plan did not combine it.
    assert plan.incomplete_combine is True


def test_combine_requires_all_components():
    """COMPLETE(y) requires D(y) subset of inventory; partial is rejected."""
    with pytest.raises(ValueError, match="not all components"):
        apply_purchase_plan(
            [_item("B. F. Sword"), _item("Pickaxe")],
            None,
            [],
            gold_on_hand=1000,
            combine_items=[_item("Infinity Edge")],
        )


def test_direct_completed_purchase_with_partial_components_charges_missing_cost():
    """2020 Item page: 'the combined cost will be increased by the cost of the
    missing components' — with BF owned (1300 of 3500), IE costs 2200."""
    plan = apply_purchase_plan(
        [_item("B. F. Sword")],
        None,
        [_item("Infinity Edge")],
        gold_on_hand=2200,
    )
    assert [item["name"] for item in plan.final_items] == ["Infinity Edge"]
    assert plan.spend == 2200
    assert plan.remaining == 0


def test_completion_never_costs_less_than_total():
    """T2: components + combine fee always equal the full total (no under-priced item)."""
    for name, components in [
        ("Infinity Edge", ["B. F. Sword", "Pickaxe", "Cloak of Agility"]),
        ("Rabadon's Deathcap", ["Needlessly Large Rod", "Needlessly Large Rod"]),
        ("Thornmail", ["Bramble Vest", "Chain Vest", "Ruby Crystal"]),
    ]:
        item = _item(name)
        fee = combine_cost(item)
        component_total = sum(item_total(_item(c)) for c in components)
        assert component_total + fee == item_total(item), name


def test_selling_completed_item_is_not_always_better_than_components():
    """Ratio mismatch flips the sell-vs-components comparison (Seeker's case).

    Seeker's Armguard sells at 40% (640) while its 70%-ratio components
    (2x Amplifying Tome + Cloth Armor) sell for 770 — selling the parts first
    recovers more gold than selling the completed item.
    """
    from src.calculator.economy import _item_by_id, recipe_demand

    seekers = _item("Seeker's Armguard")
    by_id = _item_by_id()
    demand = recipe_demand(seekers)
    components_sell = sum(
        item_sell_value(by_id[component_id]) * count
        for component_id, count in demand.items()
    )
    assert components_sell == 770
    assert item_sell_value(seekers) == 640
    assert item_sell_value(seekers) < components_sell
