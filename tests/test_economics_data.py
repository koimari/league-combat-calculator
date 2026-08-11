"""Front-door tests for sourced item economics."""

import pytest

from src.calculator.data_fetcher import get_item_by_name
from src.calculator.economics_data import (
    sourced_combine_cost,
    sourced_sell_value,
    sourced_total,
)


def test_cached_item_uses_the_sourced_economics_table() -> None:
    item = get_item_by_name("Infinity Edge")

    assert sourced_total(item) is not None
    assert sourced_sell_value(item) >= 0
    assert sourced_combine_cost(item) is None or sourced_combine_cost(item) >= 0


def test_missing_economics_entry_fails_closed() -> None:
    with pytest.raises(KeyError, match="economics-sourced"):
        sourced_sell_value({"name": "Synthetic", "id": -1})
