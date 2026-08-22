"""Trundle's reviewed crowd control (``MODULE_CC``) and W's zone uptime.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import copy

import pytest

from src.calculator.champions import parse_champion_abilities, trundle
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.stats import calculate_total_stats
from tests import cc_review


class TestReviewedCrowdControl:
    """Trundle's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Trundle")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert trundle.MODULE_CC == {"Q": "slow", "E": "slow", "R": "none"}
        assert "slow the target by 75% for 0.1 seconds" in cc_review.slot_text(
            data, "Q"
        )
        # Subjugate drains resistances, health and size — real debuffs, but
        # none of them crowd control.
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Trundle") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Trundle")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def _w_grant(uptime=None):
    """W's applied bonus-attack-speed percentage at *uptime*."""
    data = next(
        entry
        for entry in fetch_champion_data().values()
        if entry.get("name") == "Trundle"
    )
    data = copy.deepcopy(data)
    stats = calculate_total_stats(copy.deepcopy(data), 18, [])
    abilities = parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        champion_stats=stats,
        champion_options=None if uptime is None else {"w_zone_uptime": uptime},
    )
    return abilities["W"]["stat_buff"]["bonus_attack_speed"]


class TestFrozenDomainUptime:
    """CF17: the zone is ground Trundle stands on, so the steroid is dialled.

    Attack speed is linear in the bonus percent, so scaling the granted
    percentage by the uptime IS the fight average — not an approximation.
    """

    def test_the_default_is_the_whole_window_the_module_always_assumed(self):
        assert _w_grant() == pytest.approx(90.0)
        assert _w_grant(1.0) == pytest.approx(90.0)

    def test_a_partial_uptime_scales_the_grant(self):
        assert _w_grant(0.5) == pytest.approx(45.0)
        assert _w_grant(0.0) == pytest.approx(0.0)

    def test_the_option_is_declared_with_its_range(self):
        option = next(row for row in trundle.OPTIONS if row["key"] == "w_zone_uptime")
        assert (option["default"], option["min"], option["max"]) == (1.0, 0.0, 1.0)
