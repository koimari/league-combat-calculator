"""Varus's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from functools import partial

import pytest

from src.calculator.champions import varus
from src.calculator.champions.slot_extract import extract_named, extract_value
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Varus's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Varus")
        assert varus.MODULE_CC == {
            "Q": "none",
            "E": "slow",
            "R": "root",
            "P": "none",
            "W": "none",
        }
        # Q's only "slow" is the one Varus takes himself while charging.
        assert "charges while being slowed by 20%" in cc_review.slot_text(data, "Q")
        assert "slowing enemies within" in cc_review.slot_text(data, "E")
        assert "rooting them for 2 seconds" in cc_review.slot_text(data, "R")
