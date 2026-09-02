"""Kindred — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import get_champion_module_contract, kindred
from src.calculator.data_fetcher import get_champion
from tests import cc_review, coverage_truth, row_review

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"E": "slows them by 30%"}

# Wolf's frenzy attacks slow only "against monsters", never the champion
# this pair fight damages.
UNCONTROLLED_MENTIONS = {"W": ["slow"]}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Kindred")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert kindred.MODULE_CC == {"Q": "none", "W": "none", "E": "slow"}
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in kindred.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """Reviewing a kit only counts where the ledger can see it."""
        parsed = kindred.parse_abilities(cached, 18, 100.0)
        for slot, kind in kindred.MODULE_CC.items():
            parts = parsed[slot]["parts"]
            assert parts, slot
            assert {part.cc_kind for part in parts} == {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Kindred",
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


class TestCoverageMap:
    """Q prices a row; P prices nothing; R prices a heal, not damage.

    ``b03bbad9`` rewrote the set as ``{P, E}`` while adding the Mark stack
    row, turning Dance of Arrows into a reported gap and losing the
    ``no_damage`` reading the map had before it.  Mark of the Kindred is
    range and scaling state.  Lamb's Respite is a minimum-health floor plus
    a heal the ally scanner pays (375 to each teammate in the zone and to
    Kindred) — not enemy damage — so it emits an explicit ``no_damage``
    row, which is the same zero ``coverage_truth`` reads.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Kindred").coverage == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "no_damage",
        }
        assert coverage_truth.emitted("Kindred") == {
            "P": coverage_truth.ZERO,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.PRICED,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.ZERO,
        }

    def test_the_two_no_damage_slots_disclose_why_they_price_nothing(self):
        for slot, expected in (("passive", "state"), ("R", "not enemy damage")):
            entry = row_review.entry("Kindred", slot)
            assert entry["total_raw"] == 0.0
            assert expected in entry["detail"]
