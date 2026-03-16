"""Tests for Annie champion module."""

import pytest

from src.calculator.champions.annie import (
    _TIBBERS_AURA_AP_RATIO_PER_TICK,
    _TIBBERS_AURA_BASE_PER_TICK,
    _TIBBERS_AURA_TICK_INTERVAL,
)


# ---------------------------------------------------------------------------
# P: Pyromania (stun only, no damage)
# ---------------------------------------------------------------------------


class TestPassivePyromania:
    def test_passive_exists(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "P" in abilities

    def test_passive_no_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["P"]["total_raw"] == 0.0

    def test_passive_name_from_json(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["P"]["name"] == "Pyromania"


# ---------------------------------------------------------------------------
# Q: Disintegrate
# ---------------------------------------------------------------------------


class TestQDisintegrate:
    def test_q_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank5_no_ap(self, annie_data, parse_at) -> None:
        """Rank 5 Q with 0 AP should deal 260 magic damage."""
        _, abilities = parse_at(
            annie_data, 5, ap=0.0, ability_ranks={"Q": 5, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(260.0)

    def test_q_rank5_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 5 Q with 100 AP: 260 + 80 = 340 magic damage."""
        _, abilities = parse_at(
            annie_data, 5, ap=100.0, ability_ranks={"Q": 5, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(340.0)

    def test_q_rank1_base(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data, 1, ap=0.0, ability_ranks={"Q": 1, "R": 0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# W: Incinerate
# ---------------------------------------------------------------------------


class TestWIncinerate:
    def test_w_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 3)
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 3)
        assert abilities["W"]["cooldown"] > 0

    def test_w_rank5_no_ap(self, annie_data, parse_at) -> None:
        """Rank 5 W with 0 AP should deal 230 magic damage."""
        _, abilities = parse_at(
            annie_data, 5, ap=0.0, ability_ranks={"W": 5, "R": 0},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(230.0)

    def test_w_rank5_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 5 W with 100 AP: 230 + 80 = 310 magic damage."""
        _, abilities = parse_at(
            annie_data, 5, ap=100.0, ability_ranks={"W": 5, "R": 0},
        )
        assert abilities["W"]["total_raw"] == pytest.approx(310.0)


# ---------------------------------------------------------------------------
# E: Molten Shield (skipped — no offensive damage)
# ---------------------------------------------------------------------------


class TestEMoltenShield:
    def test_e_exists_with_name(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "E" in abilities
        assert abilities["E"]["name"] == "Molten Shield"

    def test_e_no_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert abilities["E"]["total_raw"] == 0.0


# ---------------------------------------------------------------------------
# R: Summon: Tibbers
# ---------------------------------------------------------------------------


class TestRSummonTibbers:
    def test_r_is_magic_damage(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_has_cooldown(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["cooldown"] > 0

    def test_r_rank3_burst_with_100ap(self, annie_data, parse_at) -> None:
        """Rank 3 R burst with 100 AP: 400 + 75 = 475 magic damage."""
        _, abilities = parse_at(
            annie_data, 16, ap=100.0, ability_ranks={"R": 3},
        )
        assert abilities["R"]["initial_burst"] == pytest.approx(475.0)

    def test_r_rank3_aura_per_tick_with_100ap(
        self, annie_data, parse_at,
    ) -> None:
        """Rank 3 R aura per tick with 100 AP: 4 + 1 = 5."""
        _, abilities = parse_at(
            annie_data, 16, ap=100.0, ability_ranks={"R": 3},
        )
        assert abilities["R"]["tibbers_aura"]["damage_per_tick"] == (
            pytest.approx(5.0)
        )

    def test_r_rank3_aura_total_5s(self, annie_data, parse_at) -> None:
        """Rank 3 R aura over 5s with 100 AP: 5 * 20 ticks = 100."""
        _, abilities = parse_at(
            annie_data, 16, ap=100.0, ability_ranks={"R": 3},
        )
        assert abilities["R"]["tibbers_aura"]["magic_damage"] == (
            pytest.approx(100.0)
        )

    def test_r_total_damage_burst_plus_aura(
        self, annie_data, parse_at,
    ) -> None:
        """Total R = burst + aura: 475 + 100 = 575 at rank 3, 100 AP."""
        _, abilities = parse_at(
            annie_data, 16, ap=100.0, ability_ranks={"R": 3},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(575.0)

    def test_r_aura_ticks(self, annie_data, parse_at) -> None:
        """Default 5s aura = 20 ticks."""
        _, abilities = parse_at(annie_data, 6)
        assert abilities["R"]["tibbers_aura"]["total_ticks"] == (
            pytest.approx(20.0)
        )

    def test_r_custom_aura_duration(self, annie_data, parse_at) -> None:
        """Custom aura duration changes total aura damage."""
        _, abilities = parse_at(
            annie_data, 16, ap=100.0,
            ability_ranks={"R": 3},
            champion_options={"tibbers_aura_seconds": 10.0},
        )
        # 10s = 40 ticks, 5 dmg/tick = 200 aura damage
        assert abilities["R"]["tibbers_aura"]["total_ticks"] == (
            pytest.approx(40.0)
        )
        assert abilities["R"]["tibbers_aura"]["magic_damage"] == (
            pytest.approx(200.0)
        )


# ---------------------------------------------------------------------------
# R passive: Magic Penetration
# ---------------------------------------------------------------------------


class TestRMagicPenetration:
    def test_r_stat_buff_has_magic_pen(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 6)
        assert "stat_buff" in abilities["R"]
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] > 0

    def test_r_rank1_magic_pen_10(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data, 6, ability_ranks={"R": 1},
        )
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] == (
            pytest.approx(10.0)
        )

    def test_r_rank3_magic_pen_20(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(
            annie_data, 16, ability_ranks={"R": 3},
        )
        assert abilities["R"]["stat_buff"]["magic_penetration_percent"] == (
            pytest.approx(20.0)
        )

    def test_r_pen_applied_before_q(self, annie_data, parse_at) -> None:
        """When R is ranked, Q should still calculate correctly.

        The magic pen is a stat buff — it doesn't change Q's raw damage,
        but it should be present in the R stat_buff for the fight engine.
        Q raw damage remains the same regardless of pen.
        """
        _, abilities_with_r = parse_at(
            annie_data, 9, ap=100.0, ability_ranks={"Q": 5, "R": 1},
        )
        _, abilities_no_r = parse_at(
            annie_data, 9, ap=100.0, ability_ranks={"Q": 5, "R": 0},
        )
        # Raw damage should be the same (pen affects post-mitigation)
        assert abilities_with_r["Q"]["total_raw"] == (
            abilities_no_r["Q"]["total_raw"]
        )
        # But R stat_buff should carry the pen
        assert abilities_with_r["R"]["stat_buff"][
            "magic_penetration_percent"
        ] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Pre-level-6 (no R)
# ---------------------------------------------------------------------------


class TestPreLevel6:
    def test_no_r_before_level_6(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5)
        assert "R" not in abilities

    def test_q_works_without_r(self, annie_data, parse_at) -> None:
        _, abilities = parse_at(annie_data, 5, ap=100.0)
        assert abilities["Q"]["total_raw"] > 0
