"""Cached stat maps must fail closed without breaking sparse fixtures."""

import copy
import math

import pytest

from src.calculator.item_stat_block import get_item_stats
from src.calculator.stats import calculate_total_stats


def test_sparse_synthetic_item_stats_remain_zero_filled():
    """Champion/unit fixtures may intentionally omit the cached item schema."""
    stats = get_item_stats({"name": "synthetic", "stats": {}})

    assert stats["health"] == 0.0
    assert stats["omnivamp_percent"] == 0.0


@pytest.mark.parametrize(
    "item",
    [
        {"id": 999001, "name": "broken", "stats": None},
        {"id": 999002, "name": "broken", "stats": {"health": 42}},
        {"id": 999005, "name": "broken", "stats": {"health": {"flat": 42}}},
        {
            "id": 999003,
            "name": "broken",
            "stats": {"omnivamp": {"percent": "10"}},
        },
        {
            "id": 999004,
            "name": "broken",
            "stats": {"health": {"flat": math.nan}},
        },
    ],
)
def test_malformed_cached_item_stats_raise_instead_of_defaulting_to_zero(item):
    """Source records with malformed nested values name the broken item."""
    with pytest.raises(ValueError, match="Cached item broken"):
        get_item_stats(item)


def test_validation_cache_rechecks_a_replaced_source_stats_map():
    components = {
        "flat": 0,
        "percent": 0,
        "perLevel": 0,
        "percentPerLevel": 0,
        "percentBase": 0,
        "percentBonus": 0,
    }
    item = {"id": 999006, "name": "refreshable", "stats": {"health": components}}

    get_item_stats(item)
    item["stats"] = {"health": {"flat": 42}}

    with pytest.raises(ValueError, match="Cached item refreshable"):
        get_item_stats(item)


@pytest.mark.parametrize("broken", [math.nan, math.inf])
def test_a_non_finite_cached_mana_regen_raises(ahri_data: dict, broken: float):
    """The mana and energy walks integrate this stat once per event.

    A non-finite value would reach every ``OP_REGEN`` amount and publish as
    mana restored, so the stat sheet refuses it and names the cached record.
    """
    champion = copy.deepcopy(ahri_data)
    champion["stats"]["manaRegen"]["flat"] = broken

    with pytest.raises(ValueError, match="resource_regen_per_second is not finite"):
        calculate_total_stats(champion, 11, [])
