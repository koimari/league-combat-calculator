"""Tests for the Rell champion module."""

from functools import partial

import pytest

from src.calculator.champions import rell
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Rell's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Rell")
        assert rell.MODULE_CC == {
            "Q": "stun",
            "W": "immobilize",
            "E": "none",
            "R": "pull",
            "P": "none",
        }
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing them magic damage and stunning them for 0.65 seconds" in q_text
        # Both W forms apply two immobilize kinds at once.
        w_text = cc_review.slot_text(data, "W")
        assert "stuns them for 0.8 seconds, and knocks them up" in w_text
        assert "stuns the target for 0.6 seconds, and flings them 150 units" in w_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []
        assert "drags them towards her" in cc_review.slot_text(data, "R")
        # P is an on-hit rider on the auto stream.
        assert rell.MODULE_CC["P"] == "none"


def test_the_published_options_are_the_one_the_module_reads():
    """Rell's only choice is which W she casts."""
    from src.calculator.champions import get_champion_options_meta

    keys = {option["key"] for option in get_champion_options_meta("Rell")["options"]}
    assert keys == {"w_variant"}


# One rotation at level 18 into the bare 2000-HP dummy, and the same fight
# into an Ahri enemy, which is what produces the coupled participant ledger.
_closure_fight = partial(closure.fight, role="mid", duration=5.0)
_closure_enemy_fight = partial(
    closure.fight, role="top", enemy=closure.AHRI, target_health=None
)
_closure_parse = closure.abilities


# ---------------------------------------------------------------------------
# Rell — P on-hit, W shield, E modeled
# ---------------------------------------------------------------------------


class TestRell:
    """P deals 5% armor + 5% MR magic on-hit; W's Crash Down shield is a
    self shield; E Full Tilt is modeled."""

    def test_p_break_the_mold_on_hit(self) -> None:
        stats = closure.stats("Rell")
        expected_per_hit = 0.05 * (stats["armor"] + stats["magic_resistance"])
        data = _closure_fight(
            "Rell", include_autos=True, mode="time_based", duration=5.0
        )
        row = data["breakdown"]["on_hit_ability_passive"]
        assert row["damage_per_hit"] == pytest.approx(expected_per_hit, abs=0.1)
        assert row["total_damage"] == pytest.approx(
            row["damage_per_hit"] * row["count"], abs=closure.ROUNDING
        )

    def test_w_shield_emitted_as_self_shield(self) -> None:
        data = _closure_enemy_fight("Rell")
        shields = closure.main_support(data, "Ferromancy: Crash Down")
        assert shields
        assert shields[0]["target_scope"] == "self"
        stats = closure.stats("Rell")
        expected = extract_named(
            closure.ability_row("Rell", "W"),
            "Shield Strength",
            5,
            stats,
            closure.TARGET_2000,
        )
        assert float(shields[0]["amount"]) == pytest.approx(expected, abs=0.2)

    def test_e_full_tilt_is_modeled(self) -> None:
        data = _closure_fight("Rell")
        # 7% of the 2000-HP target + 3% per 100 AP (0 AP) at rank 5.
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(140.0)


def test_the_closed_slots_are_declared_modeled() -> None:
    """Every slot this module closed says so in its MODULE_COVERAGE."""
    coverage = closure.module_coverage("rell")
    assert {slot: coverage[slot] for slot in ("P", "E")} == {
        "P": "modeled",
        "E": "modeled",
    }
