"""Reviewed crowd control for Master Yi (MODULE_CC): nothing he casts controls.

Alpha Strike controls nothing and lands after Master Yi reappears, 1.087
seconds after the cast starts.  Wuju Style's row prices an on-hit rider
as one direct hit, so it has no instant a marker could ride.
"""

from functools import partial

import pytest

from src.calculator.champions import master_yi, parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.healing import derive_self_healing
from tests import cc_review, rider_probe, row_review
from tests import champion_closure as closure

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


class TestReviewedCrowdControl:
    """Master Yi's reviewed crowd control, and the delay that carries Q.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Master Yi")
        assert master_yi.MODULE_CC == {
            "Q": "none",
            "P": "none",
            "W": "none",
            "E": "none",
            "R": "none",
        }
        assert master_yi.parse_abilities.cc_kinds == master_yi.MODULE_CC
        # Alpha Strike's only "unable to act" clause is about Master Yi.
        q_text = cc_review.slot_text(data, "Q")
        assert "master yi vanishes and becomes unable to act" in q_text
        assert cc_review.control_words(q_text) == []

    def test_alpha_strike_lands_when_master_yi_reappears(self):
        data = cc_review.kit("Master Yi")
        entry = data["abilities"]["Q"][0]
        assert "1.087 seconds total after the start of the cast" in (
            entry["effects"][1]["description"]
        )
        assert "Alpha Strike's primary damage applies after Master Yi reappears" in (
            entry["notes"]
        )
        (part,) = parse_champion_abilities(data, 18, 100.0, _RANKS)["Q"]["parts"]
        assert part.time_offset == 1.087
        assert part.cc_kind == "none"

    def test_wuju_style_is_an_on_hit_rider_with_no_part_of_its_own(self):
        """E's damage lands on the swings inside its window, so the row has
        no part; its reviewed "none" is the rider's."""
        data = cc_review.kit("Master Yi")
        assert master_yi.MODULE_CC["E"] == "none"
        assert "empowers his basic attacks within the next 5 seconds" in (
            cc_review.slot_text(data, "E")
        )
        entry = parse_champion_abilities(data, 18, 100.0, _RANKS)["E"]
        assert entry["parts"] == ()
        assert entry["total_raw"] == 0.0
        assert entry["on_hit"]["proc_window"] == 5.0
        assert entry["on_hit"]["damage_type"] == "true"

    def test_the_reviewed_kit_certifies_the_whole_fight(self):
        """Every slot answers "none", so no ability event goes unreviewed."""
        assert cc_review.unreviewed_ability_slots("Master Yi") == []
        coverage = cc_review.fimbulwinter_coverage("Master Yi")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestDoubleStrikeCrits:
    """P declares the crit clause its own cached sentence states."""

    def test_the_on_hit_row_carries_the_sourced_effectiveness(self):
        text = cc_review.slot_text(cc_review.kit("Master Yi"), "P")
        assert "the second strike applies on-hit effects" in text
        assert "is affected by critical strike modifiers" in text
        notes = cc_review.kit("Master Yi")["abilities"]["P"][0]["notes"].lower()
        assert "the second strike separately rolls a" in notes
        on_hit = row_review.entry("Master Yi", "passive")["on_hit"]
        assert (
            on_hit["crit_effectiveness"]
            == master_yi._SECOND_STRIKE_CRIT_EFFECTIVENESS
            == 1.0
        )

    def test_the_second_strike_crits_in_a_real_fight(self):
        """Cloak of Agility: 15% crit chance, no other stat moved.

        Full effectiveness at the 200% base multiplier is
        1 - 0.15 + 0.15 x 2.0 == 1.15 on the rider's own row.
        """
        plain = rider_probe.fight("Master Yi", deterministic=True)
        crit = rider_probe.fight(
            "Master Yi", items=["Cloak of Agility"], deterministic=True
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


# One rotation at level 18 into the bare 2000-HP dummy, and the same fight
# into an Ahri enemy, which is what produces the coupled participant ledger.
_closure_fight = partial(closure.fight, role="mid", duration=5.0)
_closure_enemy_fight = partial(
    closure.fight, role="top", enemy=closure.AHRI, target_health=None
)
_closure_parse = closure.abilities


# ---------------------------------------------------------------------------
# Master Yi — W Meditate heal stream
# ---------------------------------------------------------------------------


class TestMasterYi:
    """W: 8 ticks at 0.5s over the 4s channel, missing-health scaled."""

    def test_meditate_heal_rule_emits_eight_ticks(self) -> None:
        stats = closure.stats("MasterYi")
        heals = derive_self_healing(
            get_champion("MasterYi"),
            stats,
            {"W": {"rank": 5}},
            [],
            cast_timeline=[{"time": 0.0, "slot": "W"}],
            fight_duration_seconds=4.0,
        )
        meditate = [h for h in heals if h.get("source") == "Meditate"]
        assert len(meditate) == 8
        assert [round(float(h["time"]), 2) for h in meditate] == [
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
            3.5,
            4.0,
        ]
        # At full health the tick pays the Minimum Heal Per Tick row
        # (55 + 12.5% AP at rank 5).
        formula = meditate[0]["amount_formula"]
        assert float(formula(stats["health"], stats["health"])) == pytest.approx(55.0)

    def test_meditate_heals_in_fight(self) -> None:
        data = _closure_enemy_fight(
            "MasterYi",
            mode="time_based",
            duration=4.0,
            include_autos=False,
            enemy_ranks={"Q": 5, "W": 5, "E": 0, "R": 3},
        )
        heals = [
            h
            for h in data["combat"]["healing_events"]
            if h.get("attacker") == "main" and h.get("source") == "Meditate"
        ]
        assert len(heals) == 8
        assert all(float(h["raw_amount"]) >= 55.0 - 0.2 for h in heals)

    def test_w_slot_is_casted(self) -> None:
        data = _closure_fight("MasterYi")
        assert data["breakdown"]["W"]["total_damage"] == 0.0


def test_the_closed_slots_are_declared_modeled() -> None:
    """Every slot this module closed says so in its MODULE_COVERAGE."""
    coverage = closure.module_coverage("master_yi")
    assert {slot: coverage[slot] for slot in ("P", "W", "Q", "E")} == {
        "P": "modeled",
        "W": "modeled",
        "Q": "modeled",
        "E": "modeled",
    }
