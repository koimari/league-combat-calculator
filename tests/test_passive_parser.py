"""Front-door tests for the item passive parser.

The larger item-effect suites retain their campaign history.  This file gives
the production module a direct navigation point for parser changes.
"""

from src.calculator.data_fetcher import fetch_item_data
from src.calculator.passive_parser import _eval_simple_expr, parse_item_effect


def test_simple_expression_parser_accepts_numeric_operations() -> None:
    assert _eval_simple_expr("60 / 4 + 5") == 20.0


def test_item_parser_reads_a_cached_proc_effect() -> None:
    parsed = parse_item_effect("Rapid Firecannon", fetch_item_data())

    assert parsed is not None
    assert parsed["base"] == 40.0
    assert parsed["damage_type"] == "magic"
