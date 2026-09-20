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
from functools import partial
from tests import champion_closure as closure
from src.calculator.champions.slot_extract import extract_named

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
        assert kindred.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "slow",
            "P": "none",
            "R": "none",
        }
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
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = kindred.parse_abilities(cached, 18, 100.0)
        for slot, kind in kindred.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

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
        # E reads zero at the DEFAULT options because the pounce is no
        # longer priced at the cast: the shot marks and slows, and the
        # damage rides the sibling row the third marked attack earns.
        assert coverage_truth.emitted("Kindred") == {
            "P": coverage_truth.ZERO,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.PRICED,
            "E": coverage_truth.ZERO,
            "R": coverage_truth.ZERO,
        }
        assert coverage_truth.parse("Kindred")["E_pounce"]["total_raw"] > 0.0
        # A stated level puts it back on E, which is where it has always been.
        stated = coverage_truth.emitted("Kindred", e_stacks=3)
        assert stated["E"] == coverage_truth.PRICED
        assert "E_pounce" not in coverage_truth.parse("Kindred", e_stacks=3)

    def test_the_two_no_damage_slots_disclose_why_they_price_nothing(self):
        for slot, expected in (("passive", "state"), ("R", "not enemy damage")):
            entry = row_review.entry("Kindred", slot)
            assert entry["total_raw"] == 0.0
            assert expected in entry["detail"]


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Kindred — W Hunter's Vigor (100-stack next-auto heal)
# ---------------------------------------------------------------------------


class TestKindred:
    """P1-3: Hunter's Vigor heal receipt + the missing-health-scaled heal."""

    def test_hunters_vigor_receipt_only_at_100_stacks(self):
        """The W_vigor receipt is emitted only at the sourced 100-stack cap."""
        at_100 = _closure_parse("Kindred", options={"w_hunters_vigor_stacks": 100})
        assert "W_vigor" in at_100
        at_99 = _closure_parse("Kindred", options={"w_hunters_vigor_stacks": 99})
        assert "W_vigor" in at_99  # emitted as an explicit state row
        assert at_99["W_vigor"]["total_raw"] == 0.0

    def test_heal_fires_on_first_auto_scaled_by_missing_health(self):
        """At 100 stacks the next basic attack heals the missing-health
        share of 47 : 81 (based on level) — 81 at level 18."""
        # The bar is STATED full: unset it derives, and six seconds of
        # attacks do not fill it (champions/kindred.py's counter).
        data = _closure_fight(
            "Kindred",
            options={"w_hunters_vigor_stacks": 100},
            mode="time_based",
            duration=6,
            include_autos=True,
            enemy=closure.AHRI,
        )
        heals = closure.response_heals(data, "Hunter's Vigor")
        assert len(heals) == 1
        raw = float(heals[0].get("raw_amount", heals[0].get("amount", 0.0)))
        assert 0.0 < raw <= 81.0 + 0.6
        assert raw > 0.0  # the fight's own incoming damage creates missing health

    def test_wolf_frenzy_damage_keeps_sourced_row(self):
        """W damage stays the sourced Magic Damage row over w_attacks."""
        data = _closure_fight("Kindred")
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        per = extract_named(
            closure.ability_row("Kindred", "W"), "Magic Damage", 5, stats, target
        )
        assert closure.slot_total(data, "W") == pytest.approx(
            per * 3, abs=closure.ROUNDING
        )
