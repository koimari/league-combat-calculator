"""Tests for the Nautilus champion module."""

from functools import partial

import pytest

from src.calculator.champions import nautilus
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Nautilus' reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nautilus")
        assert nautilus.MODULE_CC == {
            "Q": "immobilize",
            "W": "none",
            "E": "slow",
            "R": "immobilize",
            "P": "root",
        }
        # Q and R each apply two immobilize kinds in one cast, which is
        # what the un-narrowed "immobilize" states.
        q_text = cc_review.slot_text(data, "Q")
        assert "stuns them for 1 second" in q_text
        assert "drags them toward nautilus" in q_text
        r_text = cc_review.slot_text(data, "R")
        assert "knocked up for 1 second, and stunned for a duration" in r_text
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slows them by an amount that decays" in cc_review.slot_text(data, "E")
