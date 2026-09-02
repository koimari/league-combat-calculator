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
from src.calculator.champions.engine import CC_PER_PART
from src.calculator.data_fetcher import get_champion
from tests import cc_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"Q": "slowing them by 80% decaying over 2 seconds"}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Lulu")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert lulu.MODULE_CC == {
            "Q": "slow",
            "E": "none",
            "P": "none",
            "W": CC_PER_PART,
            "R": "knockup",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in lulu.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A constant kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = lulu.parse_abilities(cached, 18, 100.0)
        for slot, kind in lulu.MODULE_CC.items():
            if kind == CC_PER_PART:
                continue
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_wild_growths_knock_up_is_declared_and_rides_nothing(self, cached):
        """R knocks up on every cast, which is the slot's own constant, and
        the buff row prices no part with an instant for it to ride."""
        parsed = lulu.parse_abilities(cached, 18, 100.0)
        assert lulu.MODULE_CC["R"] == "knockup"
        assert "knocking up nearby enemies for 1 second" in cc_review.slot_text(
            cached, "R"
        )
        assert [part.cc_kind for part in cc_review.declared_parts(parsed, "R")] == [
            "knockup"
        ]

    def test_whimsy_names_itself_per_part_and_the_enemy_branch_answers(self, cached):
        """The polymorph is the enemy branch's, not the slot's: the self and
        ally casts buff and control nobody."""
        assert lulu.MODULE_CC["W"] == CC_PER_PART
        assert "polymorphs them into a harmless critter" in cc_review.slot_text(
            cached, "W"
        )
        enemy = lulu.parse_abilities(
            cached, 18, 100.0, champion_options={"lulu_whimsy_target": "enemy"}
        )
        (control,) = enemy["W"]["control_events"]
        assert control.kind == "polymorph"
        self_cast = lulu.parse_abilities(
            cached, 18, 100.0, champion_options={"lulu_whimsy_target": "self"}
        )
        assert not self_cast["W"].get("control_events")

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
