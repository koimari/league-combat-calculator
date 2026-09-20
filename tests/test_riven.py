"""Tests for the Riven champion module."""

import json
from functools import partial

import pytest

from src import app as app_module
from src.calculator.champions import riven
from src.calculator.champions.slot_extract import extract_named
from tests import cc_review, rider_probe, row_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Riven's reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Riven")
        assert riven.MODULE_CC == {
            "Q": "none",
            "W": "stun",
            "R": "none",
            "P": "none",
            "E": "none",
        }
        # Q prices one slash of Broken Wings; only the third cast adds a
        # knock back, and this module does not price that specific one.
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing physical damage to enemies struck within an area" in q_text
        assert "knocking back enemies hit 75 units" in q_text
        assert riven.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            45.0,
            75.0,
            105.0,
            135.0,
            165.0,
        ]
        assert "stunning them for 0.75 seconds" in cc_review.slot_text(data, "W")
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # E and P carry no control word at all.  R_buff is a result key
        # rather than a champion slot, so MODULE_CC has no entry for it.
        for slot in ("E", "P"):
            assert cc_review.any_control_hits(data, slot) == [], slot
        assert "R_buff" not in riven.MODULE_CC


class TestRunicBladeCrits:
    """P declares the crit clause its own cached sentence states."""

    def test_the_on_hit_row_carries_the_sourced_effectiveness(self):
        text = cc_review.slot_text(cc_review.kit("Riven"), "P")
        assert "the bonus damage is affected by critical strike modifiers" in text
        on_hit = row_review.entry("Riven", "passive")["on_hit"]
        assert (
            on_hit["crit_effectiveness"] == riven._RUNIC_BLADE_CRIT_EFFECTIVENESS == 1.0
        )

    def test_the_rider_crits_in_a_real_fight(self):
        """Cloak of Agility: 15% crit chance, no other stat moved.

        Full effectiveness at the 200% base multiplier is
        1 - 0.15 + 0.15 x 2.0 == 1.15 on the rider's own row.
        """
        plain = rider_probe.fight("Riven", deterministic=True)
        crit = rider_probe.fight(
            "Riven", items=["Cloak of Agility"], deterministic=True
        )
        assert crit["champion_stats"]["critical_strike_chance"] == pytest.approx(15.0)
        assert crit["champion_stats"]["attack_damage"] == pytest.approx(
            plain["champion_stats"]["attack_damage"]
        )
        assert crit["breakdown"][rider_probe.RIDER_ROW][
            "total_damage"
        ] == pytest.approx(
            1.15 * plain["breakdown"][rider_probe.RIDER_ROW]["total_damage"], abs=0.1
        )


# One rotation at level 18 into the bare 2000-HP dummy; slot rows are parsed
# against the shared reference stat block.
_closure_fight = partial(closure.fight, role="top")
_closure_parse = closure.reference_abilities


# ---------------------------------------------------------------------------
# Riven — R1 Blade of the Exile bonus-AD buff
# ---------------------------------------------------------------------------


class TestRiven:
    """P1-3: the R1 AD steroid is expressed and feeds every physical slot."""

    def test_r1_buff_entry_exists_and_scales_bonus_ad(self):
        """The BUFF-phase R_buff entry prices +20% of bonus AD."""
        abilities = _closure_parse("Riven", stats={"bonus_attack_damage": 50.0})
        buff = abilities["R_buff"]
        assert buff["stat_buff"]["bonus_attack_damage"] == pytest.approx(10.0)

    def test_no_item_fight_totals_unchanged(self):
        """At 0 bonus AD the buff is 0, so the no-item burst keeps its
        sourced packet values."""
        data = _closure_fight("Riven")
        assert closure.slot_total(data, "Q") == pytest.approx(165.0)
        assert closure.slot_total(data, "W") == pytest.approx(185.0)
        assert closure.slot_total(data, "R") == pytest.approx(600.0)

    def test_ad_item_probe_buffs_every_physical_slot(self):
        """With a Long Sword (10 AD), R1 adds 20% x 10 == 2 bonus AD and
        Q/W/R scale off it (the ult-window understatement is closed)."""
        data = _closure_fight("Riven", enemy=None)
        payload = {
            "champion": "Riven",
            "level": 18,
            "items": ["Long Sword"],
            "role": "top",
            "ability_ranks": dict(closure.RANKS),
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "champion_options": {},
            "target_health": 2000.0,
            "target_armor": 0,
            "target_mr": 0,
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        stats = dict(data["champion_stats"])
        bonus_ad = float(stats["bonus_attack_damage"])
        assert bonus_ad >= 10.0  # Long Sword
        # The response stats already include the R1 buff (+20% of bonus
        # AD, factored at cast), so the sourced Q row resolves exactly.
        q_expected = extract_named(
            closure.ability_row("Riven", "Q"),
            "Physical Damage",
            5,
            stats,
            closure.target_stats(data),
        )
        assert q_expected > 165.0  # the buff raised Q above the 0-bAD base
        assert closure.slot_total(data, "Q") == pytest.approx(q_expected, abs=0.6)
