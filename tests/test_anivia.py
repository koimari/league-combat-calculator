"""Tests for Anivia champion module."""

import pytest

# ---------------------------------------------------------------------------
# Q — Flash Frost
# ---------------------------------------------------------------------------


class TestQFlashFrost:
    """Q uses Total Magic Damage (pass-through + detonation combined)."""

    def test_q_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank5_no_ap(self, anivia_data, parse_at) -> None:
        """Rank 5 Q with 0 AP: 330 total magic damage."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ability_ranks={"Q": 5, "E": 1, "R": 1},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(330.0)

    def test_q_rank5_100ap(self, anivia_data, parse_at) -> None:
        """Rank 5 Q with 100 AP: 330 + 70 = 400."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 1, "R": 1},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(400.0)

    def test_q_has_magic_damage_key(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert "magic_damage" in abilities["Q"]
        assert abilities["Q"]["magic_damage"] == abilities["Q"]["total_raw"]


# ---------------------------------------------------------------------------
# W — Crystallize (skipped, no damage)
# ---------------------------------------------------------------------------


class TestWCrystallize:
    """W is a utility wall — should not appear in results."""

    def test_w_not_in_results(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert "W" not in abilities


# ---------------------------------------------------------------------------
# E — Frostbite
# ---------------------------------------------------------------------------


class TestEFrostbite:
    """E always uses Enhanced Damage (target assumed Chilled)."""

    def test_e_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["E"]["cooldown"] > 0

    def test_e_rank5_no_ap(self, anivia_data, parse_at) -> None:
        """Rank 5 E with 0 AP: 310 enhanced damage."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ability_ranks={"Q": 1, "E": 5, "R": 1},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(310.0)

    def test_e_rank5_100ap(self, anivia_data, parse_at) -> None:
        """Rank 5 E with 100 AP: 310 + 110 = 420."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 1, "E": 5, "R": 1},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(420.0)

    def test_e_has_magic_damage_key(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert "magic_damage" in abilities["E"]
        assert abilities["E"]["magic_damage"] == abilities["E"]["total_raw"]


# ---------------------------------------------------------------------------
# R — Glacial Storm
# ---------------------------------------------------------------------------


class TestRGlacialStorm:
    """R is a two-phase DoT toggle with configurable duration."""

    def test_r_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 16)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_cooldown_is_very_high(self, anivia_data, parse_at) -> None:
        """R should only be cast once (cooldown set to 999)."""
        _, abilities = parse_at(anivia_data, 16)
        assert abilities["R"]["cooldown"] >= 999.0

    def test_r_rank3_100ap_5s(self, anivia_data, parse_at) -> None:
        """Rank 3 R, 100 AP, 5s duration:
        3 ticks × (30 + 6.25) + 7 ticks × (90 + 18.75) = 108.75 + 761.25 = 870.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(870.0)

    def test_r_rank3_no_ap_5s(self, anivia_data, parse_at) -> None:
        """Rank 3 R, 0 AP, 5s duration:
        3 × 30 + 7 × 90 = 90 + 630 = 720.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(720.0)

    def test_r_minimum_duration_clamp(self, anivia_data, parse_at) -> None:
        """Duration below 1.5 should be clamped to 1.5 (3 initial ticks only)."""
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 0.5},
        )
        # 1.5s = 3 initial ticks only, 0 empowered
        # 3 × 30 = 90 (0 AP)
        assert abilities["R"]["total_raw"] == pytest.approx(90.0)

    def test_r_longer_duration(self, anivia_data, parse_at) -> None:
        """R at 10s duration: 3 initial + 17 empowered ticks, 0 AP, rank 3.
        3 × 30 + 17 × 90 = 90 + 1530 = 1620.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 10.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(1620.0)

    def test_r_has_magic_damage_key(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 16)
        assert "magic_damage" in abilities["R"]
        assert abilities["R"]["magic_damage"] == abilities["R"]["total_raw"]

    def test_r_default_duration_is_5s(self, anivia_data, parse_at) -> None:
        """Without champion_options, R uses the default 5s duration."""
        _, abilities_default = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
        )
        _, abilities_explicit = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert (
            abilities_default["R"]["total_raw"] == abilities_explicit["R"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# Passive — Rebirth (skipped)
# ---------------------------------------------------------------------------


class TestPassiveRebirth:
    """Passive is resurrection only — no damage, not in results."""

    def test_passive_not_in_results(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert "P" not in abilities


# ---------------------------------------------------------------------------
# Full combo verification
# ---------------------------------------------------------------------------


class TestFullCombo:
    """Verify the expected damage from the spec at rank 5/5/3, 100 AP."""

    def test_full_combo_damage(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(
            anivia_data,
            18,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(400.0)
        assert abilities["E"]["total_raw"] == pytest.approx(420.0)
        assert abilities["R"]["total_raw"] == pytest.approx(870.0)
        total = (
            abilities["Q"]["total_raw"]
            + abilities["E"]["total_raw"]
            + abilities["R"]["total_raw"]
        )
        assert total == pytest.approx(1690.0)
