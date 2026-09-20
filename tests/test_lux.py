"""Lux — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

from functools import partial

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import lux
from src.calculator.champions.slot_extract import extract_named
from src.calculator.data_fetcher import get_champion
from tests import cc_review
from tests import champion_closure as closure

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {
    "Q": "roots them for 2 seconds",
    "E": "slow nearby enemies",
}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Lux")


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert lux.MODULE_CC == {
            "Q": "root",
            "E": "slow",
            "R": "none",
            "P": "none",
            "W": "none",
        }
        for slot, phrase in QUOTED.items():
            assert phrase in cc_review.slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in lux.MODULE_CC.items():
            if kind != "none":
                continue
            hits = cc_review.any_control_hits(cached, slot)
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """A declared kind lands on every part of the slot's row that can
        carry it; the roster census counts the slots with no such part."""
        parsed = lux.parse_abilities(cached, 18, 100.0)
        for slot, kind in lux.MODULE_CC.items():
            parts = cc_review.declared_parts(parsed, slot)
            assert {part.cc_kind for part in parts} <= {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Lux",
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


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Lux — P Illumination procs + W Prismatic Barrier (double) shield
# ---------------------------------------------------------------------------


class TestLux:
    """P1-3: the P proc and the W two-stack shield join the packet."""

    def test_illumination_procs_price_sourced_per_level_damage(self):
        """P: 30 : 200 (based on level) + 35% AP per proc, default 3 procs."""
        data = _closure_fight("Lux")
        stats = closure.fight_stats(data)
        per_proc = extract_named(
            closure.ability_row("Lux", "P"),
            "Per-Level Scaling",
            18,
            stats,
            closure.target_stats(data),
        )
        assert per_proc == pytest.approx(200.0)
        row = data["breakdown"]["passive"]
        assert row["count"] == 3
        assert float(row["total_damage"]) == pytest.approx(per_proc * 3)

    def test_illumination_procs_option_probe(self):
        """p_illumination_procs=1 prices exactly one proc."""
        data = _closure_fight("Lux", options={"p_illumination_procs": 1})
        stats = closure.fight_stats(data)
        per_proc = extract_named(
            closure.ability_row("Lux", "P"),
            "Per-Level Scaling",
            18,
            stats,
            closure.target_stats(data),
        )
        assert closure.slot_total(data, "passive") == pytest.approx(per_proc)

    def test_w_prismatic_barrier_shields_maximum_shield(self):
        """W shields Lux for the sourced Maximum Shield (throw + return)."""
        data = _closure_fight("Lux", mode="time_based", duration=6, enemy=closure.AHRI)
        rows = closure.response_shields(data, "Prismatic Barrier")
        assert len(rows) == 1
        expected = extract_named(
            closure.ability_row("Lux", "W"),
            "Maximum Shield",
            5,
            closure.fight_stats(data),
            {},
        )
        assert rows[0]["amount"] == pytest.approx(expected)
