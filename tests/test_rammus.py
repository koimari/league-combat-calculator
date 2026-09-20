"""Tests for the Rammus champion module."""

from src.calculator.champions import parse_champion_abilities, rammus
from src.calculator.champions.slot_cc import CC_PER_PART
from src.calculator.data_fetcher import get_champion
from tests import cc_review


def _w_part(autos):
    abilities = parse_champion_abilities(
        get_champion("Rammus"),
        18,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={"w_thorns_autos": autos},
    )
    (part,) = abilities["W"]["parts"]
    return part


class TestReviewedCrowdControl:
    """Rammus' reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rammus")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert rammus.MODULE_CC == {
            "Q": "immobilize",
            "W": CC_PER_PART,
            "E": "taunt",
            "R": "slow",
            "P": "none",
        }
        # Q applies two immobilize kinds in one cast, which is what the
        # un-narrowed "immobilize" states.
        q_text = cc_review.slot_text(data, "Q")
        assert "knocking them back 125 units" in q_text
        assert "enemies hit are then stunned and revealed for 0.4 seconds" in q_text
        # R slows unconditionally; the epicentre knock-up needs Soaring
        # Slam cast during Powerball, which this module does not price.
        r_text = cc_review.slot_text(data, "R")
        assert "slows them for 1.5 seconds" in r_text
        assert "if soaring slam was cast during powerball" in r_text
        # E taunts, and its only damage row is against monsters, so the
        # taunt rides the entry as a sourced ControlEvent rather than on
        # a part; P is a stat innate.
        assert "monsters are additionally dealt magic damage" in cc_review.slot_text(
            data, "E"
        )
        assert rammus.MODULE_CC["P"] == "none"

    def test_the_thorns_row_answers_only_where_the_ledger_can_hear_it(self):
        # W applies no control; it can only say so when it prices a single
        # reactive hit, because nothing sources the arrival times of the
        # enemy autos a longer row aggregates.
        assert rammus.MODULE_CC["W"] == CC_PER_PART
        assert (
            cc_review.control_words(cc_review.slot_text(cc_review.kit("Rammus"), "W"))
            == []
        )
        assert _w_part(0).cc_kind == "none"
        assert _w_part(1).cc_kind == "none"
        assert _w_part(5).cc_kind is None
