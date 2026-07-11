"""Tests for the Ahri champion module.

Hand-derived ability values at specific AP breakpoints (values re-derived from
the 16.13.1 JSON), plus an Ahri fight-level check of the Actualizer ability amp
(the accessor itself is unit-tested in test_item_effects.py).
"""

import pytest

from src.calculator.champions.ahri import (
    parse_abilities as parse_ahri_abilities,
)
from src.calculator.damage import calculate_fight_damage


class TestParseAhriAbilities:
    """Tests for Ahri ability parsing with specific AP values."""

    @pytest.fixture
    def ahri_data(self) -> dict:
        from src.calculator.data_fetcher import get_champion

        return get_champion("Ahri")

    def test_q_rank3_with_60ap(self, ahri_data: dict) -> None:
        # JSON (16.13.1): Q "Damage Per Pass" rank 3 = 85 + 50% AP.
        # 85 + 0.5 * 60 = 115 for both the magic and true damage passes.
        abilities = parse_ahri_abilities(ahri_data, 6, 60)
        q = abilities["Q"]
        assert q["rank"] == 3
        assert abs(q["magic_damage"] - 115.0) < 0.1
        assert abs(q["true_damage"] - 115.0) < 0.1

    def test_w_rank1_with_60ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 6, 60)
        w = abilities["W"]
        assert w["rank"] == 1
        assert abs(w["initial_damage"] - 64.0) < 0.1
        assert abs(w["subsequent_damage"] - 25.6) < 0.1

    def test_e_rank1_with_60ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 6, 60)
        e = abilities["E"]
        assert abs(e["magic_damage"] - 131.0) < 0.1

    def test_r_rank1_with_60ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 6, 60)
        r = abilities["R"]
        assert abs(r["damage_per_cast"] - 96.0) < 0.1
        assert r["total_casts"] == 3

    def test_q_rank5_with_215ap(self, ahri_data: dict) -> None:
        # JSON (16.13.1): Q "Damage Per Pass" rank 5 = 135 + 50% AP.
        # 135 + 0.5 * 215 = 242.5.
        abilities = parse_ahri_abilities(ahri_data, 11, 215)
        q = abilities["Q"]
        assert q["rank"] == 5
        assert abs(q["magic_damage"] - 242.5) < 0.1

    def test_w_rank5_with_572ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 18, 572)
        w = abilities["W"]
        assert w["rank"] == 5
        assert abs(w["initial_damage"] - 348.8) < 0.1

    def test_e_rank5_with_572ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 18, 572)
        e = abilities["E"]
        assert abs(e["magic_damage"] - 726.2) < 0.1

    def test_r_rank3_with_572ap(self, ahri_data: dict) -> None:
        abilities = parse_ahri_abilities(ahri_data, 18, 572)
        r = abilities["R"]
        assert abs(r["damage_per_cast"] - 375.2) < 0.1


class TestActualizerFightDamage:
    """Test Actualizer Q damage in a full fight calculation."""

    @pytest.fixture
    def ahri_data(self) -> dict:
        from src.calculator.data_fetcher import get_champion

        return get_champion("Ahri")

    @pytest.fixture
    def actualizer(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Actualizer")

    def test_ahri_q_with_actualizer_active(
        self,
        ahri_data: dict,
        actualizer: dict,
    ) -> None:
        """Ahri level 18, only Actualizer, Q vs 1000 HP / 100 MR / 100 Armor.

        JSON (16.13.1): Q rank 5 per pass = 135 + 0.5 * 90 AP = 180.
        Magic pass vs 100 MR = 90; true pass = 180; sum = 270.
        Actualizer amp = 1.15 + 0.005 * (300 bonus mana / 100) = 1.165.
        270 * 1.165 = 314.55 total Q damage.
        """
        from src.calculator.stats import calculate_total_stats

        items = [actualizer]
        stats = calculate_total_stats(ahri_data, 18, items)
        # Only care about Q damage
        abilities = parse_ahri_abilities(
            ahri_data,
            18,
            stats["ability_power"],
            ability_ranks={"Q": 5},
        )
        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            include_actives=True,
        )
        q_damage = fight["breakdown"]["Q"]["total_damage"]
        assert abs(q_damage - 314.55) <= 2, f"Q damage {q_damage:.1f} expected ~314.55"
