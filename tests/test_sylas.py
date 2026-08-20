"""Sylas's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, sylas
from tests import cc_review, rider_probe, row_review


class TestReviewedCrowdControl:
    """Sylas' whole kit is reviewed once Q's lump declares its own time."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sylas")
        assert sylas.MODULE_CC == {"W": "none", "E": "immobilize", "Q": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slowing them for 1.5 seconds" in cc_review.slot_text(data, "Q")
        # Abduct stuns on the chain hit and knocks up on arrival - two
        # immobilize kinds, so the reviewed kind is the un-narrowed one.
        assert "stun them for 0.5 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 0.5 seconds" in cc_review.slot_text(data, "E")

    def test_chain_lash_declares_its_lumped_row_at_the_cast(self):
        """The packet prices the lash and the 0.6s-delayed explosion in one
        part, so the row states when the ledger sees it instead of being
        split into the two cached rows - which re-prices the fight."""
        from src.calculator.champions import parse_champion_abilities
        from src.calculator.stats import calculate_total_stats

        data = cc_review.kit("Sylas")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.time_offset for part in parsed["Q"]["parts"]] == [0.0]
        assert sylas.SLOTS.packet_spec["slots"]["Q"]["base"] == [
            100.0,
            175.0,
            250.0,
            325.0,
            400.0,
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sylas") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sylas")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPetriciteBurst:
    """P: the Unshackled empowered attack, once per stocked stack."""

    def test_the_cached_entry_carries_no_number_at_all(self):
        """Why both ratios are module constants rather than cached reads."""
        assert [
            leveling
            for effect in cc_review.kit("Sylas")["abilities"]["P"][0]["effects"]
            for leveling in effect.get("leveling") or []
        ] == []
        text = cc_review.slot_text(cc_review.kit("Sylas"), "P")
        assert "130% ad (+ 30% ap) magic damage to the primary target" in text
        assert "stacking up to 3 times" in text

    def test_the_per_hit_damage_is_that_sentence(self):
        """130% of 200 AD + 30% of 200 AP = 320.0 magic."""
        on_hit = row_review.entry("Sylas", "passive")["on_hit"]
        assert on_hit["damage_type"] == "magic"
        assert on_hit["damage_per_hit"] == pytest.approx(1.30 * 200 + 0.30 * 200)
        assert on_hit["max_procs"] == 3

    def test_three_stocked_attacks_reach_the_fight_total(self):
        result = rider_probe.fight("Sylas")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Petricite Burst (on-hit)"
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(218.4, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_spending_no_stack_prices_nothing(self):
        result = rider_probe.fight("Sylas", champion_options={"p_procs": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]


class TestTheSlotThatStaysOutOfScope:
    """R (Hijack) casts a copy of another champion's ultimate."""

    def test_the_module_names_the_missing_axis(self):
        assert get_champion_module_contract("Sylas").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "out_of_scope",
        }
        assert "casts a copy of another champion's" in sylas.__doc__
        assert "an axis the engine has no surface for" in sylas.__doc__
