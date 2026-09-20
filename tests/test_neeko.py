"""Tests for the Neeko champion module."""

import json
from functools import partial

import pytest

from src.calculator.champions import neeko
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Neeko's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Neeko")
        assert neeko.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "root",
            "R": "stun",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "roots them for a duration" in cc_review.slot_text(data, "E")
        # R's leap knocks up and deals nothing; the landing burst is the
        # damaging part and it stuns, so the stun is the kind that rides it.
        r_text = cc_review.slot_text(data, "R")
        assert "knocking up nearby enemies for 0.6 seconds" in r_text
        assert "deals magic damage to nearby enemies and stuns them" in r_text
        # P is absent: Inherent Glamour is a disguise that damages nothing.
        assert neeko.MODULE_CC["P"] == "none"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Neeko") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Neeko")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Neeko — Q three-burst chain + R Pop Blossom shield
# ---------------------------------------------------------------------------


class TestNeeko:
    """P1-3: Q re-blooms and the game-file R shield."""

    def test_q_prices_initial_plus_two_reblooms(self):
        """Q: Initial + 2 x Subsequent == the Total Maximum Magic Damage."""
        data = _closure_fight("Neeko")
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        total = extract_named(
            closure.ability_row("Neeko", "Q"),
            "Total Maximum Magic Damage",
            5,
            stats,
            target,
        )
        assert total == pytest.approx(530.0)
        assert closure.slot_total(data, "Q") == pytest.approx(
            total, abs=closure.ROUNDING
        )

    def test_r_shield_prices_game_file_amount(self):
        """R shield: ShieldAmount + ShieldPerChampion (1 nearby enemy) +
        115% AP, 2s (neeko.bin.json NeekoR)."""
        data = _closure_fight(
            "Neeko", mode="time_based", duration=6, enemy=closure.AHRI
        )
        rows = closure.response_shields(data, "Pop Blossom")
        assert len(rows) == 1
        # rank 3: 175 + 80 (+ 75% + 40% AP) == 255 at 0 AP
        assert rows[0]["amount"] == pytest.approx(255.0)
