"""The picker's own question, asked of one cached item record.

``item_model_coverage`` takes an item name and the lanes the caller needs
answered, and the item tests all ask the attacker lane -- the lane the
picker takes -- so they ask it through here rather than each naming the
lane set again.

This is a test helper, not a test module: it holds no assertions.
"""

from src.calculator.item_coverage import ATTACKER_LANES, item_model_coverage


def attacker_coverage(item: dict) -> dict:
    """The attacker-lane public payload for one cached item record."""
    return item_model_coverage(str(item["name"]), ATTACKER_LANES).as_payload()
