"""Katarina — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import katarina
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Katarina")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert katarina.MODULE_CC == {
            "Q": "none",
            "E": "none",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in katarina.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = katarina.parse_abilities(cached, 18, 100.0)
        for slot, kind in katarina.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Katarina",
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


def test_the_dagger_ult_authors_its_order_in_the_parts_not_a_flag():
    """R's blades ride an authored cadence, and claim no certification.

    ``event_order_certified`` is a string vocabulary ("single_hit" /
    "auto_stack_proc") every reader compares against; a bool never
    matched one, so the row carries none.  Fifteen daggers over a
    2.5-second channel is neither kind anyway — the schedule the ledger
    reads is the parts' own ``time_offset``/``hit_interval``.
    """
    from tests import row_review

    entry = row_review.entry("Katarina", "R", p_daggers=2, r_daggers=15)
    assert "event_order_certified" not in entry
    assert [
        (part.count, part.time_offset, part.hit_interval) for part in entry["parts"]
    ] == [
        (15, 0.166, 2.5 / 15),
        (15, 0.166, 2.5 / 15),
    ]
