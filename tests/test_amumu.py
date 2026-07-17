"""Tests for Amumu champion ability parsing and damage calculation."""

import pytest

from src.calculator.ability_spec import parts_raw_total

from src.calculator.stats import calculate_total_stats
from src.calculator.champions.amumu import _CURSE_BONUS_FRACTION
from src.calculator.damage import calculate_fight_damage

# Default target stats used when W's %maxHP damage needs resolving.
_TARGET = {"target_max_health": 2000.0}


class TestPassiveCursedTouch:
    """Tests for P (Cursed Touch) — damage amplifier, no direct damage."""

    def test_passive_deals_no_damage(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["P"]["total_raw"] == 0.0

    def test_passive_has_true_damage_type(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["P"]["damage_type"] == "true"


class TestQBandageToss:
    """Tests for Q (Bandage Toss) — single-cast magic damage."""

    def test_q_damage_type_is_mixed_with_curse(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["Q"]["damage_type"] == "mixed"

    def test_q_damage_type_is_magic_without_curse(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(
            amumu_data,
            9,
            target_stats=_TARGET,
            champion_options={"target_cursed": False},
        )
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_uses_recharge_cooldown(self, amumu_data, parse_at) -> None:
        """Q cooldown should be the recharge timer (16-12s), not the 3s cast CD."""
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        # At level 9 with W-max order, Q is rank 2 → recharge = 15s
        assert abilities["Q"]["cooldown"] >= 12.0

    def test_q_rank1_damage_matches_json(self, amumu_data, parse_at) -> None:
        """Q rank 1 single cast = 70 + 85% AP, with 0 AP = 70."""
        _, abilities = parse_at(
            amumu_data,
            1,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(
            70.0, abs=0.5
        )

    def test_q_with_ap_scaling(self, amumu_data, parse_at) -> None:
        """Q with 200 AP: 70 + 85%*200 = 70 + 170 = 240 per cast."""
        _, abilities = parse_at(
            amumu_data,
            1,
            ap=200.0,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(
            240.0, abs=0.5
        )

    def test_q_curse_adds_true_damage(self, amumu_data, parse_at) -> None:
        """With curse, Q should have bonus true damage = 10% of magic."""
        _, abilities = parse_at(
            amumu_data,
            1,
            champion_options={"target_cursed": True},
            target_stats=_TARGET,
        )
        magic = parts_raw_total(abilities["Q"]["parts"], "magic")
        true_dmg = parts_raw_total(abilities["Q"]["parts"], "true")
        assert true_dmg == pytest.approx(magic * _CURSE_BONUS_FRACTION, rel=0.01)

    def test_q_reports_single_cast_damage(self, amumu_data, parse_at) -> None:
        """Q should report damage for one cast only (fight engine handles repetition)."""
        _, abilities = parse_at(
            amumu_data,
            1,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        # Single cast at rank 1 with 0 AP = 70, not 140 (2 charges)
        assert parts_raw_total(abilities["Q"]["parts"], "magic") == pytest.approx(
            70.0, abs=0.5
        )


class TestWDespair:
    """Tests for W (Despair) — toggle DoT with %maxHP scaling."""

    def test_w_damage_type_is_mixed_with_curse(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["W"]["damage_type"] == "mixed"

    def test_w_default_6_ticks(self, amumu_data, parse_at) -> None:
        """Default 3 seconds / 0.5s per tick = 6 ticks."""
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["W"]["total_ticks"] == 6

    def test_w_seconds_configurable(self, amumu_data, parse_at) -> None:
        _, ab5 = parse_at(
            amumu_data,
            9,
            target_stats=_TARGET,
            champion_options={"w_seconds": 5.0, "target_cursed": False},
        )
        assert ab5["W"]["total_ticks"] == 10

    def test_w_has_zero_cooldown(self, amumu_data, parse_at) -> None:
        """W is a toggle — no cooldown."""
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["W"]["cooldown"] == 0.0

    def test_w_scales_with_target_max_hp(self, amumu_data, parse_at) -> None:
        """W damage should increase with higher target max HP."""
        _, ab_low = parse_at(
            amumu_data,
            9,
            target_stats={"target_max_health": 1000.0},
            champion_options={"target_cursed": False},
        )
        _, ab_high = parse_at(
            amumu_data,
            9,
            target_stats={"target_max_health": 4000.0},
            champion_options={"target_cursed": False},
        )
        assert ab_high["W"]["total_raw"] > ab_low["W"]["total_raw"]

    def test_w_rank1_per_tick_no_ap(self, amumu_data, parse_at) -> None:
        """W rank 1: 5 flat + 0.5% of 2000 max HP = 5 + 10 = 15 per tick."""
        _, abilities = parse_at(
            amumu_data,
            3,  # level 3: W rank 1 (Q→W→E skill order)
            champion_options={"w_seconds": 0.5, "target_cursed": False},
            target_stats=_TARGET,
        )
        # 1 tick at rank 1: 5 + 0.5% * 2000 = 5 + 10 = 15
        assert parts_raw_total(abilities["W"]["parts"], "magic") == pytest.approx(
            15.0, abs=1.0
        )

    def test_w_rank5_per_tick_with_ap(self, amumu_data, parse_at) -> None:
        """W rank 5 with 200 AP: 5 + (1% + 0.5%) * 2000 = 5 + 30 = 35."""
        _, abilities = parse_at(
            amumu_data,
            13,
            ap=200.0,  # level 13: W rank 5
            champion_options={"w_seconds": 0.5, "target_cursed": False},
            target_stats=_TARGET,
        )
        # 1 tick: 5 + (1.0% + 0.25%*200/100) * 2000 = 5 + (1.0% + 0.5%) * 2000
        #       = 5 + 1.5% * 2000 = 5 + 30 = 35
        assert parts_raw_total(abilities["W"]["parts"], "magic") == pytest.approx(
            35.0, abs=1.0
        )


class TestETantrum:
    """Tests for E (Tantrum) — single-hit magic damage."""

    def test_e_damage_type(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["E"]["damage_type"] == "mixed"  # cursed by default

    def test_e_has_cooldown(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        assert abilities["E"]["cooldown"] > 0

    def test_e_rank1_damage_no_ap(self, amumu_data, parse_at) -> None:
        """E rank 1 = 65 + 50%*0 = 65 magic damage."""
        _, abilities = parse_at(
            amumu_data,
            5,  # level 5: E rank 1
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(
            65.0, abs=0.5
        )

    def test_e_with_200_ap(self, amumu_data, parse_at) -> None:
        """E rank 1 with 200 AP: 65 + 100 = 165."""
        _, abilities = parse_at(
            amumu_data,
            5,
            ap=200.0,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["E"]["parts"], "magic") == pytest.approx(
            165.0, abs=0.5
        )


class TestRCurseOfTheSadMummy:
    """Tests for R (Curse of the Sad Mummy) — single-hit magic damage."""

    def test_r_damage_type(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 6, target_stats=_TARGET)
        assert abilities["R"]["damage_type"] == "mixed"  # cursed by default

    def test_r_has_cooldown(self, amumu_data, parse_at) -> None:
        _, abilities = parse_at(amumu_data, 6, target_stats=_TARGET)
        assert abilities["R"]["cooldown"] > 0

    def test_r_rank1_damage_no_ap(self, amumu_data, parse_at) -> None:
        """R rank 1: 200 + 80%*0 = 200 magic damage."""
        _, abilities = parse_at(
            amumu_data,
            6,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["R"]["parts"], "magic") == pytest.approx(
            200.0, abs=0.5
        )

    def test_r_rank3_with_200_ap(self, amumu_data, parse_at) -> None:
        """R rank 3 with 200 AP: 400 + 160 = 560 magic damage."""
        _, abilities = parse_at(
            amumu_data,
            16,
            ap=200.0,
            champion_options={"target_cursed": False},
            target_stats=_TARGET,
        )
        assert parts_raw_total(abilities["R"]["parts"], "magic") == pytest.approx(
            560.0, abs=0.5
        )


class TestCurseIntegration:
    """Tests for Cursed Touch bonus true damage across all abilities."""

    def test_all_magic_abilities_get_curse_bonus(self, amumu_data, parse_at) -> None:
        """Every magic-damage ability should have bonus true damage."""
        _, abilities = parse_at(
            amumu_data,
            9,
            target_stats=_TARGET,
            champion_options={"target_cursed": True},
        )
        for key in ("Q", "W", "E"):
            assert (
                parts_raw_total(abilities[key]["parts"], "true") > 0
            ), f"{key} missing curse true damage"

    def test_curse_off_no_true_damage(self, amumu_data, parse_at) -> None:
        """With curse off, abilities should have no true_damage key."""
        _, abilities = parse_at(
            amumu_data,
            9,
            target_stats=_TARGET,
            champion_options={"target_cursed": False},
        )
        for key in ("Q", "W", "E"):
            assert "true_damage" not in abilities[key], f"{key} has true_damage"

    def test_curse_bonus_is_10_percent(self, amumu_data, parse_at) -> None:
        """Curse bonus true damage should be exactly 10% of magic damage."""
        _, abilities = parse_at(
            amumu_data,
            9,
            ap=100.0,
            target_stats=_TARGET,
            champion_options={"target_cursed": True},
        )
        for key in ("Q", "W", "E"):
            magic = parts_raw_total(abilities[key]["parts"], "magic")
            true_dmg = parts_raw_total(abilities[key]["parts"], "true")
            assert true_dmg == pytest.approx(
                magic * 0.10, rel=0.01
            ), f"{key}: true={true_dmg}, expected 10% of magic={magic}"


class TestFightEngineIntegration:
    """Tests for Amumu in the fight engine."""

    def test_fight_engine_returns_result(self, amumu_data, parse_at) -> None:
        stats, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        result = calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        assert result["total_damage"] > 0

    def test_passive_zero_in_breakdown(self, amumu_data, parse_at) -> None:
        """P should appear but contribute 0 damage in breakdown."""
        stats, abilities = parse_at(amumu_data, 9, target_stats=_TARGET)
        result = calculate_fight_damage(
            champion_stats=stats,
            ability_damages=abilities,
            target_health=2000,
            target_armor=100,
            target_magic_resistance=60,
            fight_duration_seconds=5.0,
            one_rotation=True,
        )
        p_entry = result["breakdown"].get("P", {})
        assert p_entry.get("total_damage", 0.0) == 0.0
