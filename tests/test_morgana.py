"""Morgana — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.champions import morgana
from src.calculator.champions.slot_cc import CC_PER_PART
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"Q": "roots them for a duration"}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Morgana")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert morgana.MODULE_CC == {
            "Q": "root",
            "W": "none",
            "R": CC_PER_PART,
            "P": "none",
            "E": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in morgana.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_r_declares_its_two_controls_per_part(self, cached):
        """Soul Shackles slows on contact and stuns only on the break."""
        text = cc_review.slot_text(cached, "R")
        assert "slowed by 20%" in text
        assert "become stunned" in text
        parts = morgana.parse_abilities(cached, 18, 100.0)["R"]["parts"]
        assert [part.cc_kind for part in parts] == ["slow", "stun"]
