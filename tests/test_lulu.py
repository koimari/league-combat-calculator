"""Lulu — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import lulu
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# Every control word the Wiki uses for the classes an item passive keys on.
CONTROL_WORDS = (
    "stun",
    "root",
    "snare",
    "charm",
    "fear",
    "flee",
    "taunt",
    "sleep",
    "suppress",
    "knock",
    "airborne",
    "pull",
    "slow",
    "immobiliz",
    "stasis",
    "drowsy",
    "cripple",
    "polymorph",
    "disarm",
    "silence",
)

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"Q": "slowing them by 80% decaying over 2 seconds"}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Lulu")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert lulu.MODULE_CC == {"Q": "slow", "E": "none"}
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in lulu.MODULE_CC.items():
            if kind != "none":
                continue
            hits = [
                word
                for word in CONTROL_WORDS
                if word in cc_review.slot_text(cached, slot)
            ]
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """Reviewing a kit only counts where the ledger can see it."""
        parsed = lulu.parse_abilities(cached, 18, 100.0)
        for slot, kind in lulu.MODULE_CC.items():
            parts = parsed[slot]["parts"]
            assert parts, slot
            assert {part.cc_kind for part in parts} == {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Lulu",
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
