"""Lucian — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import lucian
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {}

# Vigilance reads an immobilize someone else applied: an enemy champion
# within 1000 units being immobilized empowers Lucian's next two shots.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {"P": ["immobiliz"]}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Lucian")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert lucian.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "R": "none",
            "P": "none",
            "E": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in lucian.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = lucian.parse_abilities(cached, 18, 100.0)
        for slot, kind in lucian.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Lucian",
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
