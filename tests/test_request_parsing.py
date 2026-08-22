"""The shared public coercion policy, exercised at its own front door."""

import pytest

from src.calculator.request_parsing import request_int, request_optional_int


def test_an_omitted_optional_int_is_none_rather_than_a_default():
    """An absent key, an explicit null and an empty string all mean nothing."""
    assert request_optional_int({}, "gold_budget", 1, 30_000) is None
    assert request_optional_int({"gold_budget": None}, "gold_budget", 1, 30_000) is None
    assert request_optional_int({"gold_budget": ""}, "gold_budget", 1, 30_000) is None


def test_a_supplied_optional_int_reads_under_the_shared_integer_policy():
    """Same coercion, same bounds, same error strings as request_int."""
    data = {"gold_budget": "2500"}
    assert request_optional_int(data, "gold_budget", 1, 30_000) == 2500
    assert request_optional_int({"gold_budget": 2500}, "gold_budget", 1, 30_000) == 2500

    with pytest.raises(ValueError, match="gold_budget must be an integer"):
        request_optional_int({"gold_budget": True}, "gold_budget", 1, 30_000)
    with pytest.raises(ValueError, match="gold_budget must be an integer"):
        request_optional_int({"gold_budget": "2500.0"}, "gold_budget", 1, 30_000)
    with pytest.raises(ValueError, match="gold_budget must be between 1 and 30000"):
        request_optional_int({"gold_budget": 0}, "gold_budget", 1, 30_000)


def test_zero_is_a_value_and_not_an_absent_field():
    """The sentinel set is exactly ``None`` and ``""``: 0 is supplied data."""
    with pytest.raises(ValueError, match="max_purchase_items must be between 1 and 7"):
        request_optional_int({"max_purchase_items": 0}, "max_purchase_items", 1, 7)
    assert request_int({"max_purchase_items": 0}, "max_purchase_items", 0, 0, 7) == 0
