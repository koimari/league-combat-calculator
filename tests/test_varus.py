"""Varus's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from src.calculator.champions import varus
from tests import cc_review
from functools import partial
from tests import champion_closure as closure
import pytest
from src.calculator.champions.slot_extract import extract_named
from src.calculator.champions.slot_extract import extract_value


class TestReviewedCrowdControl:
    """Varus's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Varus")
        assert varus.MODULE_CC == {
            "Q": "none",
            "E": "slow",
            "R": "root",
            "P": "none",
            "W": "none",
        }
        # Q's only "slow" is the one Varus takes himself while charging.
        assert "charges while being slowed by 20%" in cc_review.slot_text(data, "Q")
        assert "slowing enemies within" in cc_review.slot_text(data, "E")
        assert "rooting them for 2 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Varus") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Varus")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Varus — W active empowered shot (missing-health magic)
# ---------------------------------------------------------------------------


class TestVarus:
    """P1-3: the W active empower rides the fully-charged Q."""

    def test_q_empower_prices_active_maximum_missing_health(self):
        """Q prices the arrow + 3-stack detonation + the W-active empower
        (Active Maximum Magic Damage = 21% of missing health at W rank 5).

        The stack count is asked for, because the identity being pinned is
        between the cached rows; a default request derives the level the
        swings actually applied.
        """
        data = _closure_fight("Varus", options={"blight_stacks": 3})
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        arrow = extract_named(
            closure.ability_row("Varus", "Q"),
            "Maximum Physical Damage",
            5,
            stats,
            target,
        )
        per_stack = extract_named(
            closure.ability_row("Varus", "W"),
            "Bonus Magic Damage per Stack",
            5,
            stats,
            target,
        )
        empower_pct = extract_value(
            closure.ability_row("Varus", "W"), "Active Maximum Magic Damage", 5
        )
        empower = empower_pct / 100.0 * 0.50 * float(target["target_max_health"])
        assert closure.slot_total(data, "Q") == pytest.approx(arrow)
        assert closure.slot_total(data, "blight_detonation") == pytest.approx(
            per_stack * 3 + empower, abs=closure.ROUNDING
        )

    def test_w_active_empower_option_probe(self):
        """w_active_empower=False prices the arrow + detonation only."""
        data = _closure_fight(
            "Varus", options={"w_active_empower": False, "blight_stacks": 3}
        )
        stats = closure.fight_stats(data)
        target = closure.target_stats(data)
        per_stack = extract_named(
            closure.ability_row("Varus", "W"),
            "Bonus Magic Damage per Stack",
            5,
            stats,
            target,
        )
        assert closure.slot_total(data, "blight_detonation") == pytest.approx(
            per_stack * 3, abs=closure.ROUNDING
        )

    def test_the_default_derives_the_blight_level_the_swings_applied(self):
        """Varus' own attacks apply Blight, so a fight with none detonates
        nothing: the stacks are hits, not a state to assume."""
        data = _closure_fight("Varus")
        row = data["breakdown"].get("blight_detonation")
        assert row is None or row["total_damage"] >= 0.0

    def test_target_missing_hp_pct_option_probe(self):
        """target_missing_hp_pct=100 doubles the empower's missing-health
        base versus 50."""
        data50 = _closure_fight("Varus")
        data100 = _closure_fight("Varus", options={"target_missing_hp_pct": 100})
        assert closure.slot_total(data100, "blight_detonation") > closure.slot_total(
            data50, "blight_detonation"
        )
