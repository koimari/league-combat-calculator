"""Maokai — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import maokai
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {
    "Q": "slows them by 99% for 0.25 seconds",
    "W": "roots them for a duration",
    "E": "slowing them by 45% for 2 seconds",
    "R": "roots them for 0.75 : 2.25",
}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Maokai")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert maokai.MODULE_CC == {
            "Q": "slow",
            "W": "root",
            "E": "slow",
            "R": "root",
            "P": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = maokai.parse_abilities(cached, 18, 100.0)
        for slot, kind in maokai.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Maokai",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
            }
        )["timeline_coverage"]

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
        assert coverage["coarse_sources"] == []
