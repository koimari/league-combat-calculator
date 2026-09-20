"""Skarner's reviewed crowd control (``MODULE_CC``).

The roster-wide half of this review lives in ``test_module_cc_census.py``.
"""

from functools import partial

import pytest

from src.calculator.champions import skarner
from src.calculator.champions.slot_extract import extract_named, extract_value
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Skarner's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Skarner")
        assert skarner.MODULE_CC == {
            "P": "none",
            "Q": "slow",
            "W": "slow",
            "E": "stun",
            "R": "suppression",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []
        assert "slowing afflicted enemies by 40%" in cc_review.slot_text(data, "Q")
        assert "slow them by 20% for 1 second" in cc_review.slot_text(data, "W")
        # E's suppression is the grab that precedes the damage; the stun is
        # what lands with it, on terrain collision.
        assert "stunning them for 1.1 seconds" in cc_review.slot_text(data, "E")
        assert "suppress them for 1.5 seconds" in cc_review.slot_text(data, "R")


def test_the_published_options_are_the_one_the_module_reads():
    """Skarner's only choice is which Q he casts."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Skarner")["options"]}
    assert keys == {"q_variant"}


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Skarner — W 8%-max-HP shield + E Ixtal's Impact damage
# ---------------------------------------------------------------------------


class TestSkarner:
    """P1-3: W shield and the E formula-slot inconsistency."""

    def test_w_shield_is_8_percent_max_health(self):
        """W shields Skarner for 8% of his maximum health for 2.5s."""
        data = _closure_fight(
            "Skarner", mode="time_based", duration=6, enemy=closure.AHRI
        )
        rows = closure.response_shields(data, "Seismic Bastion")
        assert len(rows) == 1
        expected = 0.08 * float(closure.fight_stats(data)["health"])
        assert rows[0]["amount"] == pytest.approx(expected)

    def test_e_prices_terrain_collision_damage(self):
        """E: Physical Damage row (flat + 120% bAD + 6% of Skarner's max
        health) — the formula slot now matches MODULE_COVERAGE."""
        data = _closure_fight("Skarner")
        stats = closure.fight_stats(data)
        flat = extract_named(
            closure.ability_row("Skarner", "E"), "Physical Damage", 5, stats, {}
        )
        max_hp_pct = extract_value(
            closure.ability_row("Skarner", "E"), "Physical Damage", 5, 2
        )
        expected = flat + max_hp_pct / 100.0 * float(stats["health"])
        assert closure.slot_total(data, "E") == pytest.approx(expected, abs=0.6)
